"""
Step 2 — VERIFY

Turns raw ingested material into a small list of "verified facts" that
step 3 (generation) is allowed to use. Two tiers of trust:

  1. Canonical AWS docs pages (exam guide, in/out-of-scope lists) are
     trusted directly — no corroboration needed, since they ARE the
     source of truth for what's testable.

  2. RSS/blog items are treated as leads, not facts. Each one only gets
     promoted to "verified" if a service/feature it names also appears
     on the current canonical in-scope or out-of-scope list — i.e. the
     canonical source corroborates it. Anything that can't be
     corroborated this way is logged but excluded from generation input.

This mirrors exactly what was done manually earlier in this project:
service-lifecycle claims (Kendra, Q Business, GuardDuty, Bedrock Agents)
were only trusted once cross-checked against the live exam guide's
in-scope/out-of-scope pages, not from a single blog post alone.
"""
import json
import os
import sys
from datetime import datetime, timezone

from config import ANTHROPIC_API_KEY, AUDIT_MODEL, VERIFIED_DIR, SNAPSHOT_DIR

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_today_snapshot():
    path = os.path.join(SNAPSHOT_DIR, f"{TODAY}.json")
    with open(path) as f:
        return json.load(f)


def facts_from_service_changes(snapshot):
    """Tier 1: directly from the canonical diff computed in ingest.py — no LLM needed."""
    facts = []
    for page_key, change in snapshot.get("service_changes_vs_previous", {}).items():
        url = snapshot["canonical"][page_key]["url"]
        for svc in change.get("added", []):
            facts.append({
                "fact": f"{svc} was added to the '{page_key}' list on the official exam guide.",
                "source_url": url,
                "trust_tier": 1,
                "category": "service_scope_change",
            })
        for svc in change.get("removed", []):
            facts.append({
                "fact": f"{svc} was removed from the '{page_key}' list on the official exam guide "
                        f"(may indicate deprecation, rename, or consolidation — verify current status "
                        f"before using as a 'correct answer').",
                "source_url": url,
                "trust_tier": 1,
                "category": "service_scope_change",
            })
    return facts


def current_service_names(snapshot):
    names = set()
    for key in ("in_scope_services", "out_of_scope_services"):
        names |= set(snapshot["canonical"].get(key, {}).get("services", []))
    return names


def try_llm_extract(client, item, model):
    """Ask the model to pull one short factual claim + the service it's about, nothing else."""
    prompt = f"""You will be given an RSS item title and summary about AWS.
Extract ONE short, neutral factual claim it makes (max 25 words), and the
single AWS service/feature name it is primarily about. If the item makes
no clear factual claim about a specific named AWS service or feature,
respond with exactly: NONE

Title: {item['title']}
Summary: {item['summary']}

Respond in this exact format (two lines, nothing else):
SERVICE: <service name as AWS writes it, e.g. "Amazon Bedrock">
CLAIM: <the claim>"""
    resp = client.messages.create(
        model=model,
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text == "NONE" or "SERVICE:" not in text:
        return None
    lines = text.split("\n")
    service = next((l.split("SERVICE:", 1)[1].strip() for l in lines if l.startswith("SERVICE:")), None)
    claim = next((l.split("CLAIM:", 1)[1].strip() for l in lines if l.startswith("CLAIM:")), None)
    if not service or not claim:
        return None
    return {"service": service, "claim": claim}


def facts_from_rss(snapshot):
    """Tier 2: RSS leads, promoted only if corroborated against the canonical service lists."""
    items = snapshot.get("rss_items", [])
    if not items:
        return [], []

    known_services = current_service_names(snapshot)
    verified, unverified = [], []

    client = None
    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            print("[verify] anthropic package not installed; falling back to keyword-only mode", file=sys.stderr)

    for item in items:
        extracted = None
        if client:
            try:
                extracted = try_llm_extract(client, item, AUDIT_MODEL)
            except Exception as e:
                print(f"[verify] LLM extraction failed for '{item['title']}': {e}", file=sys.stderr)

        if not extracted:
            # fallback: no LLM available — just check title text for a known service name
            for svc in known_services:
                if svc.lower() in item["title"].lower():
                    extracted = {"service": svc, "claim": item["title"]}
                    break

        if not extracted:
            unverified.append({**item, "reason": "no extractable claim"})
            continue

        # corroboration check: does the canonical source currently mention this service at all?
        corroborated = any(extracted["service"].lower() in s.lower() or s.lower() in extracted["service"].lower()
                            for s in known_services)

        record = {
            "fact": extracted["claim"],
            "service": extracted["service"],
            "source_url": item["link"],
            "trust_tier": 2,
            "category": "news_lead",
            "corroborated_against_canonical": corroborated,
        }
        if corroborated:
            verified.append(record)
        else:
            unverified.append(record)

    return verified, unverified


def main():
    snapshot = load_today_snapshot()

    tier1_facts = facts_from_service_changes(snapshot)
    tier2_verified, tier2_unverified = facts_from_rss(snapshot)

    all_verified = tier1_facts + tier2_verified

    os.makedirs(VERIFIED_DIR, exist_ok=True)
    out_path = os.path.join(VERIFIED_DIR, f"{TODAY}.json")
    with open(out_path, "w") as f:
        json.dump({
            "date": TODAY,
            "verified_facts": all_verified,
            "unverified_leads": tier2_unverified,
        }, f, indent=2)

    print(f"[verify] {len(tier1_facts)} tier-1 (canonical) facts, "
          f"{len(tier2_verified)} tier-2 (corroborated) facts, "
          f"{len(tier2_unverified)} leads left unverified")
    print(f"[verify] wrote {out_path}")

    if not all_verified:
        print("[verify] NOTE: no new facts today — generation step will reuse the standing "
              "domain content (exam guide domains 1-5) rather than skip the run.")


if __name__ == "__main__":
    main()
