"""
Cover Letter Generator v2 — Drafter-Reviewer-Reviser Pipeline
==============================================================
From MadsLorentzen/ai-job-search drafter-reviewer approach + career-ops email drafts.

3-pass pipeline:
  Pass 1 (DRAFT)   — write cover letter from resume + JD
  Pass 2 (REVIEW)  — critique for authenticity, specificity, ATS keywords
  Pass 3 (REVISE)  — rewrite incorporating critique (only if REWRITE_NEEDED: YES)

Also generates short application emails (career-ops feature).
"""

import logging
import os
from typing import Dict

from app.security.output_filter import OutputFilter

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────────

DRAFT_PROMPT = """You are an expert job application writer. Write a compelling cover letter.

## Candidate Resume
{resume}

## Job Posting
Company: {company}
Title: {title}
Description:
{description}

## Instructions
- 3 paragraphs, under 300 words
- Opening: hook that connects your background to THIS specific company/role
- Middle: 2 concrete achievements (numbers/metrics preferred) matching the JD requirements
- Close: clear call to action, enthusiasm for THIS company
- Avoid: "I am writing to apply", "passionate", "hardworking", "team player"
- Mirror key ATS terms from the job description naturally

Write only the cover letter body. No subject line or signature."""

REVIEW_PROMPT = """You are a harsh but constructive hiring manager reviewing a cover letter draft.

## Job Posting
Company: {company}
Title: {title}
Description:
{description}

## Cover Letter Draft
{draft}

Critique on these axes:
1. SPECIFICITY: Does it mention this specific company's products/mission/challenges? (not just the title)
2. ACHIEVEMENTS: Are the metrics concrete and relevant?
3. ATS KEYWORDS: Which important JD terms are missing?
4. CLICHES: List any cliched phrases to cut.
5. LENGTH: Is it under 300 words?

End your review with exactly:
REWRITE_NEEDED: YES
or
REWRITE_NEEDED: NO

If NO, include: IMPROVEMENT_NOTES: <one sentence of minor tweaks only>"""

REVISE_PROMPT = """You are rewriting a cover letter based on a reviewer's critique.

## Job Posting
Company: {company}
Title: {title}
Description:
{description}

## Original Draft
{draft}

## Reviewer Critique
{review}

Rewrite the cover letter addressing ALL critique points. Keep it under 300 words.
Return ONLY the revised cover letter body."""

EMAIL_DRAFT_PROMPT = """Write a short, professional job application email body.

Job: {title} at {company}
Candidate highlights (from cover letter):
{cl_snippet}

Instructions:
- 4-5 sentences max
- Subject line on first line (format: "Subject: ...")
- Then blank line, then email body
- Mention resume and cover letter are attached
- Natural, confident tone"""


class CoverLetterGenerator:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 800) -> str:
        provider = self.provider
        if provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        elif provider == "gemini":
            import google.generativeai as genai
            api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(
                self.model or "gemini-1.5-flash"
            ).generate_content(prompt).text.strip()
        elif provider == "ollama":
            import requests
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": self.model or "llama3", "prompt": prompt, "stream": False},
                timeout=120,
            )
            return resp.json().get("response", "").strip()
        raise ValueError(f"Unknown provider: {provider}")

    def generate(self, job: Dict) -> Dict[str, str]:
        """Run 3-pass drafter-reviewer pipeline. Returns dict with cover_letter + email_draft."""
        title = job.get("title", "")
        company = job.get("company", "")
        description = (job.get("description") or "")[:3000]

        # Pass 1: Draft
        logger.info(f"  CL Draft -> {title} @ {company}")
        draft = self._llm(DRAFT_PROMPT.format(
            resume=self.resume[:3000],
            title=title, company=company, description=description
        ), max_tokens=600)

        # Pass 2: Review
        logger.info(f"  CL Review -> {title} @ {company}")
        review = self._llm(REVIEW_PROMPT.format(
            title=title, company=company, description=description, draft=draft
        ), max_tokens=500)

        # Pass 3: Revise (only if reviewer flags YES)
        final_cl = draft
        if "REWRITE_NEEDED: YES" in review:
            logger.info(f"  CL Revise -> {title} @ {company}")
            final_cl = self._llm(REVISE_PROMPT.format(
                title=title, company=company, description=description,
                draft=draft, review=review
            ), max_tokens=600)

        # Output filter — strip placeholders, enforce length, flag missing company name
        validation = OutputFilter.validate_cover_letter(final_cl, job=job)
        if validation.issues:
            logger.debug(f"  CL output issues [{company}]: {validation.issues}")
        if validation.output:
            final_cl = validation.output

        # Append signature
        name = self.profile.get("name", "")
        email = self.profile.get("email", "")
        linkedin = self.profile.get("linkedin_url", "")
        final_cl = final_cl.strip()
        if name:
            final_cl += f"\n\nBest regards,\n{name}"
            if email:
                final_cl += f"\n{email}"
            if linkedin:
                final_cl += f"\n{linkedin}"

        # Email draft
        cl_snippet = final_cl[:400]
        email_draft = self._llm(EMAIL_DRAFT_PROMPT.format(
            title=title, company=company, cl_snippet=cl_snippet
        ), max_tokens=200)

        return {
            "cover_letter": final_cl,
            "cover_letter_review": review,
            "email_draft": email_draft,
        }

    def generate_batch(self, jobs: list) -> list:
        """Enrich a list of jobs with cover_letter, cover_letter_review, email_draft fields."""
        for job in jobs:
            if job.get("cover_letter"):
                continue
            try:
                result = self.generate(job)
                job.update(result)
            except Exception as e:
                logger.error(f"Cover letter failed for {job.get('title')}: {e}")
                job["cover_letter"] = f"[Cover letter generation failed: {e}]"
        return jobs
