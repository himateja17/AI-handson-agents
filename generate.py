"""
Step 3 — GENERATE

Writes new practice questions using Claude (Haiku tier by default — this
is a well-specified, formulaic task, not a reasoning-heavy one, so the
cheapest capable model is the right call).

Grounding rule: every question must be traceable to either
  (a) the standing canonical exam-guide text for its domain, or
  (b) a specific verified fact from today's verify.py output.
The model is given ONLY that material — never raw/unverified scrape data
— and is required to tag each question with the source it used, so
qa_dedupe.py can mechanically reject anything that cites a source that
doesn't exist in what it was given.
"""
import json
import os
import sys
from datetime import datetime, timezone

import anthropic

from config import (
    ANTHROPIC_API_KEY, GENERATION_MODEL, DOMAIN_WEIGHTS, DAILY_QUESTION_TARGET,
    SNAPSHOT_DIR, VERIFIED_DIR, QUESTIONS_FILE, ROOT,
)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
CANDIDATES_DIR = os.path.join(ROOT, "data", "candidates")

SYSTEM_PROMPT = """You write multiple-choice practice questions for the AWS Certified AI \
Practitioner (AIF-C01) exam.

Hard rules:
- Use ONLY the "SOURCE MATERIAL" given to you. Never invent AWS service names, \
features, prices, or lifecycle status that isn't in the source material.
- Every question must be answerable from the source material alone.
- Exactly 4 options (A-D), exactly one correct.
- Match the real exam's style: scenario-based where natural, plain factual recall \
otherwise. No trick questions, no ambiguous wording.
- Do not write a question that is a near-duplicate (same tested concept + same \
correct answer) of anything in "EXISTING QUESTIONS TO AVOID DUPLICATING".
- Output ONLY a JSON array, no prose before or after. Each element:
  {"question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, \
"correct": "A", "rationale": "one sentence", "source_ref": "<exact string copied \
from the SOURCE MATERIAL that grounds this question>"}
"""


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def build_source_material(snapshot, verified, domain_key, domain_page_key):
    """Combine the standing canonical domain text with any fresh verified facts."""
    parts = []
    domain_text = snapshot["canonical"].get(domain_page_key, {}).get("text", "")
    if domain_text:
        parts.append(f"--- Official exam guide, {domain_page_key} ---\n{domain_text[:6000]}")

    scope_text = snapshot["canonical"].get("in_scope_services", {}).get("text", "")
    if scope_text:
        parts.append(f"--- In-scope AWS services (official) ---\n{scope_text[:3000]}")

    out_scope_text = snapshot["canonical"].get("out_of_scope_services", {}).get("text", "")
    if out_scope_text:
        parts.append(f"--- Out-of-scope AWS services (official) ---\n{out_scope_text[:2000]}")

    relevant_facts = [f for f in verified.get("verified_facts", [])]
    if relevant_facts:
        facts_txt = "\n".join(f"- {f['fact']} (source: {f['source_url']})" for f in relevant_facts)
        parts.append(f"--- Newly verified facts (today) ---\n{facts_txt}")

    return "\n\n".join(parts)


def existing_questions_for_domain(all_questions, domain_key):
    return [q["question"] for q in all_questions if q.get("domain") == domain_key]


def questions_needed_per_domain(all_questions, target=DAILY_QUESTION_TARGET):
    """Split today's target across domains by the official weighting."""
    counts = {d: round(w * target) for d, w in DOMAIN_WEIGHTS.items()}
    diff = target - sum(counts.values())
    if diff != 0:
        last_domain = list(DOMAIN_WEIGHTS.keys())[-1]
        counts[last_domain] += diff
    return counts


DOMAIN_PAGE_KEY = {
    "DOMAIN 1 — Fundamentals of AI and ML": "domain1",
    "DOMAIN 2 — Fundamentals of Generative AI": "domain2",
    "DOMAIN 3 — Applications of Foundation Models": "domain3",
    "DOMAIN 4 — Guidelines for Responsible AI": "domain4",
    "DOMAIN 5 — Security, Compliance, and Governance for AI Solutions": "domain5",
}


def generate_for_domain(client, snapshot, verified, all_questions, domain_key, count):
    if count <= 0:
        return []
    source_material = build_source_material(snapshot, verified, domain_key, DOMAIN_PAGE_KEY[domain_key])
    existing = existing_questions_for_domain(all_questions, domain_key)
    existing_sample = existing[-60:]  # recent slice keeps the prompt bounded as the bank grows

    user_prompt = f"""SOURCE MATERIAL:
{source_material}

EXISTING QUESTIONS TO AVOID DUPLICATING (this domain, most recent {len(existing_sample)}):
{json.dumps(existing_sample, indent=2)}

Write exactly {count} new questions for: {domain_key}
Output the JSON array now."""

    resp = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    # strip accidental code fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[generate] WARNING: could not parse model output for {domain_key}: {e}", file=sys.stderr)
        return []

    for item in items:
        item["domain"] = domain_key
        item["date_added"] = TODAY
    return items


def main():
    if not ANTHROPIC_API_KEY:
        print("[generate] ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    snapshot = load_json(os.path.join(SNAPSHOT_DIR, f"{TODAY}.json"))
    verified = load_json(os.path.join(VERIFIED_DIR, f"{TODAY}.json"), default={"verified_facts": []})
    all_questions = load_json(QUESTIONS_FILE, default=[])

    if not snapshot:
        print("[generate] ERROR: no snapshot for today — run ingest.py first", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    counts = questions_needed_per_domain(all_questions)
    print(f"[generate] target split: {counts}")

    all_candidates = []
    source_materials = {}
    for domain_key, count in counts.items():
        source_materials[domain_key] = build_source_material(
            snapshot, verified, domain_key, DOMAIN_PAGE_KEY[domain_key]
        )
        items = generate_for_domain(client, snapshot, verified, all_questions, domain_key, count)
        print(f"[generate] {domain_key}: requested {count}, got {len(items)}")
        all_candidates.extend(items)

    os.makedirs(CANDIDATES_DIR, exist_ok=True)
    out_path = os.path.join(CANDIDATES_DIR, f"{TODAY}.json")
    with open(out_path, "w") as f:
        json.dump(all_candidates, f, indent=2)

    # Save the exact source material each domain was grounded in, so qa_dedupe.py
    # can mechanically verify each question's source_ref actually appears in it.
    src_path = os.path.join(CANDIDATES_DIR, f"{TODAY}_source_material.json")
    with open(src_path, "w") as f:
        json.dump(source_materials, f, indent=2)

    print(f"[generate] wrote {len(all_candidates)} candidates to {out_path}")


if __name__ == "__main__":
    main()
