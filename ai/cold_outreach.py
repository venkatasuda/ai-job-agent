"""
Cold Outreach Generator
========================
Referrals increase interview odds by 10x. A senior consultant always
knows someone at the target company — or reaches out to find one.

Generates per job:
  1. LinkedIn DM to a hiring manager / employee (under 300 chars — fits DM limit)
  2. Cold email to hiring manager (subject + body)
  3. Alumni/mutual-connection message (warm outreach variant)
  4. Follow-up message if no response in 5 days

The messages are personalized to the company + role + candidate background.
They do NOT beg — they lead with value.
"""

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

LINKEDIN_DM_PROMPT = """Write a LinkedIn DM to a {role} at {company} about the {title} role.

Candidate background snippet:
{resume_snippet}

Rules:
- Under 280 characters (LinkedIn DM limit for cold messages)
- Lead with one specific thing about {company} (product, mission, recent news)
- Mention one relevant achievement from the candidate's background
- End with a soft ask — NOT "can I have a job?" but "would you be open to a quick chat?"
- Natural, peer-to-peer tone. Not desperate or sycophantic.

Return ONLY the DM text."""

COLD_EMAIL_PROMPT = """Write a cold email to a hiring manager at {company} about the {title} role.

Candidate background:
{resume_snippet}

Job context:
{description_snippet}

Format:
Subject: <subject line>

<email body — 4 paragraphs max, under 200 words>

Rules:
- Subject line: specific, not "Interested in Opportunities"
- Para 1: one concrete thing about {company} you admire (product, mission, growth)
- Para 2: your most relevant achievement with a number
- Para 3: why THIS role at THIS company (not generic)
- Para 4: soft CTA — ask for 15 min, not a job
- Sign off with name placeholder [YOUR NAME]"""

WARM_OUTREACH_PROMPT = """Write a warm outreach message to an {connection_type} who works at {company}.

Candidate background:
{resume_snippet}

Context: I'm applying for the {title} role and want to ask for an internal referral or insights.

Rules:
- Reference the shared connection (alumni / former colleague / mutual contact)
- Under 150 words
- Ask for a 15-min call OR just their honest take on the company
- Do NOT directly ask for a referral in the first message
- Warm, human, not transactional"""

FOLLOWUP_PROMPT = """Write a 3-sentence follow-up message to send 5 days after no response to a cold outreach.

Original context: {company}, {title} role
Medium: {medium}

Rules:
- Reference the previous message briefly ("I reached out last week...")
- Add one new value-add (a relevant project, insight, or company news)
- End with an easy out ("No worries if not the right time")
- Under 100 words"""


class ColdOutreachGenerator:
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

    def _llm(self, prompt: str, max_tokens: int = 400) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
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

    def _resume_snippet(self) -> str:
        """Take first 600 chars of resume as context."""
        return self.resume[:600]

    def generate_linkedin_dm(self, job: Dict, target_role: str = "Software Engineer") -> str:
        return self._llm(LINKEDIN_DM_PROMPT.format(
            role=target_role,
            company=job.get("company", ""),
            title=job.get("title", ""),
            resume_snippet=self._resume_snippet(),
        ), max_tokens=150)

    def generate_cold_email(self, job: Dict) -> str:
        return self._llm(COLD_EMAIL_PROMPT.format(
            company=job.get("company", ""),
            title=job.get("title", ""),
            resume_snippet=self._resume_snippet(),
            description_snippet=(job.get("description") or "")[:500],
        ), max_tokens=350)

    def generate_warm_outreach(self, job: Dict,
                                connection_type: str = "fellow alumni") -> str:
        return self._llm(WARM_OUTREACH_PROMPT.format(
            connection_type=connection_type,
            company=job.get("company", ""),
            title=job.get("title", ""),
            resume_snippet=self._resume_snippet(),
        ), max_tokens=200)

    def generate_followup(self, job: Dict, medium: str = "LinkedIn DM") -> str:
        return self._llm(FOLLOWUP_PROMPT.format(
            company=job.get("company", ""),
            title=job.get("title", ""),
            medium=medium,
        ), max_tokens=150)

    def generate_all(self, job: Dict) -> Dict[str, str]:
        """Generate the full outreach pack for a job."""
        logger.info(f"Generating cold outreach for {job.get('title')} @ {job.get('company')}")
        return {
            "outreach_linkedin_dm": self.generate_linkedin_dm(job),
            "outreach_cold_email": self.generate_cold_email(job),
            "outreach_warm_message": self.generate_warm_outreach(job),
            "outreach_followup": self.generate_followup(job),
        }

    def enrich_jobs(self, jobs: list, threshold: int = 75) -> list:
        """Add outreach messages to high-score jobs."""
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("outreach_linkedin_dm"):
                try:
                    result = self.generate_all(job)
                    job.update(result)
                except Exception as e:
                    logger.error(f"Cold outreach failed for {job.get('title')}: {e}")
        return jobs
