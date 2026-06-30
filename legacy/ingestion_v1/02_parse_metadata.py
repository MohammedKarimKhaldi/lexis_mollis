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

def normalize_doc_type(title):
    if not title:
        return "Inconnu"
    t = title.lower().strip()
    base = re.sub(r'\(.*?\)', '', t).strip()
    patterns = [
        (r'^traité', 'Traité'),
        (r'^convention', 'Convention'),
        (r'^accord', 'Accord'),
        (r'^protocole', 'Protocole'),
        (r'^déclaration', 'Déclaration'),
        (r'^arrangement', 'Arrangement'),
        (r'^échange de lettres', 'Échange de lettres'),
        (r'^lettre', 'Lettre'),
        (r"^instrument d'?adhésion", "Instrument d'adhésion"),
        (r'^instrument de ratification', 'Instrument de ratification'),
        (r'^pouvoirs', 'Pouvoirs'),
        (r'^procès-verbal', 'Procès-verbal'),
        (r'^note verbale', 'Note verbale'),
        (r'^certificat', 'Certificat'),
        (r'^notification', 'Notification'),
        (r'^texte de', 'Texte'),
        (r'^minutes', 'Minutes'),
    ]
    for pattern, label in patterns:
        if re.search(pattern, base):
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
