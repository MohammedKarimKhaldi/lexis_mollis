import os, time, json
from pathlib import Path
import requests
from tqdm import tqdm

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
METADATA_DIR = BASE_DIR / "metadata"
LISTE_PDFS = TRAITES_DIR / "liste_pdfs.txt"

METADATA_DIR.mkdir(exist_ok=True)

with open(LISTE_PDFS, "r") as f:
    lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

missing = []
existing_count = 0
for line in lines:
    parts = line.split("|")
    if len(parts) >= 2:
        url, filename = parts[0].strip(), parts[1].strip()
        filepath = TRAITES_DIR / filename
        if not filepath.exists():
            missing.append((url, filename))
        else:
            existing_count += 1

print(f"Already have: {existing_count}  Missing: {len(missing)}")

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*"})

log = []
success = 0
fail = 0
for url, filename in tqdm(missing, desc="Downloading PDFs"):
    filepath = TRAITES_DIR / filename
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(r.content)
            log.append({"filename": filename, "url": url, "status": "ok", "size": len(r.content)})
            success += 1
        else:
            log.append({"filename": filename, "url": url, "status": f"http_{r.status_code}"})
            fail += 1
    except Exception as e:
        log.append({"filename": filename, "url": url, "status": f"error_{e}"})
        fail += 1
    time.sleep(0.1)

with open(METADATA_DIR / "download_log.json", "w") as f:
    json.dump(log, f, indent=2)

print(f"Downloaded: {success}  Failed: {fail}")
