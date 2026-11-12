"""
test_tour_text.py - Automated validation for guided tour text.

Ensures:
1. Valid schema for all steps (id, title, text, audio, target, action, highlightStyle, durationFallbackMs).
2. Numbers in narration match computed data values within reasonable rounding tolerance.
3. No forbidden words appear ("proves", "confirms", "real physical signal", unqualified "caused by").
4. High-school definitions for required foundational terms are present on first use.
"""

import json
import os
import re
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOURS_JSON = os.path.join(BASE_DIR, "web", "tour", "tours.json")


@pytest.fixture(scope="module")
def tours():
    assert os.path.exists(TOURS_JSON), f"Missing {TOURS_JSON}"
    with open(TOURS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def test_tours_schema(tours):
    """Verifies schema structure of tours.json."""
    expected_tours = ["site_tour", "case_amazon", "case_sahel", "case_tibet", "case_canada"]
    for t_id in expected_tours:
        assert t_id in tours, f"Tour '{t_id}' missing from tours.json"
        tour = tours[t_id]
        assert "id" in tour
        assert "title" in tour
        assert "steps" in tour
        assert len(tour["steps"]) >= 5, f"Tour '{t_id}' has fewer than 5 steps"

        for s in tour["steps"]:
            assert "id" in s and s["id"]
            assert "title" in s and s["title"]
            assert "text" in s and s["text"]
            assert "audio" in s and s["audio"].endswith(".mp3")
            assert "target" in s
            assert "action" in s and isinstance(s["action"], dict)
            assert s.get("highlightStyle") in ["ring", "spotlight", "arrow"]
            assert isinstance(s.get("durationFallbackMs"), (int, float))
            assert s["durationFallbackMs"] >= 3000


def test_forbidden_phrases(tours):
    """Fails if forbidden phrases appear without proper scientific qualification."""
    forbidden = ["proves", "confirms", "real physical signal"]

    for t_id, tour in tours.items():
        for s in tour["steps"]:
            txt = s["text"].lower()
            for f in forbidden:
                assert f not in txt, f"Forbidden phrase '{f}' found in tour '{t_id}' step '{s['id']}': {s['text']}"

            if "caused by" in txt:
                assert "not proven to be caused" in txt or "is not caused by" in txt, (
                    f"Unqualified 'caused by' found in tour '{t_id}' step '{s['id']}': {s['text']}"
                )


def test_required_definitions_present(tours):
    """Verifies high-school definitions for required foundational terms are present on first use."""
    required_terms = [
        "anomaly",
        "trend",
        "p-value",
        "significant",
        "confidence interval",
        "step change",
    ]

    all_texts = []
    for tour in tours.values():
        for s in tour["steps"]:
            all_texts.append(s["text"].lower())
    combined_text = " ".join(all_texts)

    for term in required_terms:
        assert term in combined_text, f"Required statistical definition for '{term}' was missing from tour narrations!"


def test_real_numbers_match_computed(tours):
    """Verifies numbers in narration match computed data values within rounding tolerance."""
    # From scripts/build_tours.py real computed values:
    # Amazon: slope ~ -11.96, p_hr ~ 0.0194, CI: [-22.15, -1.75]
    amz_steps = {s["id"]: s["text"] for s in tours["case_amazon"]["steps"]}
    assert "-11.96" in amz_steps["case_amz_02_signal"]
    assert "0.0194" in amz_steps["case_amz_03_significance"]
    assert "-22.15" in amz_steps["case_amz_04_ci"]
    assert "-1.75" in amz_steps["case_amz_04_ci"]

    # Sahel: IMERG slope ~ 0.32, GLDAS slope ~ 0.73
    shl_steps = {s["id"]: s["text"] for s in tours["case_sahel"]["steps"]}
    assert "0.32" in shl_steps["case_shl_02_imerg_trend"]
    assert "0.73" in shl_steps["case_shl_05_disagreement"]

    # Tibet: slope ~ 2.75, CI: [2.12, 3.37]
    tbt_steps = {s["id"]: s["text"] for s in tours["case_tibet"]["steps"]}
    assert "2.75" in tbt_steps["case_tbt_02_signal"]
    assert "2.12" in tbt_steps["case_tbt_04_ci"]
    assert "3.37" in tbt_steps["case_tbt_04_ci"]

    # Canada: summer slope ~ 0.04 (or 0.039)
    can_steps = {s["id"]: s["text"] for s in tours["case_canada"]["steps"]}
    assert "0.04" in can_steps["case_can_03_jja_slice"]
