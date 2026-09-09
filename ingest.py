"""
Step 1 — INGEST
Pulls the canonical AWS exam-guide pages (always) and recent RSS items
(filtered for relevance), saves a dated snapshot, and computes a diff
against the most recent prior snapshot so downstream steps only have to
look at what changed.

Deliberately does NOT do open-ended web crawling or paid search APIs —
the source list is fixed and small, which keeps this both cheap and
auditable (every fact traces back to one of a handful of known URLs).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser

import feedparser
import requests

from config import CANONICAL_SOURCES, RSS_SOURCES, RELEVANCE_KEYWORDS, SNAPSHOT_DIR

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TextExtractor(HTMLParser):
    """Minimal HTML->text so we can diff page content without a heavy parser dependency."""
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)

    def get_text(self):
        return "\n".join(self.chunks)


def fetch_page_text(url, timeout=20):
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "aif-c01-quiz-agent/1.0"})
    resp.raise_for_status()
    parser = TextExtractor()
    parser.feed(resp.text)
    return parser.get_text()


def extract_service_list(text):
    """
    The in-scope/out-of-scope pages are bulleted lists of service names.
    Pull out lines that look like a service name (short, capitalized, no
    sentence punctuation) rather than trying to parse the HTML structure,
    since AWS restructures these pages periodically.
    """
    candidates = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 80:
            continue
        if line.endswith((".", ":", "?")):
            continue
        if re.match(r"^(Amazon|AWS)\s+[A-Z]", line):
            candidates.append(line)
    return sorted(set(candidates))


def fetch_canonical_sources():
    out = {}
    for key, url in CANONICAL_SOURCES.items():
        try:
            text = fetch_page_text(url)
            entry = {"url": url, "fetched_at": TODAY, "text": text}
            if "scope" in key:
                entry["services"] = extract_service_list(text)
            out[key] = entry
            print(f"[ingest] fetched {key} ({len(text)} chars)")
        except Exception as e:
            print(f"[ingest] WARNING: failed to fetch {key} ({url}): {e}", file=sys.stderr)
    return out


def fetch_rss_items():
    items = []
    for feed_name, feed_url in RSS_SOURCES.items():
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:30]:
                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")
                link = getattr(entry, "link", "")
                blob = f"{title} {summary}".lower()
                if any(kw in blob for kw in RELEVANCE_KEYWORDS):
                    items.append({
                        "feed": feed_name,
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "published": getattr(entry, "published", ""),
                    })
            print(f"[ingest] {feed_name}: {len(parsed.entries)} items, "
                  f"{sum(1 for i in items if i['feed']==feed_name)} relevant")
        except Exception as e:
            print(f"[ingest] WARNING: failed to fetch RSS {feed_name}: {e}", file=sys.stderr)
    return items


def load_previous_snapshot():
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    files = sorted(f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json") and f < f"{TODAY}.json")
    if not files:
        return None
    with open(os.path.join(SNAPSHOT_DIR, files[-1])) as f:
        return json.load(f)


def diff_service_lists(prev, curr):
    changes = {}
    for key in curr:
        if "services" not in curr[key]:
            continue
        curr_services = set(curr[key]["services"])
        prev_services = set(prev.get(key, {}).get("services", [])) if prev else set()
        added = sorted(curr_services - prev_services)
        removed = sorted(prev_services - curr_services)
        if added or removed:
            changes[key] = {"added": added, "removed": removed}
    return changes


def main():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    canonical = fetch_canonical_sources()
    rss_items = fetch_rss_items()
    prev = load_previous_snapshot()

    service_changes = diff_service_lists(prev, canonical)
    if service_changes:
        print(f"[ingest] SERVICE LIST CHANGES DETECTED: {json.dumps(service_changes, indent=2)}")

    snapshot = {
        "date": TODAY,
        "canonical": canonical,
        "rss_items": rss_items,
        "service_changes_vs_previous": service_changes,
    }

    out_path = os.path.join(SNAPSHOT_DIR, f"{TODAY}.json")
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"[ingest] wrote snapshot to {out_path}")
    print(f"[ingest] {len(rss_items)} relevant RSS items, "
          f"{len(service_changes)} pages with service-list changes")


if __name__ == "__main__":
    main()
