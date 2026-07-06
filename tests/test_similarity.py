from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from pdfkb.similarity.chunking import chunk_pages
from pdfkb.similarity.config import SimilarityConfig
from pdfkb.similarity.doc_type_profiles import build_doc_type_profiles
from pdfkb.similarity.embeddings import embed_chunks
from pdfkb.similarity.index import semantic_pairs
from pdfkb.similarity.io import read_parquet_records, write_parquet_records
from pdfkb.similarity.lexical import char_ngrams, lexical_pairs, normalise_lexical
from pdfkb.similarity.pairs import fuse_pairs


SHA_A = "a" * 64
SHA_B = "b" * 64


class FakeTokenizer:
    def __call__(self, text: str, **_: object) -> dict:
        import re

        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str], **_: object) -> np.ndarray:
        self.calls += len(texts)
        vectors = []
        for text in texts:
            vectors.append([float(len(text) + 1), float(sum(ord(ch) for ch in text) % 17 + 1)])
        return np.asarray(vectors, dtype=np.float32)


def page_record(source_sha: str, document_id: str, page_number: int, text: str, *, lang: str = "fr") -> dict:
    return {
        "document_id": document_id,
        "source_filename": f"{document_id}.PDF",
        "canonical_filename": f"{document_id}.PDF",
        "source_sha256": source_sha,
        "title": "Test",
        "treaty_id": None,
        "treaty_number": None,
        "doc_type": "Autre",
        "year": 1900,
        "pipeline_version": "2.0.1",
        "page_number": page_number,
        "page_count": 1,
        "language": [lang],
        "script": ["Latin"],
        "method": "native_pymupdf",
        "quality_score": 0.9,
        "review_required": False,
        "review_priority": "none",
        "review_reasons": [],
        "text": text,
    }


