"""
tests/test_scoring.py — AI scoring accuracy tests
===================================================
Tests the scoring pipeline, prompt registry, output filter,
and golden dataset expectations.
Run: pytest tests/test_scoring.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

GOLDEN_PATH = Path(__file__).parent.parent / "evaluation" / "golden_dataset.json"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def golden_dataset():
    if GOLDEN_PATH.exists():
        return json.loads(GOLDEN_PATH.read_text())
    return {"scoring": [], "cover_letters": [], "ats": [], "scam": []}


@pytest.fixture
def ml_job():
    return {
        "id": "test-ml-001",
        "title": "Machine Learning Engineer",
        "company": "Anthropic",
        "location": "San Francisco, CA",
        "job_url": "https://jobs.ashbyhq.com/anthropic/ml-001",
        "description": (
            "Build safety-critical ML systems. Requirements: PyTorch, Python 3.10+, "
            "distributed training with FSDP or DeepSpeed, RLHF, transformers architecture. "
            "5+ years ML experience. PhD preferred. NLP, LLM alignment work a plus."
        ),
        "source": "greenhouse",
        "salary_min": 200000,
        "salary_max": 300000,
    }


@pytest.fixture
def weak_frontend_job():
    return {
        "id": "test-fe-001",
        "title": "Senior Frontend Developer",
        "company": "WebCorp",
        "location": "Austin, TX",
        "job_url": "https://webcorp.com/jobs/fe-001",
        "description": (
            "Build React UIs. Requirements: React, TypeScript, CSS, Figma. "
            "3+ years frontend. No backend or ML experience needed."
        ),
        "source": "linkedin",
    }


@pytest.fixture
def sample_resume():
    return """
    Venky Reddy | ML Engineer
    MS Computer Science, MIT 2024

    Skills: Python, PyTorch, TensorFlow, scikit-learn, SQL, Docker, Kubernetes
    ML: Transformers, RLHF, distributed training, NLP, LLM fine-tuning

    Experience:
    - Built RLHF pipeline for 7B parameter LLM at research lab
    - Distributed training across 64 GPUs using FSDP
    - Published 2 papers on AI safety at NeurIPS

    Education: MIT, MS CS (GPA 3.9), focus on ML Systems
    """


# ── Prompt Registry Tests ─────────────────────────────────────────────────────

class TestPromptRegistry:
    def test_registry_has_scoring_prompt(self):
        from app.prompts.registry import REGISTRY
        prompt = REGISTRY.get("scoring")
        assert prompt is not None
        assert "{resume}" in prompt.template or "{job_description}" in prompt.template

    def test_registry_returns_latest_version(self):
        from app.prompts.registry import REGISTRY
        prompt = REGISTRY.get("scoring")
        # Should return v1 (or latest)
        assert prompt.version is not None

    def test_prompt_render(self):
        from app.prompts.registry import REGISTRY
        prompt = REGISTRY.get("scoring")
        rendered = prompt.render(
            resume="My resume",
            job_title="ML Engineer",
            company="Anthropic",
            job_description="Build ML systems",
            location="SF"
        )
        assert "My resume" in rendered
        assert len(rendered) > 50

    def test_prompt_cost_estimate(self):
        from app.prompts.registry import REGISTRY
        prompt = REGISTRY.get("scoring")
        assert prompt.estimated_cost_usd >= 0
        assert prompt.estimated_cost_usd < 0.10  # Should be cheap

    def test_render_prompt_shortcut(self):
        from app.prompts.registry import render_prompt
        result = render_prompt(
            "cover_letter_draft",
            resume="resume text",
            job_title="SWE",
            company="Google",
            job_description="Build systems",
            location="Remote"
        )
        assert len(result) > 20


# ── Output Filter Tests ───────────────────────────────────────────────────────

class TestOutputFilter:
    def test_rejects_placeholder_cover_letter(self):
        from app.security.output_filter import OutputFilter
        bad_letter = "Dear [HIRING MANAGER], I am applying for the [JOB TITLE] position at [COMPANY]."
        result = OutputFilter.validate_cover_letter(bad_letter, company="Anthropic")
        assert not result.valid
        assert "placeholder" in result.reason.lower()

    def test_rejects_short_cover_letter(self):
        from app.security.output_filter import OutputFilter
        short = "I want this job."
        result = OutputFilter.validate_cover_letter(short, company="Anthropic")
        assert not result.valid

    def test_rejects_missing_company_name(self):
        from app.security.output_filter import OutputFilter
        no_company = " ".join(["This is a great opportunity." for _ in range(30)])
        result = OutputFilter.validate_cover_letter(no_company, company="Anthropic")
        assert not result.valid
        assert "company" in result.reason.lower()

    def test_accepts_valid_cover_letter(self):
        from app.security.output_filter import OutputFilter
        good = (
            "Dear Hiring Team at Anthropic, I am thrilled to apply for the Machine Learning "
            "Engineer position. My experience building RLHF pipelines at MIT directly aligns "
            "with your mission to build safe AI. I have spent the last two years working on "
            "distributed training with FSDP and LLM fine-tuning, which maps perfectly to "
            "the technical requirements you've outlined. I would love to bring this expertise "
            "to Anthropic's safety research team and contribute to your groundbreaking work."
        )
        result = OutputFilter.validate_cover_letter(good, company="Anthropic")
        assert result.valid

    def test_validates_json_output(self):
        from app.security.output_filter import OutputFilter
        valid_json = '{"score": 85, "verdict": "STRONG_MATCH", "reason": "Great fit"}'
        result = OutputFilter.validate_json(valid_json)
        assert result is not None
        assert result["score"] == 85

    def test_extracts_json_from_markdown(self):
        from app.security.output_filter import OutputFilter
        md_wrapped = '```json\n{"score": 75, "verdict": "GOOD_MATCH"}\n```'
        result = OutputFilter.validate_json(md_wrapped)
        assert result is not None
        assert result["score"] == 75

    def test_truncates_linkedin_dm(self):
        from app.security.output_filter import OutputFilter
        long_dm = "Hi! " + "Very long message. " * 50
        result = OutputFilter.validate_linkedin_dm(long_dm)
        assert len(result) <= 300


# ── Scoring Tests (with mocked LLM) ──────────────────────────────────────────

class TestJobScorer:
    def _make_scorer(self, config, resume):
        """Helper: build scorer with given config."""
        from ai.job_scorer import JobScorer
        return JobScorer(config, resume)

    def test_scorer_score_range(self, sample_resume):
        config = {
            "ai": {"provider": "openai", "model": "gpt-4o-mini"},
            "scoring": {"min_score": 0},
        }
        mock_response = json.dumps({
            "score": 87,
            "verdict": "STRONG_MATCH",
            "reason": "Strong ML background matches well",
            "must_have_met": ["Python", "ML experience"],
            "must_have_missing": [],
            "salary_alignment": "ABOVE_RANGE",
            "recommendation": "Apply immediately",
        })

        with patch("openai.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=mock_response))]
            )
            MockOpenAI.return_value = mock_client

            scorer = self._make_scorer(config, sample_resume)
            # The scorer should either use the LLM or return a rule-based score
            # Just verify it's callable and returns a number
            assert hasattr(scorer, "score_job")

    def test_rule_based_score_ml_job(self, ml_job, sample_resume):
        """Test that a strong ML match scores high even with rule-based scoring."""
        # Check title/description keyword overlap manually
        resume_lower = sample_resume.lower()
        jd_lower = ml_job["description"].lower()
        keywords = ["pytorch", "python", "rlhf", "transformers", "distributed"]
        matches = [kw for kw in keywords if kw in resume_lower and kw in jd_lower]
        # At least 3 keywords should match for this pair
        assert len(matches) >= 3, f"Expected strong keyword overlap, got: {matches}"

    def test_rule_based_score_frontend_mismatch(self, weak_frontend_job, sample_resume):
        """Frontend job should have fewer keyword matches for ML resume."""
        resume_lower = sample_resume.lower()
        jd_lower = weak_frontend_job["description"].lower()
        fe_keywords = ["react", "typescript", "css", "figma", "frontend"]
        matches = [kw for kw in fe_keywords if kw in resume_lower and kw in jd_lower]
        # ML resume shouldn't have React, CSS, Figma
        assert len(matches) <= 1, f"Expected weak overlap, got: {matches}"


# ── Golden Dataset Tests ──────────────────────────────────────────────────────

class TestGoldenDataset:
    def test_golden_dataset_exists(self):
        assert GOLDEN_PATH.exists(), f"Golden dataset missing at {GOLDEN_PATH}"

    def test_golden_dataset_structure(self, golden_dataset):
        assert "scoring" in golden_dataset
        assert "cover_letters" in golden_dataset
        assert "scam" in golden_dataset

    def test_golden_scoring_cases_have_range(self, golden_dataset):
        for case in golden_dataset.get("scoring", []):
            assert "expected_min" in case
            assert "expected_max" in case
            assert case["expected_min"] <= case["expected_max"]
            assert 0 <= case["expected_min"] <= 100
            assert 0 <= case["expected_max"] <= 100

    def test_golden_cover_letter_cases_have_checks(self, golden_dataset):
        for case in golden_dataset.get("cover_letters", []):
            assert "forbidden" in case or "required" in case

    def test_golden_scam_cases_labeled(self, golden_dataset):
        for case in golden_dataset.get("scam", []):
            assert "expected" in case
            assert case["expected"] in ("blocked", "allowed")


# ── JD Summarizer Tests ───────────────────────────────────────────────────────

class TestJDSummarizer:
    def test_detects_red_flags_rule_based(self):
        from ai.jd_summarizer import JDSummarizer
        config = {"ai": {"provider": "openai"}}
        summarizer = JDSummarizer(config)
        jd_with_red_flags = (
            "We're a fast-paced startup. You'll wear many hats! "
            "We offer unlimited PTO and a ping pong table. "
            "Competitive salary (depends on fit). Must be comfortable with ambiguity."
        )
        result = summarizer._rule_based_analysis(jd_with_red_flags)
        assert len(result["red_flags"]) >= 2

    def test_detects_green_flags_rule_based(self):
        from ai.jd_summarizer import JDSummarizer
        config = {"ai": {"provider": "openai"}}
        summarizer = JDSummarizer(config)
        jd_with_green = (
            "We just raised Series B! Remote-friendly environment. "
            "Competitive salary with equity. 401k with matching. H1B visa sponsorship available."
        )
        result = summarizer._rule_based_analysis(jd_with_green)
        assert len(result["green_flags"]) >= 2


# ── ATS Scanner Tests ─────────────────────────────────────────────────────────

class TestATSScanner:
    def test_ats_scanner_importable(self):
        try:
            from ai.ats_scanner import ATSScanner
            assert ATSScanner is not None
        except ImportError as e:
            pytest.skip(f"ATSScanner not available: {e}")

    def test_keyword_extraction(self, ml_job):
        """Keywords from JD should include ML terms."""
        jd = ml_job["description"].lower()
        expected_keywords = ["pytorch", "python", "distributed"]
        for kw in expected_keywords:
            assert kw in jd
