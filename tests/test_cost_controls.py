"""Tests for cost controls: budget circuit breaker and cache threshold validation.

These tests verify the cost safety mechanisms without making any API calls.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from productteam.errors import BudgetExceededError
from productteam.supervisor import (
    CostTracker,
    _estimate_tokens,
    validate_cache_thresholds,
    _CACHE_MIN_TOKENS,
)


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    """Tests for the budget circuit breaker."""

    def test_tracks_tokens(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        tracker.add({"input_tokens": 1000, "output_tokens": 200})
        assert tracker.total_input == 1000
        assert tracker.total_output == 200

    def test_accumulates_across_calls(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        tracker.add({"input_tokens": 1000, "output_tokens": 100})
        tracker.add({"input_tokens": 2000, "output_tokens": 300})
        assert tracker.total_input == 3000
        assert tracker.total_output == 400

    def test_tracks_cache_tokens(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        tracker.add({
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 5000,
            "cache_read_input_tokens": 4000,
        })
        assert tracker.total_cache_creation == 5000
        assert tracker.total_cache_read == 4000

    def test_est_cost_haiku(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        # 1M input at $0.80/M + 100K output at $4.00/M = $0.80 + $0.40 = $1.20
        tracker.add({"input_tokens": 1_000_000, "output_tokens": 100_000})
        assert tracker.est_cost == pytest.approx(1.20, abs=0.01)

    def test_est_cost_includes_cache_tokens(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        # With caching: input_tokens is small, cache_read is large
        # 10K input at $0.80/M = $0.008
        # 100K cache_create at $0.80*1.25/M = $0.10
        # 1M cache_read at $0.80*0.1/M = $0.08
        # 50K output at $4.00/M = $0.20
        # Total = $0.388
        tracker.add({
            "input_tokens": 10_000,
            "output_tokens": 50_000,
            "cache_creation_input_tokens": 100_000,
            "cache_read_input_tokens": 1_000_000,
        })
        assert tracker.est_cost == pytest.approx(0.388, abs=0.01)

    def test_est_cost_sonnet(self):
        tracker = CostTracker(model_id="claude-sonnet-4-6", budget_usd=10.0)
        # 1M input at $3.00/M + 100K output at $15.00/M = $3.00 + $1.50 = $4.50
        tracker.add({"input_tokens": 1_000_000, "output_tokens": 100_000})
        assert tracker.est_cost == pytest.approx(4.50, abs=0.01)

    def test_est_cost_unknown_model(self):
        tracker = CostTracker(model_id="some-unknown-model", budget_usd=10.0)
        tracker.add({"input_tokens": 1_000_000, "output_tokens": 100_000})
        assert tracker.est_cost is None

    def test_raises_when_budget_exceeded(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=0.50)
        # 1M input = $0.80 which exceeds $0.50 budget
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.add({"input_tokens": 1_000_000, "output_tokens": 0}, stage="build")
        assert exc_info.value.spent > 0.50
        assert exc_info.value.budget == 0.50
        assert exc_info.value.stage == "build"

    def test_does_not_raise_within_budget(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=5.0)
        # 100K input = $0.08, well within $5.00
        tracker.add({"input_tokens": 100_000, "output_tokens": 10_000})
        # No exception raised

    def test_raises_on_accumulated_cost(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=1.0)
        # Each call is $0.08 input + $0.04 output = $0.12
        for i in range(8):
            tracker.add({"input_tokens": 100_000, "output_tokens": 10_000})
        # After 8 calls: $0.96, still under $1.00
        # 9th call should push over
        with pytest.raises(BudgetExceededError):
            tracker.add({"input_tokens": 100_000, "output_tokens": 10_000})

    def test_unknown_model_never_raises(self):
        """Unknown models can't estimate cost, so budget is not enforced."""
        tracker = CostTracker(model_id="unknown-model", budget_usd=0.01)
        # Even massive token usage doesn't raise because cost is None
        tracker.add({"input_tokens": 100_000_000, "output_tokens": 10_000_000})

    def test_handles_missing_usage_keys(self):
        tracker = CostTracker(model_id="claude-haiku-4-5-20251001", budget_usd=10.0)
        tracker.add({})  # No keys at all
        assert tracker.total_input == 0
        assert tracker.total_output == 0

    def test_budget_exceeded_error_message(self):
        err = BudgetExceededError(spent=2.5, budget=1.0, stage="evaluate:sprint-003")
        assert "$2.5" in str(err)
        assert "$1.00" in str(err)
        assert "evaluate:sprint-003" in str(err)


# ---------------------------------------------------------------------------
# Cache threshold validation tests
# ---------------------------------------------------------------------------


