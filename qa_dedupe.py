"""
Step 4 — QA / DEDUPE

Deliberately rule-based, not another expensive LLM pass, for everything
that CAN be checked mechanically:
  - schema validity
  - grounding (does source_ref actually appear in the material the model
    was given? if not, discard — it's either invented or misattributed)
  - duplicate detection against the full existing bank + within today's
    own batch, via simple sequence-similarity (no embeddings needed at
    this scale — a few hundred questions)

Only after mechanical checks pass does a small random sample go through
an independent LLM spot-check (audit_sample), which is the one place
this step spends tokens.
"""
import difflib
import json
import os
import random
import sys
from datetime import datetime, timezone

from config import (
    ANTHROPIC_API_KEY, AUDIT_MODEL, QUESTIONS_FILE, ROOT,
    DUPLICATE_SIMILARITY_THRESHOLD, AUDIT_SAMPLE_RATE,
)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
CANDIDATES_DIR = os.path.join(ROOT, "data", "candidates")
ACCEPTED_DIR = os.path.join(ROOT, "data", "accepted")
REJECTED_DIR = os.path.join(ROOT, "data", "rejected")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def valid_schema(q):
    if not isinstance(q.get("question"), str) or not q["question"].strip():
        return False
    opts = q.get("options")
    if not isinstance(opts, dict) or set(opts.keys()) != {"A", "B", "C", "D"}:
        return False
    if any(not isinstance(v, str) or not v.strip() for v in opts.values()):
        return False
    if len({v.strip().lower() for v in opts.values()}) != 4:
        return False  # duplicate option text within the same question
    if q.get("correct") not in ("A", "B", "C", "D"):
        return False
    if not q.get("rationale") or not q.get("source_ref"):
        return False
    return True


def is_grounded(q, source_materials):
    domain = q.get("domain")
    material = source_materials.get(domain, "")
    ref = q.get("source_ref", "").strip()
    if not ref:
        return False
    # require a meaningful chunk of the cited source string to actually appear
    # in what the model was given (allows minor whitespace/formatting drift)
    ref_snippet = ref[:40] if len(ref) > 40 else ref
    return ref_snippet.lower() in material.lower()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def is_duplicate(candidate_text, existing_texts, threshold):
    for existing in existing_texts:
        if similarity(candidate_text, existing) >= threshold:
            return True
    return False


def audit_sample(client, sample, source_materials):
    """Independent spot-check: does the model still think this Q is well-grounded
    and correctly keyed, seeing ONLY the question + the source material (not its
    own prior reasoning)?"""
    approved = []
    for q in sample:
        material = source_materials.get(q["domain"], "")[:4000]
        prompt = f"""SOURCE MATERIAL:
{material}

QUESTION: {q['question']}
OPTIONS: {json.dumps(q['options'])}
CLAIMED CORRECT ANSWER: {q['correct']}

Based ONLY on the source material, is the claimed correct answer actually
correct, and is the question answerable from this material? Reply with
exactly one word: YES or NO."""
        try:
            resp = client.messages.create(
                model=AUDIT_MODEL, max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            verdict = resp.content[0].text.strip().upper()
            approved.append(verdict.startswith("YES"))
        except Exception as e:
            print(f"[qa_dedupe] audit call failed, treating as fail-closed: {e}", file=sys.stderr)
            approved.append(False)
    return approved


def main():
    candidates = load_json(os.path.join(CANDIDATES_DIR, f"{TODAY}.json"), default=[])
    source_materials = load_json(os.path.join(CANDIDATES_DIR, f"{TODAY}_source_material.json"), default={})
    existing_questions = load_json(QUESTIONS_FILE, default=[])
    existing_texts = [q["question"] for q in existing_questions]

    if not candidates:
        print("[qa_dedupe] no candidates to process")
        return

    stage1_pass, rejected = [], []
    for q in candidates:
        if not valid_schema(q):
            rejected.append({**q, "reject_reason": "schema"})
            continue
        if not is_grounded(q, source_materials):
            rejected.append({**q, "reject_reason": "ungrounded"})
            continue
        if is_duplicate(q["question"], existing_texts, DUPLICATE_SIMILARITY_THRESHOLD):
            rejected.append({**q, "reject_reason": "duplicate_of_existing"})
            continue
        stage1_pass.append(q)

    # within-batch dedup (in case the model repeated itself across domain calls)
    final_pass, seen_texts = [], []
    for q in stage1_pass:
        if is_duplicate(q["question"], seen_texts, DUPLICATE_SIMILARITY_THRESHOLD):
            rejected.append({**q, "reject_reason": "duplicate_within_batch"})
            continue
        final_pass.append(q)
        seen_texts.append(q["question"])

    print(f"[qa_dedupe] {len(candidates)} candidates -> {len(final_pass)} passed mechanical checks "
          f"-> {len(rejected)} rejected")

    # audit spot-check on a random sample of survivors
    if final_pass and ANTHROPIC_API_KEY:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        sample_size = max(1, int(len(final_pass) * AUDIT_SAMPLE_RATE))
        sample = random.sample(final_pass, min(sample_size, len(final_pass)))
        verdicts = audit_sample(client, sample, source_materials)
        failed_ids = {id(q) for q, ok in zip(sample, verdicts) if not ok}
        if failed_ids:
            print(f"[qa_dedupe] audit sample flagged {len(failed_ids)}/{len(sample)} — "
                  f"if this rate is high, review the generation prompt/model")
        final_pass = [q for q in final_pass if id(q) not in failed_ids]
        rejected.extend([{**q, "reject_reason": "failed_audit_spotcheck"}
                          for q in sample if id(q) in failed_ids])

    # renumber, starting after the current max
    next_num = max((q.get("num", 0) for q in existing_questions), default=0) + 1
    for q in final_pass:
        q["num"] = next_num
        next_num += 1
        q.pop("source_ref", None)  # internal-only field, not needed on the live site

    os.makedirs(ACCEPTED_DIR, exist_ok=True)
    os.makedirs(REJECTED_DIR, exist_ok=True)
    with open(os.path.join(ACCEPTED_DIR, f"{TODAY}.json"), "w") as f:
        json.dump(final_pass, f, indent=2)
    with open(os.path.join(REJECTED_DIR, f"{TODAY}.json"), "w") as f:
        json.dump(rejected, f, indent=2)

    print(f"[qa_dedupe] FINAL: {len(final_pass)} accepted, {len(rejected)} rejected "
          f"(logged to data/rejected/{TODAY}.json for review)")


if __name__ == "__main__":
    main()
