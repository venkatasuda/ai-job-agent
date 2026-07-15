"""
app/prompts/templates.py — Centralized, versioned prompt library
=================================================================
ALL LLM prompts live here. No prompts scattered across ai/ modules.

Benefits:
  - One place to tune, A/B test, or version prompts
  - Hot-swappable: change a prompt without touching agent logic
  - Clear ownership: each prompt has a version, author, and description
  - Cost tracking: prompts expose expected token ranges

Usage:
    from app.prompts.registry import get_prompt
    prompt = get_prompt("cover_letter.draft", version="v2")
    text = prompt.render(job_title="SWE", company="Stripe", ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Any, Dict


@dataclass
class Prompt:
    """A versioned, renderable prompt template."""
    key: str
    version: str
    description: str
    template: str
    expected_input_tokens: int = 500
    expected_output_tokens: int = 500
    model_hint: str = "gpt-4o-mini"    # Cheapest model that handles this well
    tags: list[str] = field(default_factory=list)

    def render(self, **kwargs: Any) -> str:
        """Render the prompt with provided variables."""
        t = self.template
        for k, v in kwargs.items():
            t = t.replace(f"{{{k}}}", str(v))
        return t

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate for one call (gpt-4o-mini pricing)."""
        input_cost = self.expected_input_tokens * 0.00000015
        output_cost = self.expected_output_tokens * 0.0000006
        return round(input_cost + output_cost, 6)


# ── Scoring Prompts ───────────────────────────────────────────────────────────

SCORE_RESUME_V1 = Prompt(
    key="scoring.resume_match",
    version="v1",
    description="Score a resume against a job description. Returns 0–100 with reasoning.",
    expected_input_tokens=1500,
    expected_output_tokens=200,
    tags=["scoring", "core"],
    template="""You are an expert technical recruiter. Score how well this resume matches the job.

JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION:
{job_description}

CANDIDATE RESUME:
{resume}

Score 0–100 and explain. Return JSON:
{{
  "score": <int 0-100>,
  "reason": "<2 sentences>",
  "keyword_matches": ["<matched skill 1>", "<matched skill 2>"],
  "keyword_gaps": ["<missing skill 1>", "<missing skill 2>"],
  "experience_match": <0.0-1.0>,
  "skills_match": <0.0-1.0>
}}""",
)


# ── Cover Letter Prompts ──────────────────────────────────────────────────────

COVER_LETTER_DRAFT_V2 = Prompt(
    key="cover_letter.draft",
    version="v2",
    description="First-pass cover letter draft. Drafter step in drafter-reviewer pipeline.",
    expected_input_tokens=1800,
    expected_output_tokens=600,
    tags=["cover_letter", "generation"],
    template="""You are a professional cover letter writer. Write a compelling cover letter.

CANDIDATE BACKGROUND:
{resume}

JOB: {job_title} at {company}
LOCATION: {location}
JOB DESCRIPTION (key parts):
{job_description}

ACADEMIC HIGHLIGHTS (if Masters/PhD):
{academic_highlights}

Instructions:
- Opening: Hook the reader in the first sentence (avoid "I am applying for...")
- Paragraph 2: Your most relevant technical achievement (specific numbers/impact)
- Paragraph 3: Why THIS company specifically (research their product/mission)
- Closing: Confident call to action, not desperate
- Length: 250–350 words
- Tone: Confident, specific, genuine — not generic

Write the cover letter now:""",
)

COVER_LETTER_REVIEW_V2 = Prompt(
    key="cover_letter.review",
    version="v2",
    description="Reviewer step: critique draft and decide if rewrite is needed.",
    expected_input_tokens=800,
    expected_output_tokens=300,
    tags=["cover_letter", "review"],
    template="""You are a strict cover letter editor. Review this draft.

JOB: {job_title} at {company}

DRAFT COVER LETTER:
{draft}

Critique it hard. Check for:
1. Generic opener (instant reject)
2. Missing specific achievements with numbers
3. No mention of company-specific reasons
4. Filler phrases ("I am a fast learner", "team player", etc.)
5. Too long (>400 words) or too short (<200 words)

Output:
REWRITE_NEEDED: YES/NO
ISSUES: <bullet list of problems>
SCORE: <1-10>
ONE_LINE_FIX: <the single most important change>""",
)

