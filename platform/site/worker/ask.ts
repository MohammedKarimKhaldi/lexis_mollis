// Server-side counterpart to scripts/rag_ask.py: retrieval here runs inside
// the Worker over a small pre-built keyword index (platform/scripts/
// build_site_data.py writes /data/ask_index.json — title/tags/preview words,
// deduped, per document), then the assembled context + question go to the
// same free OpenCode Zen model. The API key lives only as a Worker secret —
// never sent to the browser — so this is the only place it's safe to call it.
//
// Deliberately NOT using a full-text search library (e.g. MiniSearch) here:
// tokenizing/indexing the whole corpus, or even just parsing+compiling that
// library's code, blew through the Workers free-plan CPU budget (~10ms) and
// every request failed with error 1102. A plain substring-overlap scan over
// a small pre-tokenized JSON file is cheap enough to fit comfortably.

export interface Env {
  ASSETS: Fetcher;
  OPENCODE_API_KEY?: string;
}

const API_URL = "https://opencode.ai/zen/v1/chat/completions";
const API_MODEL = "big-pickle";
const MAX_HITS = 6;

const SYSTEM_PROMPT =
  "Tu es un assistant de recherche qui répond STRICTEMENT à partir des extraits de documents " +
  "fournis (corpus de traités et instruments juridiques Lexis Mollis, OCR historique, parfois " +
  "imparfait). Si l'information n'est pas dans le contexte fourni, dis-le clairement plutôt que " +
  "d'inventer. Cite systématiquement l'identifiant de document entre crochets (ex. [16460004_s1]) " +
  "et l'année quand c'est pertinent. Réponds dans la langue de la question.";

interface AskIndexDoc {
  id: string;
  title?: string;
  year?: number;
  doc_type?: string;
  treaty_id?: string;
  kw?: string;
}

interface SearchHit extends AskIndexDoc {
  document_id: string;
  score: number;
}

interface DocDetail {
  document_id: string;
  title?: string;
  year?: number;
  doc_type?: string;
  treaty_id?: string;
  text_preview?: string;
  similar_documents?: { document_id: string; title?: string; type?: string; score?: number }[];
}

let cachedAskIndex: AskIndexDoc[] | null = null;

async function loadAskIndex(env: Env, origin: string): Promise<AskIndexDoc[]> {
  if (cachedAskIndex) return cachedAskIndex;
  const response = await env.ASSETS.fetch(new URL("/data/ask_index.json", origin));
  cachedAskIndex = ((await response.json()) as AskIndexDoc[]) || [];
  return cachedAskIndex;
}

function searchAskIndex(query: string, docs: AskIndexDoc[], limit: number): SearchHit[] {
  const queryWords = Array.from(new Set(query.toLowerCase().match(/[a-zà-öø-ÿ0-9]{3,}/g) || []));
  if (!queryWords.length) return [];
  const scored: SearchHit[] = [];
  for (const doc of docs) {
    const kw = doc.kw || "";
    let score = 0;
    for (const word of queryWords) {
      if (kw.includes(word)) score += 1;
    }
    if (score > 0) scored.push({ ...doc, document_id: doc.id, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit);
}

async function fetchDocDetail(env: Env, origin: string, documentId: string): Promise<DocDetail | null> {
  const response = await env.ASSETS.fetch(new URL(`/data/docs/${encodeURIComponent(documentId)}.json`, origin));
  if (!response.ok) return null;
  return (await response.json()) as DocDetail;
}

function buildContext(hits: SearchHit[], details: (DocDetail | null)[]): string {
  const blocks: string[] = [];
  hits.forEach((hit, i) => {
    const detail = details[i];
    const title = detail?.title || hit.title || hit.document_id;
    const lines = [
      `### [${hit.document_id}] ${title} (${detail?.year ?? hit.year ?? "année n/a"}, score=${hit.score.toFixed(2)})`,
      `Traité : ${detail?.treaty_id || hit.treaty_id || "n/a"} · Type : ${detail?.doc_type || hit.doc_type || "n/a"}`,
      "",
      (detail?.text_preview || "").trim()
    ];
    const related = (detail?.similar_documents || []).slice(0, 4);
    if (related.length) {
      lines.push(
        "",
        "Documents liés : " +
          related
            .map((r) => `${r.title || r.document_id} [${r.document_id}] (${r.type || "similar_to"}, ${Number(r.score ?? 0).toFixed(2)})`)
            .join("; ")
      );
    }
    blocks.push(lines.join("\n"));
  });
  return blocks.join("\n\n---\n\n");
}

async function askLLM(question: string, context: string, apiKey: string): Promise<string> {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: API_MODEL,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: `Contexte :\n\n${context}\n\n---\n\nQuestion : ${question}` }
      ],
      temperature: 0.2
    })
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`LLM ${response.status}: ${body.slice(0, 300)}`);
  }
  const data = (await response.json()) as { choices?: { message?: { content?: string } }[] };
  return data.choices?.[0]?.message?.content ?? "";
}

async function handleAsk(request: Request, env: Env, origin: string): Promise<Response> {
  let query = "";
  try {
    const body = (await request.json()) as { query?: string };
    query = (body.query || "").trim();
  } catch {
    return Response.json({ error: "Corps de requête JSON invalide." }, { status: 400 });
  }
  if (!query) {
    return Response.json({ error: "Question vide." }, { status: 400 });
  }

  const askDocs = await loadAskIndex(env, origin);
  const hits = searchAskIndex(query, askDocs, MAX_HITS);
  if (!hits.length) {
    return Response.json({
      answer: "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
      sources: []
    });
  }

  const details = await Promise.all(hits.map((hit) => fetchDocDetail(env, origin, hit.document_id)));
  const context = buildContext(hits, details);
  const sources = hits.map((hit) => ({
    document_id: hit.document_id,
    title: hit.title,
    year: hit.year,
    score: hit.score
  }));

  if (!env.OPENCODE_API_KEY) {
    return Response.json({
      answer: null,
      sources,
      error: "La clé OPENCODE_API_KEY n'est pas configurée côté serveur (wrangler secret put OPENCODE_API_KEY)."
    });
  }

  try {
    const answer = await askLLM(query, context, env.OPENCODE_API_KEY);
    return Response.json({ answer, sources });
  } catch (error) {
    return Response.json(
      { answer: null, sources, error: error instanceof Error ? error.message : String(error) },
      { status: 502 }
    );
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/ask") {
      if (request.method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }
      return handleAsk(request, env, url.origin);
    }
    return env.ASSETS.fetch(request);
  }
};
