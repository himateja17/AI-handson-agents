"""
Step 5 — PUBLISH

Appends today's accepted questions to site/questions.json (the file the
live site fetches at load). Also updates a small manifest the site can
show ("last updated", "total questions") without needing to count the
array client-side.
"""
import json
import os
from datetime import datetime, timezone

from config import QUESTIONS_FILE, ROOT, SITE_DIR

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
ACCEPTED_DIR = os.path.join(ROOT, "data", "accepted")
MANIFEST_FILE = os.path.join(SITE_DIR, "manifest.json")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def main():
    accepted = load_json(os.path.join(ACCEPTED_DIR, f"{TODAY}.json"), default=[])
    if not accepted:
        print("[publish] nothing accepted today — leaving questions.json unchanged")
        accepted = []

    existing = load_json(QUESTIONS_FILE, default=[])
    updated = existing + accepted

    with open(QUESTIONS_FILE, "w") as f:
        json.dump(updated, f, indent=2)

    domain_counts = {}
    for q in updated:
        domain_counts[q["domain"]] = domain_counts.get(q["domain"], 0) + 1

    manifest = {
        "total_questions": len(updated),
        "last_updated": TODAY,
        "added_today": len(accepted),
        "domain_counts": domain_counts,
    }
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"[publish] {len(accepted)} new questions added, {len(updated)} total, "
          f"wrote {QUESTIONS_FILE} and {MANIFEST_FILE}")


if __name__ == "__main__":
    main()
