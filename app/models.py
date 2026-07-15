"""
app/models.py — Pydantic data models
======================================
Single source of truth for all data shapes in the pipeline.
Every scraper, AI module, and DB layer speaks this language.

These replace raw dicts — structured, validated, serializable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, computed_field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class JobSource(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    GOOGLE = "google"
    ZIP_RECRUITER = "zip_recruiter"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    NEW_GRAD = "new_grad"
    DISCORD = "discord"
    RSS = "rss"
    HN = "hn_who_is_hiring"
    UNKNOWN = "unknown"


class InterviewStage(str, Enum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    PHONE_SCREEN = "phone_screen"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    ONSITE = "onsite"
    OFFER = "offer"
    NEGOTIATING = "negotiating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class HiringSignal(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    UNKNOWN = "UNKNOWN"


class FreezeStatus(str, Enum):
    FROZEN = "FROZEN"
    LIKELY_FROZEN = "LIKELY_FROZEN"
    UNCERTAIN = "UNCERTAIN"
    HIRING = "HIRING"
    SURGE = "SURGE"


class VisaStatus(str, Enum):
    SPONSORS = "SPONSORS"
    SILENT = "SILENT"
    NO_SPONSOR = "NO_SPONSOR"
    UNCERTAIN = "UNCERTAIN"
    SILENT_LIKELY_OK = "SILENT_LIKELY_OK"


class ATSVerdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


# ── Core Models ───────────────────────────────────────────────────────────────

class Job(BaseModel):
    """Core job posting model. Produced by scrapers, enriched by agents."""

    # Identity
    id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint: Optional[str] = None          # MD5 dedup hash

    # Core fields
    title: str
    company: str
    location: str = ""
    job_url: str = ""
    description: str = ""
    source: str = JobSource.UNKNOWN.value

    # Dates
    date_posted: Optional[str] = None
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Compensation
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_range: Optional[str] = None
    salary_currency: str = "USD"

    # Flags
    is_remote: bool = False
    is_new_grad: bool = False

    # AI enrichment — scoring
    score: Optional[float] = Field(None, ge=0, le=100)
    score_reason: Optional[str] = None
    personalized_score: Optional[float] = Field(None, ge=0, le=100)
    personal_score_adjustment: Optional[float] = None

    # AI enrichment — cover letter
    cover_letter: Optional[str] = None
    cover_letter_review: Optional[str] = None
    email_draft: Optional[str] = None

    # AI enrichment — company
    company_research: Optional[str] = None
    contact_name: Optional[str] = None
    contact_linkedin: Optional[str] = None
    culture_score: Optional[float] = Field(None, ge=0, le=10)
    culture_summary: Optional[str] = None

    # AI enrichment — hiring intelligence
    hiring_signal: Optional[str] = HiringSignal.UNKNOWN.value
    hiring_signal_reason: Optional[str] = None
    freeze_status: Optional[str] = FreezeStatus.UNCERTAIN.value
    freeze_reason: Optional[str] = None

    # AI enrichment — resume matching
    ats_score: Optional[float] = Field(None, ge=0, le=100)
    ats_verdict: Optional[str] = None
    ats_report: Optional[str] = None
    tailored_resume: Optional[str] = None

    # AI enrichment — outreach
    outreach_linkedin_dm: Optional[str] = None
    outreach_cold_email: Optional[str] = None

    # AI enrichment — visa
    visa_status: Optional[str] = None
    visa_reason: Optional[str] = None

    # AI enrichment — JD summary
    jd_summary: Optional[Dict[str, Any]] = None

    # AI enrichment — salary
    salary_estimate: Optional[str] = None

    # Interview pipeline
    interview_stage: str = InterviewStage.NOT_APPLIED.value
    interview_stage_updated_at: Optional[str] = None
    interview_dates: Optional[str] = None
    response_received: bool = False
    response_date: Optional[str] = None
    rejection_reason: Optional[str] = None
    thankyou_sent: bool = False

    # Tracking
    notified: bool = False
    applied_at: Optional[str] = None
    filter_reason: Optional[str] = None

    model_config = {"extra": "allow"}  # Allow extra fields from legacy dicts

    @computed_field
    @property
    def display_score(self) -> str:
        s = self.personalized_score or self.score
        return f"{s:.0f}" if s is not None else "N/A"

    @computed_field
    @property
    def is_high_match(self) -> bool:
        return (self.score or 0) >= 80

    @field_validator("job_url", mode="before")
    @classmethod
    def clean_url(cls, v: Any) -> str:
        return str(v) if v else ""

    def to_db_dict(self) -> Dict[str, Any]:
        """Flatten to dict for SQLite storage."""
        return self.model_dump(mode="json", exclude_none=False)

    @classmethod
    def from_db_dict(cls, d: Dict[str, Any]) -> "Job":
        return cls.model_validate(d)

    @classmethod
    def from_legacy_dict(cls, d: Dict[str, Any]) -> "Job":
        """Convert old raw dict format to typed Job."""
        return cls.model_validate({
            "title": d.get("title", ""),
            "company": d.get("company", ""),
            "location": d.get("location", ""),
            "job_url": d.get("job_url") or d.get("url", ""),
            "description": d.get("description", ""),
            "source": d.get("source", "unknown"),
            **{k: v for k, v in d.items()
               if k not in ("title", "company", "location", "job_url", "url", "description", "source")},
        })


class PipelineRun(BaseModel):
    """Tracks a single execution of the job pipeline."""
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    run_number: int = 1
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None

    # Counts
    scraped: int = 0
    filtered_repost: int = 0
    filtered_visa: int = 0
    filtered_freeze: int = 0
    new_jobs: int = 0
    scored: int = 0
    cover_letters_generated: int = 0
    alerts_sent: int = 0
    auto_applied: int = 0

    # Cost
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Status
    status: Literal["running", "completed", "failed"] = "running"
    error: Optional[str] = None

    def complete(self):
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.elapsed_seconds = (
            datetime.fromisoformat(self.finished_at) -
            datetime.fromisoformat(self.started_at)
        ).total_seconds()
        self.status = "completed"

    def finish(self):
        """Alias for complete() — mark the run as finished."""
        self.complete()


class ApplicationEvent(BaseModel):
    """Tracks a stage change in the interview pipeline."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    company: str
    title: str
    from_stage: str
    to_stage: str
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "manual"  # manual | gmail_parser | auto
    notes: Optional[str] = None