COVER_LETTER_REVISE_V2 = Prompt(
    key="cover_letter.revise",
    version="v2",
    description="Revise draft based on reviewer feedback.",
    expected_input_tokens=1200,
    expected_output_tokens=600,
    tags=["cover_letter", "revision"],
    template="""Revise this cover letter based on the critique.

ORIGINAL DRAFT:
{draft}

CRITIQUE:
{critique}

JOB: {job_title} at {company}

Write an improved version that addresses all critique points.
Keep what works. Fix what doesn't. Same length target (250–350 words).""",
)

COVER_LETTER_EMAIL_V1 = Prompt(
    key="cover_letter.email_draft",
    version="v1",
    description="Short application email (for email submissions, not portal uploads).",
    expected_input_tokens=500,
    expected_output_tokens=150,
    tags=["cover_letter", "email"],
    template="""Write a short job application email (NOT a full cover letter).

Role: {job_title} at {company}
Key strength: {top_strength}

Write 3–4 sentences:
- Subject line
- Brief intro (1 sentence)
- Top qualification (1 sentence)
- Call to action (1 sentence)

Subject: [subject line]
Body: [email body]""",
)


# ── Company Research Prompts ──────────────────────────────────────────────────

COMPANY_RESEARCH_V1 = Prompt(
    key="company.research",
    version="v1",
    description="Deep company research: culture, tech stack, interview style, contact.",
    expected_input_tokens=1000,
    expected_output_tokens=500,
    tags=["company", "research"],
    template="""Research this company for a job application.

COMPANY: {company}
ROLE: {job_title}
WEB RESEARCH NOTES:
{web_notes}

Return JSON:
{{
  "summary": "<2 sentence company overview>",
  "recent_news": ["<news item 1>", "<news item 2>"],
  "tech_stack": ["<tech 1>", "<tech 2>"],
  "interview_style": "<what their interviews are like>",
  "culture_notes": "<3 bullet points about culture>",
  "why_work_here": "<genuine reason to want this job>",
  "red_flags": ["<flag 1>"],
  "culture_score": <1-10>
}}""",
)


# ── ATS Scanner Prompts ───────────────────────────────────────────────────────

ATS_SCAN_V1 = Prompt(
    key="ats.scan",
    version="v1",
    description="ATS resume compatibility scan. Score + missing keywords + format issues.",
    expected_input_tokens=1500,
    expected_output_tokens=400,
    tags=["ats", "resume"],
    template="""Simulate an ATS (Applicant Tracking System) scan.

JOB DESCRIPTION:
{job_description}

RESUME:
{resume}

Return JSON:
{{
  "score": <0-100>,
  "verdict": "<PASS|WARN|FAIL>",
  "required_keywords_missing": ["<keyword>"],
  "nice_to_have_missing": ["<keyword>"],
  "format_warnings": ["<warning>"],
  "quick_fixes": ["<specific fix>"]
}}""",
)


# ── Interview Prep Prompts ────────────────────────────────────────────────────

INTERVIEW_PREP_V1 = Prompt(
    key="interview.prep",
    version="v1",
    description="Generate role-specific interview questions + STAR story bank.",
    expected_input_tokens=1200,
    expected_output_tokens=800,
    tags=["interview", "prep"],
    template="""Generate interview prep for this role.

COMPANY: {company}
ROLE: {job_title}
RESUME HIGHLIGHTS: {resume_highlights}

Return JSON:
{{
  "behavioral_questions": [
    {{"question": "...", "star_hint": "...", "why_asked": "..."}}
  ],
  "technical_questions": ["<question>"],
  "company_specific": ["<question about company/product>"],
  "questions_to_ask": ["<smart question to ask interviewer>"],
  "star_stories": [
    {{"situation": "...", "task": "...", "action": "...", "result": "..."}}
  ]
}}""",
)


