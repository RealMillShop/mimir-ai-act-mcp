"""Offline tests — no Anthropic API calls. Run in CI.

Verifies catalog structure, schema validity, golden-set coverage, and that
``server.py`` and ``http_main.py`` import without error.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
SCHEMAS_DIR = REPO_ROOT / "schemas"
TESTS_DIR = REPO_ROOT / "tests"

CATALOG = json.loads((KNOWLEDGE_DIR / "violations_catalog.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((SCHEMAS_DIR / "compliance_report.json").read_text(encoding="utf-8"))
EXPECTED_IDS = {f"V{i:03d}" for i in range(1, 13)}
DEPLOYMENT_TYPES = {
    "voice_agent",
    "chatbot",
    "generated_content",
    "deepfake",
    "biometric_system",
    "other",
}


def test_catalog_has_12_violations():
    ids = {v["id"] for v in CATALOG["violations"]}
    assert ids == EXPECTED_IDS, f"Expected {EXPECTED_IDS}, got {ids}"


def test_catalog_entries_have_required_fields():
    required = {
        "id",
        "article",
        "title",
        "severity",
        "in_force_since",
        "description",
        "detection_hints",
        "compliant_example",
        "non_compliant_example",
        "suggested_fix_template",
        "penalty_range_eur",
    }
    for v in CATALOG["violations"]:
        missing = required - set(v.keys())
        assert not missing, f"{v['id']}: missing fields {missing}"


def test_catalog_severity_values():
    allowed = {"high", "medium", "low"}
    for v in CATALOG["violations"]:
        assert v["severity"] in allowed, f"{v['id']}: invalid severity {v['severity']!r}"


def test_catalog_multilingual_hints():
    """Every entry must have at least EN, LV, RU detection_hints."""
    for v in CATALOG["violations"]:
        hints = v["detection_hints"]
        assert isinstance(hints, dict), f"{v['id']}: detection_hints must be a dict"
        for lang in ("en", "lv", "ru"):
            assert lang in hints, f"{v['id']}: missing '{lang}' detection_hints"
            assert hints[lang], f"{v['id']}: '{lang}' detection_hints must be non-empty"


def test_catalog_in_force_dates():
    """Art. 5 → 2025-02-02, Art. 50 → 2026-08-02, Art. 53 → 2025-08-02."""
    for v in CATALOG["violations"]:
        article = v["article"]
        when = v["in_force_since"]
        if article.startswith("Article 5("):
            assert when == "2025-02-02", f"{v['id']}: Art. 5 should be 2025-02-02, got {when}"
        elif article.startswith("Article 50("):
            assert when == "2026-08-02", f"{v['id']}: Art. 50 should be 2026-08-02, got {when}"
        elif article.startswith("Article 53"):
            assert when == "2025-08-02", f"{v['id']}: Art. 53 should be 2025-08-02, got {when}"


def test_schema_is_valid_draft7():
    from jsonschema import Draft7Validator

    Draft7Validator.check_schema(SCHEMA)


def test_schema_required_fields():
    expected = {
        "compliance_status",
        "risk_score",
        "violations",
        "general_recommendations",
        "disclaimer",
        "audited_at",
        "audit_version",
    }
    assert set(SCHEMA["required"]) == expected


def test_schema_compliance_status_enum():
    assert set(SCHEMA["properties"]["compliance_status"]["enum"]) == {
        "compliant",
        "needs_review",
        "non_compliant",
    }


def test_golden_set_loads_and_covers_everything():
    golden = []
    for line in (TESTS_DIR / "golden_set.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        golden.append(json.loads(line))

    assert len(golden) >= 15, f"Golden set must have ≥15 examples, has {len(golden)}"

    deployment_types = {ex["deployment_type"] for ex in golden}
    assert deployment_types == DEPLOYMENT_TYPES, (
        f"Missing deployment_type coverage: have {deployment_types}, want {DEPLOYMENT_TYPES}"
    )

    languages = {ex.get("language", "en") for ex in golden}
    assert "lv" in languages, "Need at least one Latvian example"
    assert "ru" in languages, "Need at least one Russian example"

    statuses = {ex["expected_status"] for ex in golden}
    assert "compliant" in statuses, "Need at least one compliant example for precision testing"
    assert "non_compliant" in statuses, "Need at least one non_compliant example"

    flagged_ids = {vid for ex in golden for vid in ex.get("expected_violation_ids", [])}
    missing = EXPECTED_IDS - flagged_ids
    assert not missing, f"Golden set must exercise every catalog violation, missing: {missing}"


def test_golden_set_ids_match_catalog():
    """Every expected_violation_id in the golden set must exist in the catalog."""
    for line in (TESTS_DIR / "golden_set.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ex = json.loads(line)
        for vid in ex.get("expected_violation_ids", []):
            assert vid in EXPECTED_IDS, f"{ex['id']}: unknown violation_id {vid}"


def test_server_module_imports():
    """server.py must import cleanly (constructs SYSTEM_BLOCKS, loads catalog, etc.).

    Skipped if mcp/anthropic deps are not installed (CI without them).
    """
    pytest.importorskip("mcp")
    pytest.importorskip("anthropic")
    import server  # noqa: F401

    assert server.AUDIT_VERSION == "1.0"
    assert len(server.SYSTEM_BLOCKS) == 1
    assert server.SYSTEM_BLOCKS[0]["cache_control"] == {"type": "ephemeral"}
    assert server.SUBMIT_REPORT_TOOL["input_schema"]["title"] == "ComplianceReport"


def test_http_main_module_imports():
    """http_main.py must import cleanly."""
    pytest.importorskip("fastapi")
    pytest.importorskip("mcp")
    pytest.importorskip("anthropic")
    import http_main  # noqa: F401

    assert http_main.app.title == "MIMIR EU AI Act Compliance Checker"