class ScoringResult(BaseModel):
    """Output from the JobScorer agent."""
    job_id: str = ""
    score: float = Field(..., ge=0, le=100)
    verdict: str = ""
    reason: str = ""
    keyword_matches: List[str] = []
    keyword_gaps: List[str] = []
    experience_match: float = Field(0.0, ge=0, le=1)
    skills_match: float = Field(0.0, ge=0, le=1)


class CoverLetterResult(BaseModel):
    """Output from the CoverLetterGenerator agent."""
    job_id: str
    cover_letter: str
    cover_letter_review: str
    rewrite_needed: bool
    email_draft: str
    variant_id: Optional[str] = None  # For A/B testing
    tokens_used: int = 0


class ATSScanResult(BaseModel):
    """Output from the ATSScanner agent."""
    job_id: str
    score: float = Field(..., ge=0, le=100)
    verdict: ATSVerdict
    required_keywords_missing: List[str] = []
    nice_to_have_missing: List[str] = []
    format_warnings: List[str] = []
    quick_fixes: List[str] = []
    report: str = ""


class CompanyResearchResult(BaseModel):
    """Output from the CompanyResearcher agent."""
    company: str
    summary: str
    recent_news: List[str] = []
    tech_stack: List[str] = []
    interview_style: str = ""
    contact_name: Optional[str] = None
    contact_linkedin: Optional[str] = None
    culture_score: Optional[float] = Field(None, ge=0, le=10)
    cached_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Re-export for convenience
from typing import Literal  # noqa: E402
