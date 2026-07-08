import csv, re, json
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
METADATA_DIR = BASE_DIR / "metadata"
LISTE_PDFS = TRAITES_DIR / "liste_pdfs.txt"
METADATA_DIR.mkdir(exist_ok=True)

with open(LISTE_PDFS, "r") as f:
    lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

TYPE_KEYWORD_PATTERNS = [
    (r'^traité', 'Traité'),
    (r'^convention', 'Convention'),
    (r'^accord', 'Accord'),
    (r'^protocole', 'Protocole'),
    (r'^déclaration', 'Déclaration'),
    (r'^arrangement', 'Arrangement'),
    # [eé] rather than a bare é: some source titles drop the accent
    # ("Echange de lettres") -- purely an OCR/scraping artifact upstream,
    # not a different type.
    (r'^[eé]change de lettres', 'Échange de lettres'),
    (r'^[eé]change de notes', 'Échange de notes'),
    (r'^lettre', 'Lettre'),
    # Ratification, acceptance, approval and accession are the four standard
    # means of expressing consent to a treaty (Vienna Convention on the Law
    # of Treaties, Art. 11) -- "adhésion" is the French term for accession,
    # hence folding "accession"-worded titles and the "ahésion" typo into the
    # same label rather than treating them as a different type.
    (r"^instrument d'?(adh[ée]sion|ah[ée]sion|accession)", "Instrument d'adhésion"),
    (r'^instrument de ratification', 'Instrument de ratification'),
    (r"^instrument d'?approbation", "Instrument d'approbation"),
    (r"^instrument d'?acceptation", "Instrument d'acceptation"),
    (r'^instrument de succession', 'Instrument de succession'),
    (r'^pouvoirs', 'Pouvoirs'),
    # [\s-] rather than a bare hyphen: many source titles use "procès verbal"
    # (space) instead of "procès-verbal" (hyphen).
    (r'^proc[èe]s[\s-]verba', 'Procès-verbal'),
    (r'^note verbale', 'Note verbale'),
    # Formal acknowledgment-of-receipt records -- a distinct, recurring
    # administrative act with no other label fitting it. Covers "accusé de
    # réception", "accusé réception" (no "de"), and the plural/hyphenated
    # "accusé(s)-réception" variants seen in the source titles.
    (r'^accusés?[\s-]?(de\s+)?r[ée]ception', 'Accusé de réception'),
    (r'^certificat', 'Certificat'),
    (r'^notification', 'Notification'),
    # Titles that just say "Ratification ..." without the "Instrument de"
    # prefix (e.g. "Ratification mauritanienne") -- same underlying act,
    # folded into the existing label rather than left unclassified.
    (r'^ratifications?\b', 'Instrument de ratification'),
    (r'^m[ée]morandum', 'Memorandum'),
    (r'^minutes', 'Minutes'),
]

# "Texte(s) de/du/des X" titles describe the TEXT of instrument X -- a flat
# "Texte" label alone isn't informative for corpus-wide comparison (nearly
# every document "is the text of" something), and it was swallowing hundreds
# of documents whose real type (Accord, Déclaration, Memorandum, ...) was
# right there in the title. If X matches a known type, classify by X instead;
# only fall back to "Texte" when X isn't recognizable (e.g. "Texte de
# l'avenant", "Texte du document cadre").
TEXTE_OF_PREFIX = re.compile(r'^textes? (?:de|du|des)\s+')
LEADING_ARTICLE = re.compile(r"^(?:l['’]|la\s+|le\s+|les\s+|du\s+|des\s+)")

# Some titles lead with a short label before the actual type, e.g. "France -
# Procès-verbal de dépôt..." or "Transmission de l'instrument : note verbale
# des autorités monténégrines" -- the type is genuinely stated, just not at
# position 0. Only strip a SHORT leading segment (<=40 chars) before a "-" or
# ":" separator, so this can't accidentally eat into a long descriptive title
# and misfire on unrelated text.
LEADING_LABEL_PREFIX = re.compile(r'^[^-:]{1,40}[-:]\s*')


def normalize_doc_type(title):
    if not title:
        return "Inconnu"
    t = title.lower().strip()
    base = re.sub(r'\(.*?\)', '', t).strip()

    texte_of = TEXTE_OF_PREFIX.match(base)
    if texte_of:
        remainder = LEADING_ARTICLE.sub('', base[texte_of.end():].strip()).strip()
        for pattern, label in TYPE_KEYWORD_PATTERNS:
            if re.match(pattern, remainder):
                return label
        return 'Texte'

    for pattern, label in TYPE_KEYWORD_PATTERNS:
        if re.search(pattern, base):
            return label

    label_prefix = LEADING_LABEL_PREFIX.match(base)
    if label_prefix:
        remainder = base[label_prefix.end():].strip()
        for pattern, label in TYPE_KEYWORD_PATTERNS:
            if re.match(pattern, remainder):
                return label

    return "Autre"

records = []
for line in lines:
    parts = line.split("|")
    if len(parts) < 4:
        continue
    url, filename, ref, title = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    treaty_id = ""
    treaty_number = ""
    if "/" in ref:
        treaty_id, treaty_number = ref.split("/", 1)
    elif ref.startswith("TRA") or ref.startswith("tra"):
        treaty_id = ref
    year = None
    year_match = re.search(r'(?:TRA|tra)?(\d{4})', treaty_id)
    if year_match:
        year = int(year_match.group(1))
    doc_type = normalize_doc_type(title)
    filepath = TRAITES_DIR / filename
    file_exists = filepath.exists()
    file_size = filepath.stat().st_size if file_exists else 0
    records.append({
        "filename": filename,
        "url": url,
        "treaty_id": treaty_id,
        "treaty_number": treaty_number,
        "title": title,
        "doc_type": doc_type,
        "year": year,
        "file_exists": file_exists,
        "file_size": file_size,
    })
# Write CSV
csv_path = METADATA_DIR / "parsed_metadata.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=records[0].keys())
    w.writeheader()
    w.writerows(records)

# Write JSON
json_path = METADATA_DIR / "parsed_metadata.json"
with open(json_path, "w") as f:
    json.dump(records, f, indent=2, ensure_ascii=False)

# Summary
local_count = sum(1 for r in records if r["file_exists"])
missing_count = sum(1 for r in records if not r["file_exists"])
print(f"Total entries: {len(records)}")
print(f"Files present: {local_count}  Missing: {missing_count}")
print(f"Year range: {min(r['year'] for r in records if r['year'])} - {max(r['year'] for r in records if r['year'])}")

# Doc type distribution
type_counts = Counter(r["doc_type"] for r in records)
print("\nDocument type distribution:")
for t, c in type_counts.most_common():
    print(f"  {t}: {c}")

# Year distribution
year_counts = Counter(r["year"] for r in records if r["year"])
print(f"\nUnique treaties: {len(set(r['treaty_id'] for r in records if r['treaty_id']))}")
print(f"Years with most documents: {year_counts.most_common(10)}")