# ── Cold Outreach Prompts ─────────────────────────────────────────────────────

COLD_OUTREACH_LINKEDIN_V1 = Prompt(
    key="outreach.linkedin_dm",
    version="v1",
    description="LinkedIn DM under 280 characters. Warm, specific, not spammy.",
    expected_input_tokens=400,
    expected_output_tokens=100,
    tags=["outreach", "linkedin"],
    template="""Write a LinkedIn DM to a recruiter/employee at {company}.

Role I'm targeting: {job_title}
My background: {background}
Connection angle: {connection}

Rules:
- Under 280 characters (hard limit)
- Do NOT start with "Hi, I came across your profile"
- Be specific — mention company/role/one specific thing
- End with a soft ask, not "can we hop on a call?"

DM:""",
)

COLD_EMAIL_V1 = Prompt(
    key="outreach.cold_email",
    version="v1",
    description="Cold email to hiring manager. Under 150 words.",
    expected_input_tokens=600,
    expected_output_tokens=200,
    tags=["outreach", "email"],
    template="""Write a cold email to a hiring manager at {company} about the {job_title} role.

My top credential: {top_credential}
Why this company: {why_company}

Format:
Subject: [subject]
Body: [3 short paragraphs, under 150 words total]
- P1: Who you are + why you're writing (2 sentences)
- P2: Your most relevant achievement (with number/impact)
- P3: Soft ask""",
)


# ── Salary / Market Prompts ───────────────────────────────────────────────────

SALARY_ESTIMATE_V1 = Prompt(
    key="salary.estimate",
    version="v1",
    description="Estimate salary range from JD text and market data.",
    expected_input_tokens=600,
    expected_output_tokens=150,
    tags=["salary"],
    template="""Estimate the salary range for this role.

ROLE: {job_title}
COMPANY: {company}
LOCATION: {location}
JD TEXT: {jd_excerpt}
DEGREE: {degree}
YOE: {years_experience}

Return JSON:
{{
  "min_salary": <int>,
  "max_salary": <int>,
  "midpoint": <int>,
  "currency": "USD",
  "notes": "<why this range>",
  "masters_premium": "<% above BS median>"
}}""",
)


# ── Upskill Prompts ───────────────────────────────────────────────────────────

UPSKILL_V1 = Prompt(
    key="upskill.analysis",
    version="v1",
    description="Weekly skill gap analysis from scraped job data.",
    expected_input_tokens=2000,
    expected_output_tokens=600,
    tags=["upskill", "weekly"],
    template="""Analyze this week's job market data and generate an upskill plan.

TOP SKILLS IN DEMAND:
{top_skills}

CANDIDATE'S CURRENT SKILLS:
{current_skills}

TOP COMPANIES HIRING:
{top_companies}

Generate a markdown upskill report:
## Skill Gap Analysis
[3 skills to learn NOW, 3 to learn next month]

## This Week's Learning Plan
[Specific daily tasks, free resources only]

## 30-Day Goal
[One achievable milestone]""",
)


# Registry of all prompts (imported by registry.py)
ALL_PROMPTS: list[Prompt] = [
    SCORE_RESUME_V1,
    COVER_LETTER_DRAFT_V2,
    COVER_LETTER_REVIEW_V2,
    COVER_LETTER_REVISE_V2,
    COVER_LETTER_EMAIL_V1,
    COMPANY_RESEARCH_V1,
    ATS_SCAN_V1,
    INTERVIEW_PREP_V1,
    COLD_OUTREACH_LINKEDIN_V1,
    COLD_EMAIL_V1,
    SALARY_ESTIMATE_V1,
    UPSKILL_V1,
]
