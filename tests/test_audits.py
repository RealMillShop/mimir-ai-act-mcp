"""Live golden-set eval — makes real Anthropic API calls. SLOW + costs money.

Skipped by default. To run:

    RUN_AUDIT_EVAL=1 pytest tests/test_audits.py -v -s

Optional env knobs:
    MIMIR_EVAL_RUNS=3                    # runs per example (default 3)
    MIMIR_AUDIT_MODEL=claude-sonnet-4-6  # override default Haiku 4.5

Thresholds (from BRIEF.md):
    recall      ≥ 0.85
    precision   ≥ 0.75
    consistency ≥ 0.80   (mean pairwise Jaccard across runs)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from statistics import mean

import pytest

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TESTS_DIR = REPO_ROOT / "tests"
GOLDEN_SET_PATH = TESTS_DIR / "golden_set.jsonl"
SCHEMA_PATH = REPO_ROOT / "schemas" / "compliance_report.json"

RUNS_PER_EXAMPLE = int(os.getenv("MIMIR_EVAL_RUNS", "3"))
RECALL_THRESHOLD = 0.85
PRECISION_THRESHOLD = 0.75
CONSISTENCY_THRESHOLD = 0.80

EVAL_ENABLED = os.getenv("RUN_AUDIT_EVAL") == "1"
SKIP_REASON = "Set RUN_AUDIT_EVAL=1 to run live API eval (slow + paid)"


def _load_golden_set() -> list[dict]:
    examples: list[dict] = []
    for line in GOLDEN_SET_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        examples.append(json.loads(line))
    return examples


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _recall(expected: set, actual: set) -> float:
    if not expected:
        return 1.0 if not actual else 0.0
    return len(expected & actual) / len(expected)


def _precision(expected: set, actual: set) -> float:
    if not actual:
        return 1.0 if not expected else 0.0
    return len(expected & actual) / len(actual)


@pytest.mark.skipif(not EVAL_ENABLED, reason=SKIP_REASON)
def test_golden_set_eval():
    pytest.importorskip("anthropic")
    pytest.importorskip("jsonschema")

    from jsonschema import Draft7Validator

    from server import audit_ai_deployment

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    examples = _load_golden_set()

    per_example_recall: list[float] = []
    per_example_precision: list[float] = []
    per_example_consistency: list[float] = []
    cache_hits = 0

    print(f"\n=== Golden-set eval — {len(examples)} examples × {RUNS_PER_EXAMPLE} runs ===\n")

    for ex in examples:
        expected = set(ex.get("expected_violation_ids", []))
        runs: list[set] = []

        for run_idx in range(RUNS_PER_EXAMPLE):
            report = audit_ai_deployment(ex["text"], ex["deployment_type"])
            errors = list(validator.iter_errors(report))
            assert not errors, (
                f"{ex['id']} run {run_idx + 1}: schema validation failed: "
                f"{[e.message for e in errors]}"
            )
            actual = {v["violation_id"] for v in report["violations"]}
            runs.append(actual)

        ex_recall = mean(_recall(expected, r) for r in runs)
        ex_precision = mean(_precision(expected, r) for r in runs)
        pairs = [(runs[i], runs[j]) for i in range(len(runs)) for j in range(i + 1, len(runs))]
        ex_consistency = mean(_jaccard(a, b) for a, b in pairs) if pairs else 1.0

        per_example_recall.append(ex_recall)
        per_example_precision.append(ex_precision)
        per_example_consistency.append(ex_consistency)

        print(
            f"  {ex['id']:6s} [{ex.get('language', 'en')}] {ex['deployment_type']:18s} "
            f"expected={sorted(expected) or '∅':<20} "
            f"R={ex_recall:.2f} P={ex_precision:.2f} C={ex_consistency:.2f}"
        )

    overall_recall = mean(per_example_recall)
    overall_precision = mean(per_example_precision)
    overall_consistency = mean(per_example_consistency)

    print(
        f"\n=== Aggregate ({len(examples)} examples) ===\n"
        f"  recall      = {overall_recall:.3f}   (threshold ≥{RECALL_THRESHOLD})\n"
        f"  precision   = {overall_precision:.3f}   (threshold ≥{PRECISION_THRESHOLD})\n"
        f"  consistency = {overall_consistency:.3f}   (threshold ≥{CONSISTENCY_THRESHOLD})\n"
    )

    assert overall_recall >= RECALL_THRESHOLD, (
        f"Recall {overall_recall:.3f} below threshold {RECALL_THRESHOLD}"
    )
    assert overall_precision >= PRECISION_THRESHOLD, (
        f"Precision {overall_precision:.3f} below threshold {PRECISION_THRESHOLD}"
    )
    assert overall_consistency >= CONSISTENCY_THRESHOLD, (
        f"Consistency {overall_consistency:.3f} below threshold {CONSISTENCY_THRESHOLD}"
    )


@pytest.mark.skipif(not EVAL_ENABLED, reason=SKIP_REASON)
def test_prompt_cache_hits_on_second_audit():
    """Second audit within the cache TTL must produce a cache read >0."""
    pytest.importorskip("anthropic")

    import server

    # Bypass the public wrapper to access the raw response and its usage stats.
    client = server.get_client()

    def _raw_audit(text: str, deployment_type: str):
        return client.messages.create(
            model=server.MODEL,
            max_tokens=2000,
            system=server.SYSTEM_BLOCKS,
            tools=[server.SUBMIT_REPORT_TOOL],
            tool_choice={"type": "tool", "name": "submit_compliance_report"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Audit the following `{deployment_type}` for EU AI Act compliance. "
                        f"Call submit_compliance_report.\n\n---\n{text}\n---"
                    ),
                }
            ],
        )

    sample = "Hello, this is Anna from BrightHouse Energy. How are you today?"
    r1 = _raw_audit(sample, "voice_agent")
    r2 = _raw_audit(sample, "voice_agent")

    cache_read_2 = getattr(r2.usage, "cache_read_input_tokens", 0)
    print(
        f"\nFirst call:  cache_creation_input_tokens={getattr(r1.usage, 'cache_creation_input_tokens', 0)} "
        f"cache_read_input_tokens={getattr(r1.usage, 'cache_read_input_tokens', 0)}"
        f"\nSecond call: cache_creation_input_tokens={getattr(r2.usage, 'cache_creation_input_tokens', 0)} "
        f"cache_read_input_tokens={cache_read_2}"
    )

    assert cache_read_2 > 0, (
        f"Expected prompt cache hit on second audit, got cache_read_input_tokens={cache_read_2}. "
        "Either cache_control isn't applied or the TTL expired."
    )
