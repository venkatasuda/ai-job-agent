"""
Company Research + Contact Discovery
=====================================
Inspired by career-ops' `deep` and `contacto` modes.

For high-scoring jobs (score >= threshold):
1. DEEP RESEARCH: Company overview, AI strategy, recent news, engineering culture
2. CONTACT DISCOVERY: Find hiring manager/recruiter + LinkedIn message draft
"""

import logging
import os
import requests
from typing import Dict

logger = logging.getLogger(__name__)

RESEARCH_PROMPT = """You are a senior talent researcher helping a candidate prepare for an application.

## Job Posting
Title: {title}
Company: {company}
Description:
{description}

## Candidate Background (brief)
{resume_excerpt}

## Task
Research this company and produce a structured briefing. Cover:

1. **Company Overview** (2-3 sentences): What they do, size, stage
2. **AI/Tech Strategy**: Technologies, AI initiatives
3. **Recent News**: Funding, product launches, leadership changes in the last year
4. **Engineering Culture**: Reputation, remote policy, tech stack
5. **Why This Role Matters**: What problem does this team solve
6. **Candidate Angle**: Given the candidate's background, what unique angle to take

Be factual — if you don't know something, say so rather than hallucinating."""

CONTACT_PROMPT = """You are helping a job candidate identify who to reach out to at a company.

## Job Posting
Title: {title}
Company: {company}

## Task
1. Identify the MOST LIKELY person to contact (hiring manager / recruiter / peer)
2. Suggest their likely LinkedIn search query
3. Write TWO LinkedIn connection message variants (≤300 chars each)
4. One LinkedIn boolean search string to find them

Format:
CONTACT_TYPE: [hiring_manager / recruiter / peer]
SEARCH_QUERY: [what to type in LinkedIn search]
MESSAGE_A: [≤300 chars - for hiring manager]
MESSAGE_B: [≤300 chars - for recruiter]
BOOLEAN_SEARCH: [search string]"""


class CompanyResearcher:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self.research_threshold = max(self.cfg.get("min_match_score", 70), 75)
        self._client = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=900,
            )
            return resp.choices[0].message.content.strip()
        elif self.provider == "gemini":
            import google.generativeai as genai
            api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        elif self.provider == "ollama":
            resp = requests.post("http://localhost:11434/api/generate",
                json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=120)
            return resp.json().get("response", "").strip()
        raise ValueError(f"Unknown provider: {self.provider}")

    def research_company(self, job: Dict) -> str:
        try:
            return self._llm(RESEARCH_PROMPT.format(
                title=job.get("title", ""), company=job.get("company", ""),
                description=(job.get("description") or "")[:2000],
                resume_excerpt=self.resume[:800],
            ))
        except Exception as e:
            logger.error(f"Company research failed for {job.get('company')}: {e}")
            return f"[Research unavailable: {e}]"

    def discover_contact(self, job: Dict) -> str:
        try:
            return self._llm(CONTACT_PROMPT.format(
                title=job.get("title", ""), company=job.get("company", ""),
            ))
        except Exception as e:
            logger.error(f"Contact discovery failed: {e}")
            return f"[Contact discovery unavailable: {e}]"

    def enrich_jobs(self, jobs: list) -> list:
        eligible = [j for j in jobs if (j.get("score") or 0) >= self.research_threshold]
        if not eligible:
            logger.info("Company research: no jobs above threshold.")
            return jobs
        logger.info(f"Company research: enriching {len(eligible)} high-score jobs...")
        for job in eligible:
            if not job.get("company_research"):
                job["company_research"] = self.research_company(job)
            if not job.get("contact_info"):
                job["contact_info"] = self.discover_contact(job)
        return jobs