class TestCacheThresholdValidation:
    """Tests for the cache threshold pre-flight check."""

    def test_warns_on_small_skill(self, tmp_path):
        """Skill below Haiku's 4096-token minimum should produce a warning."""
        skill_dir = tmp_path / "builder"
        skill_dir.mkdir()
        # ~500 tokens — well below 4096
        (skill_dir / "SKILL.md").write_text("Short prompt. " * 100, encoding="utf-8")

        warnings = validate_cache_thresholds(
            model_id="claude-haiku-4-5-20251001",
            skills_dir=tmp_path,
            skill_names=("builder",),
        )
        assert len(warnings) == 1
        assert "4,096" in warnings[0]
        assert "builder" in warnings[0]

    def test_no_warning_on_large_skill(self, tmp_path):
        """Skill above threshold should produce no warning."""
        skill_dir = tmp_path / "builder"
        skill_dir.mkdir()
        # ~5000 tokens — above 4096
        (skill_dir / "SKILL.md").write_text("Detailed instructions. " * 2000, encoding="utf-8")

        warnings = validate_cache_thresholds(
            model_id="claude-haiku-4-5-20251001",
            skills_dir=tmp_path,
            skill_names=("builder",),
        )
        assert len(warnings) == 0

    def test_sonnet_lower_threshold(self, tmp_path):
        """Sonnet has a 1024-token threshold — same skill passes for Sonnet but not Haiku."""
        skill_dir = tmp_path / "builder"
        skill_dir.mkdir()
        # ~2000 tokens — above 1024 but below 4096
        (skill_dir / "SKILL.md").write_text("Medium prompt. " * 500, encoding="utf-8")

        # Should pass for Sonnet
        warnings_sonnet = validate_cache_thresholds(
            model_id="claude-sonnet-4-6",
            skills_dir=tmp_path,
            skill_names=("builder",),
        )
        assert len(warnings_sonnet) == 0

        # Should warn for Haiku
        warnings_haiku = validate_cache_thresholds(
            model_id="claude-haiku-4-5-20251001",
            skills_dir=tmp_path,
            skill_names=("builder",),
        )
        assert len(warnings_haiku) == 1

    def test_unknown_model_skips_validation(self, tmp_path):
        """Unknown models have no threshold — validation always passes."""
        skill_dir = tmp_path / "builder"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Tiny.", encoding="utf-8")

        warnings = validate_cache_thresholds(
            model_id="unknown-model",
            skills_dir=tmp_path,
            skill_names=("builder",),
        )
        assert len(warnings) == 0

    def test_missing_skill_skipped(self, tmp_path):
        """Missing skill files are silently skipped (not an error)."""
        warnings = validate_cache_thresholds(
            model_id="claude-haiku-4-5-20251001",
            skills_dir=tmp_path,
            skill_names=("nonexistent",),
        )
        assert len(warnings) == 0

    def test_multiple_skills_checked(self, tmp_path):
        """All listed skills are checked."""
        for name in ("builder", "evaluator", "planner"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text("Tiny. " * 10, encoding="utf-8")

        warnings = validate_cache_thresholds(
            model_id="claude-haiku-4-5-20251001",
            skills_dir=tmp_path,
            skill_names=("builder", "evaluator", "planner"),
        )
        assert len(warnings) == 3  # All three are too small


class TestEstimateTokens:
    """Tests for the rough token estimator."""

    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_short_text(self):
        # 20 chars / 4 = 5 tokens
        assert _estimate_tokens("12345678901234567890") == 5

    def test_reasonable_estimate(self):
        # A 16K char document should be roughly 4000 tokens
        text = "a" * 16000
        est = _estimate_tokens(text)
        assert 3500 < est < 4500


class TestProductionSkillSizes:
    """Verify that the actual shipped skill files are above the cache threshold.

    This test uses the real skill files in the repo, not test fixtures.
    It ensures we never regress below the minimum.
    """

    def test_builder_skill_above_haiku_threshold(self):
        skill_path = Path(__file__).parent.parent / "skills" / "builder" / "SKILL.md"
        if not skill_path.exists():
            pytest.skip("Builder skill not found (not in repo root)")
        content = skill_path.read_text(encoding="utf-8")
        est = _estimate_tokens(content)
        min_threshold = _CACHE_MIN_TOKENS["claude-haiku-4-5-20251001"]
        assert est >= min_threshold, (
            f"Builder skill is ~{est} tokens, below Haiku's {min_threshold} minimum. "
            f"Prompt caching will be silently disabled."
        )

    def test_evaluator_skill_above_haiku_threshold(self):
        skill_path = Path(__file__).parent.parent / "skills" / "evaluator" / "SKILL.md"
        if not skill_path.exists():
            pytest.skip("Evaluator skill not found (not in repo root)")
        content = skill_path.read_text(encoding="utf-8")
        est = _estimate_tokens(content)
        min_threshold = _CACHE_MIN_TOKENS["claude-haiku-4-5-20251001"]
        assert est >= min_threshold, (
            f"Evaluator skill is ~{est} tokens, below Haiku's {min_threshold} minimum. "
            f"Prompt caching will be silently disabled."
        )
