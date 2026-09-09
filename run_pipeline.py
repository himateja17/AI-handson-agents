"""
Orchestrates the full daily pipeline: ingest -> verify -> generate -> qa_dedupe -> publish.
Run manually with:  python scripts/run_pipeline.py
Called by .github/workflows/daily-question-generation.yml on a schedule.
"""
import subprocess
import sys
import time

STEPS = ["ingest.py", "verify.py", "generate.py", "qa_dedupe.py", "publish.py"]


def run_step(script):
    print(f"\n{'='*60}\n  RUNNING: {script}\n{'='*60}")
    start = time.time()
    result = subprocess.run([sys.executable, script], cwd="scripts")
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"[pipeline] STEP FAILED: {script} (exit {result.returncode}, {elapsed:.1f}s)")
        sys.exit(result.returncode)
    print(f"[pipeline] {script} completed in {elapsed:.1f}s")


def main():
    for step in STEPS:
        run_step(step)
    print("\n[pipeline] All steps completed successfully.")


if __name__ == "__main__":
    main()
