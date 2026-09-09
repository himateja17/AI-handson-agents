"""
Shared configuration for the AIF-C01 daily question pipeline.
Edit SOURCES if AWS reorganizes their docs; edit DOMAIN_WEIGHTS only if
AWS publishes a new exam guide with different weightings.
"""
import os

# ---- Anthropic API ----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GENERATION_MODEL = "claude-haiku-4-5-20251001"   # cheapest tier, plenty for this task
AUDIT_MODEL = "claude-haiku-4-5-20251001"        # second-pass spot-check model

# ---- Canonical, high-trust sources (checked every run, no corroboration needed) ----
CANONICAL_SOURCES = {
    "exam_guide": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01.html",
    "in_scope_services": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/aif-01-in-scope-services.html",
    "out_of_scope_services": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/aif-01-out-of-scope-services.html",
    "domain1": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01-domain1.html",
    "domain2": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01-domain2.html",
    "domain3": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01-domain3.html",
    "domain4": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01-domain4.html",
    "domain5": "https://docs.aws.amazon.com/aws-certification/latest/ai-practitioner-01/ai-practitioner-01-domain5.html",
}

# ---- Lower-trust sources: only promoted to "verified" if corroborated
# (their linked page is fetched and cross-checked against CANONICAL_SOURCES) ----
RSS_SOURCES = {
    "aws_whats_new": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
    "aws_ml_blog": "https://aws.amazon.com/blogs/machine-learning/feed/",
}

# Keywords used to filter RSS items down to ones plausibly relevant to AIF-C01
RELEVANCE_KEYWORDS = [
    "bedrock", "sagemaker", "ai practitioner", "generative ai", "foundation model",
    "guardrail", "agentcore", "knowledge base", "rag", "responsible ai",
    "comprehend", "rekognition", "textract", "transcribe", "polly", "lex",
    "personalize", "kendra", "amazon q", "amazon quick", "macie", "inspector",
    "cloudtrail", "iam", "clarify",
]

# ---- Domain weighting (must match the current official exam guide) ----
DOMAIN_WEIGHTS = {
    "DOMAIN 1 — Fundamentals of AI and ML": 0.20,
    "DOMAIN 2 — Fundamentals of Generative AI": 0.24,
    "DOMAIN 3 — Applications of Foundation Models": 0.28,
    "DOMAIN 4 — Guidelines for Responsible AI": 0.14,
    "DOMAIN 5 — Security, Compliance, and Governance for AI Solutions": 0.14,
}

DAILY_QUESTION_TARGET = 100

# ---- Paths ----
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, "site")
QUESTIONS_FILE = os.path.join(SITE_DIR, "questions.json")
SNAPSHOT_DIR = os.path.join(ROOT, "data", "snapshots")
VERIFIED_DIR = os.path.join(ROOT, "data", "verified_facts")
ACCEPTED_DIR = os.path.join(ROOT, "data", "accepted")

DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # reject candidate Qs above this similarity to an existing one
AUDIT_SAMPLE_RATE = 0.15               # fraction of accepted batch re-checked by a second LLM call