class SimilarityTests(unittest.TestCase):
    def test_chunking_is_deterministic_and_page_bounded(self) -> None:
        cfg = SimilarityConfig(target_tokens=4, overlap_tokens=1)
        pages = [
            page_record(SHA_A, "doc_a", 1, "one two three four five six"),
            page_record(SHA_B, "doc_b", 2, "alpha beta gamma"),
        ]
        first = list(chunk_pages(pages, cfg, FakeTokenizer()))
        second = list(chunk_pages(pages, cfg, FakeTokenizer()))
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 2)
        self.assertTrue(all(chunk["char_start"] >= 0 for chunk in first))
        self.assertTrue(any(":p0001:" in chunk["chunk_id"] for chunk in first))
        self.assertTrue(any(":p0002:" in chunk["chunk_id"] for chunk in first))
        self.assertTrue(all(chunk["source_sha256"] in {SHA_A, SHA_B} for chunk in first))

    def test_chunk_ids_preserve_document_aliases_for_duplicate_pdfs(self) -> None:
        cfg = SimilarityConfig(target_tokens=32, overlap_tokens=0)
        pages = [
            page_record(SHA_A, "doc_alias_a", 1, "same physical pdf, first documentary alias"),
            page_record(SHA_A, "doc_alias_b", 1, "same physical pdf, second documentary alias"),
        ]
        chunks = list(chunk_pages(pages, cfg, FakeTokenizer()))
        self.assertEqual(len(chunks), 2)
        self.assertEqual({chunk["source_sha256"] for chunk in chunks}, {SHA_A})
        self.assertEqual({chunk["document_id"] for chunk in chunks}, {"doc_alias_a", "doc_alias_b"})
        self.assertEqual(len({chunk["chunk_id"] for chunk in chunks}), 2)

    def test_lexical_normalisation_and_ngrams(self) -> None:
        self.assertEqual(normalise_lexical("État,  ÉTAT!"), "etat etat")
        self.assertEqual(char_ngrams("abc", 5), {"abc"})
        self.assertIn("etat", char_ngrams("État fédéral", 4))

    def test_minhash_finds_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = [
                self._chunk("c1", SHA_A, "doc_a", "Article premier. Les parties coopèrent durablement."),
                self._chunk("c2", SHA_B, "doc_b", "Article premier. Les parties coopèrent durablement."),
                self._chunk("c3", SHA_B, "doc_c", "Texte complètement différent sur un autre sujet."),
            ]
            chunks_pq = write_parquet_records(chunks, root / "chunks.parquet")
            pairs_pq = lexical_pairs(chunks_pq, SimilarityConfig(minhash_perm=64, lsh_threshold=0.8), root)
            pairs = read_parquet_records(pairs_pq)
            self.assertTrue(any({row["src"], row["dst"]} == {"c1", "c2"} and row["jaccard"] > 0.95 for row in pairs))

    def test_faiss_semantic_pairs_excludes_self(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            embeddings = np.asarray([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]], dtype=np.float32)
            np.save(root / "embeddings.npy", embeddings)
            write_parquet_records(
                [
                    {"row_index": 0, "chunk_id": "c1", "text_sha256": "1" * 64},
                    {"row_index": 1, "chunk_id": "c2", "text_sha256": "2" * 64},
                    {"row_index": 2, "chunk_id": "c3", "text_sha256": "3" * 64},
                ],
                root / "embeddings_index.parquet",
            )
            pairs_pq = semantic_pairs(root / "embeddings.npy", root / "embeddings_index.parquet", SimilarityConfig(knn=1), root)
            pairs = read_parquet_records(pairs_pq)
            self.assertTrue(all(row["src"] != row["dst"] for row in pairs))
            self.assertTrue(any({row["src"], row["dst"]} == {"c1", "c2"} for row in pairs))

    def test_embedding_cache_reuses_text_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = [
                self._chunk("c1", SHA_A, "doc_a", "same text"),
                self._chunk("c2", SHA_B, "doc_b", "same text"),
                self._chunk("c3", SHA_B, "doc_c", "different text"),
            ]
            chunks_pq = write_parquet_records(chunks, root / "chunks.parquet")
            model = FakeEmbeddingModel()

            def factory(_: SimilarityConfig) -> tuple[FakeEmbeddingModel, str]:
                return model, "fake-model"

            first = embed_chunks(chunks_pq, SimilarityConfig(batch_size=2), root, model_factory=factory)
            second = embed_chunks(chunks_pq, SimilarityConfig(batch_size=2), root, model_factory=factory)
            vectors = np.load(first.embeddings_path)
            norms = np.linalg.norm(vectors, axis=1)
            self.assertEqual(first.encoded_count, 2)
            self.assertEqual(second.encoded_count, 0)
            self.assertTrue(np.allclose(norms, 1.0, atol=1e-5))

    def test_fuse_pairs_validates_edge_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = [
                self._chunk("c1", SHA_A, "doc_a", "Texte A", lang=["fr"], quality=0.91),
                self._chunk("c2", SHA_B, "doc_b", "Texte B", lang=["en"], quality=0.82, review=True),
            ]
            chunks_pq = write_parquet_records(chunks, root / "chunks.parquet")
            lexical_pq = write_parquet_records([{"src": "c1", "dst": "c2", "jaccard": 0.1}], root / "lexical_pairs.parquet")
            semantic_pq = write_parquet_records([{"src": "c1", "dst": "c2", "cosine": 1.000001}], root / "semantic_pairs.parquet")
            edges_pq = fuse_pairs(lexical_pq, semantic_pq, chunks_pq, SimilarityConfig(), root)
            edges = read_parquet_records(edges_pq)
            self.assertEqual(edges[0]["type"], "translation")
            self.assertLessEqual(edges[0]["semantic"], 1.0)
            self.assertLessEqual(edges[0]["combined"], 1.0)
            self.assertTrue(edges[0]["provisional"])
            schema = json.loads(Path("metadata_design/edge.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(edges[0])

    def test_doc_type_profiles_detect_markers_and_compare_types(self) -> None:
        treaty_chunks = [
            self._typed_chunk(
                "t1c0", "doc_t1", "Traité", 0,
                "Les Hautes Parties contractantes, après avoir exhibé leurs pleins pouvoirs, "
                "sont convenus des articles suivants. Article premier. Article 2.",
            ),
            self._typed_chunk(
                "t1c1", "doc_t1", "Traité", 1,
                "En foi de quoi les plénipotentiaires ont signé. Fait à Paris le 3 mars 1919. "
                "Le présent traité sera ratifié et entrera en vigueur après ratification.",
            ),
            self._typed_chunk(
                "t2c0", "doc_t2", "Traité", 0,
                "Les Hautes Parties contractantes sont convenus des articles suivants. "
                "Article premier. Ratification requise pour l'entrée en vigueur.",
            ),
        ]
        declaration_chunks = [
            self._typed_chunk(
                "d1c0", "doc_d1", "Déclaration", 0,
                "Le soussigné, dûment autorisé, déclare par les présentes accéder aux dispositions "
                "ci-après énoncées, sans qu'aucun article numéroté ne soit requis.",
            ),
        ]
        chunks = treaty_chunks + declaration_chunks
        mapping = {"Traité": {"instrument_type": "treaty", "legal_force": "unknown"}}

        profiles = build_doc_type_profiles(chunks, mapping, min_documents=2)

        self.assertEqual(profiles["n_documents_total"], 3)
        self.assertEqual(profiles["n_chunks_total"], 4)
        self.assertIn("Traité", profiles["types"])
        self.assertIn("Déclaration", profiles["types"])

        treaty = profiles["types"]["Traité"]
        self.assertEqual(treaty["n_documents"], 2)
        self.assertEqual(treaty["instrument_type"], "treaty")
        self.assertFalse(treaty["low_sample_warning"])
        self.assertEqual(treaty["markers"]["hautes_parties_contractantes"]["document_fraction"], 1.0)
        self.assertEqual(treaty["markers"]["ratification"]["document_fraction"], 1.0)
        self.assertGreater(treaty["markers"]["article_numbered"]["avg_occurrences_per_document"], 0)
        self.assertIn("Traité", treaty["narrative_fr"])

        declaration = profiles["types"]["Déclaration"]
        self.assertEqual(declaration["n_documents"], 1)
        self.assertTrue(declaration["low_sample_warning"])
        # The declaration sample deliberately has no "Hautes Parties contractantes" /
        # numbered-article structure, unlike the treaty sample above — this is the
        # exact contrast a "compare document types" question needs to be answerable.
        self.assertEqual(declaration["markers"]["hautes_parties_contractantes"]["document_fraction"], 0.0)
        self.assertEqual(declaration["markers"]["soussigne_declare"]["document_fraction"], 1.0)
        self.assertLess(
            declaration["markers"]["article_numbered"]["avg_occurrences_per_document"],
            treaty["markers"]["article_numbered"]["avg_occurrences_per_document"],
        )

    def _typed_chunk(self, chunk_id: str, document_id: str, doc_type: str, chunk_index: int, text: str) -> dict:
        chunk = self._chunk(chunk_id, SHA_A, document_id, text)
        chunk["doc_type"] = doc_type
        chunk["chunk_index"] = chunk_index
        chunk["page_number"] = chunk_index + 1
        return chunk

    def _chunk(
        self,
        chunk_id: str,
        source_sha: str,
        document_id: str,
        text: str,
        *,
        lang: list[str] | None = None,
        quality: float = 0.9,
        review: bool = False,
    ) -> dict:
        from pdfkb.ids import text_sha256

        return {
            "chunk_id": chunk_id,
            "source_sha256": source_sha,
            "document_id": document_id,
            "source_filename": f"{document_id}.PDF",
            "title": "Test",
            "treaty_id": None,
            "year": 1900,
            "doc_type": "Autre",
            "page_number": 1,
            "chunk_index": 0,
            "char_start": 0,
            "char_end": len(text),
            "text": text,
            "text_sha256": text_sha256(text),
            "language": lang or ["fr"],
            "script": ["Latin"],
            "quality_score": quality,
            "review_required": review,
            "review_priority": "normal" if review else "none",
            "embedding_model": None,
            "embedding_created_at": None,
            "pipeline_version": "2.0.1",
            "tags": ["language:fr"],
        }


if __name__ == "__main__":
    unittest.main()
