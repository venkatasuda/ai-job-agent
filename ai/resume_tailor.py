"""
Resume Tailor — per-job resume bullet rewriter
===============================================
A 20-year consultant doesn't send the same resume to every job.
They rewrite the bullets to mirror the job's language and priorities.

Pipeline:
  1. Extract top 10 keywords/skills from JD
  2. Map candidate's existing bullets to those keywords
  3. Rewrite each bullet to incorporate missing keywords naturally
  4. Output a tailored resume text + a diff of what changed
"""

import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

KEYWORD_EXTRACT_PROMPT = """Extract the 15 most important ATS keywords from this job description.
Focus on: required skills, tech stack, action verbs, domain terms, certifications.

Job Description:
{description}

Return as a simple comma-separated list. No explanations."""

TAILOR_PROMPT = """You are a professional resume writer with 20 years of experience.
Your job: rewrite the candidate's resume bullets to be a stronger match for this specific job.

## Candidate Resume
{resume}

## Target Job
Company: {company}
Title: {title}

## Key ATS Keywords to incorporate (naturally — no keyword stuffing)
{keywords}

## Rules
- Keep ALL facts accurate — do NOT invent achievements, metrics, or technologies
- Rewrite existing bullets to use the job's language where truthful
- Add missing keywords only if the candidate's experience genuinely supports it
- Preserve bullet count and rough structure
- Make opening summary/headline match this specific role
- Output the full tailored resume text only

Output the complete tailored resume."""

DIFF_PROMPT = """Compare original and tailored resume. List ONLY lines that changed.
Format each change as:
BEFORE: <original line>
AFTER:  <tailored line>

Original:
{original}

Tailored:
{tailored}

List only meaningful changes (skip whitespace-only diffs)."""


class ResumeTailor:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
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

    def _llm(self, prompt: str, max_tokens: int = 1200) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        elif self.provider == "gemini":
            import google.generativeai as genai
            api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        elif self.provider == "ollama":
            import requests
            resp = requests.post("http://localhost:11434/api/generate",
                json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=120)
            return resp.json().get("response", "").strip()
        raise ValueError(f"Unknown provider: {self.provider}")

    def extract_keywords(self, job: Dict) -> List[str]:
        """Extract top ATS keywords from job description."""
        description = (job.get("description") or "")[:3000]
        raw = self._llm(KEYWORD_EXTRACT_PROMPT.format(description=description), max_tokens=200)
        keywords = [k.strip() for k in re.split(r"[,\n]", raw) if k.strip()]
        return keywords[:15]

    def tailor(self, job: Dict) -> Dict[str, str]:
        """
        Returns dict with:
          - tailored_resume: full rewritten resume text
          - keywords: extracted JD keywords
          - changes: diff of what changed
        """
        logger.info(f"Tailoring resume for {job.get('title')} @ {job.get('company')}")

        keywords = self.extract_keywords(job)
        keywords_str = ", ".join(keywords)

        tailored = self._llm(TAILOR_PROMPT.format(
            resume=self.resume[:4000],
            company=job.get("company", ""),
            title=job.get("title", ""),
            keywords=keywords_str,
        ), max_tokens=1500)

        # Generate diff summary
        try:
            changes = self._llm(DIFF_PROMPT.format(
                original=self.resume[:2000],
                tailored=tailored[:2000],
            ), max_tokens=600)
        except Exception:
            changes = "Diff unavailable."

        return {
            "tailored_resume": tailored,
            "ats_keywords": keywords,
            "resume_changes": changes,
        }

    def enrich_jobs(self, jobs: list, threshold: int = 70) -> list:
        """Add tailored_resume to jobs scoring above threshold."""
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("tailored_resume"):
                try:
                    result = self.tailor(job)
                    job.update(result)
                except Exception as e:
                    logger.error(f"Resume tailor failed for {job.get('title')}: {e}")
        return jobs
