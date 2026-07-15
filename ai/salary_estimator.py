"""
Salary Estimator — inspired by MadsLorentzen/ai-job-search's salary_lookup.py

Estimates salary range for jobs where compensation isn't listed.
Also generates negotiation playbooks for specific offers.
"""

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

SALARY_PROMPT = """You are a compensation expert with deep knowledge of tech industry salaries.

## Job Details
Title: {title}
Company: {company}
Location: {location}
Remote: {is_remote}
Job Type: {job_type}
Description excerpt:
{description}

## Task
Estimate the total compensation range for this role (2025-2026 market rates).

Respond ONLY as valid JSON:
{{
  "base_salary_min": <integer USD annual>,
  "base_salary_max": <integer USD annual>,
  "total_comp_min": <integer USD annual including equity/bonus estimate>,
  "total_comp_max": <integer USD annual>,
  "level_estimate": "<e.g. Senior IC / Staff / L5 equivalent>",
  "confidence": "<low/medium/high>",
  "notes": "<one sentence on key salary drivers>"
}}"""

NEGOTIATION_PROMPT = """You are a salary negotiation coach.

## Job: {title} at {company}
## Estimated Market Range: ${salary_min:,} - ${salary_max:,} base
## Candidate: {resume_excerpt}

Generate a concise negotiation playbook:

**1. Opening Anchor** — What number to say first if asked about salary expectations

**2. Justification Points** — 3 specific data points from the candidate's background to justify the ask

**3. Counter Scripts**
- If they say "that's above our band": [exact response]
- If they say "we need to move fast": [exact response]
- If they offer equity instead of base: [exact response]

**4. Walk-Away Number** — Based on the market range, the minimum acceptable offer

Keep each section to 2-3 sentences max."""


class SalaryEstimator:
    def __init__(self, config: dict, resume_text: str = ""):
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

    def _llm(self, prompt: str, json_mode: bool = False) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            kwargs = dict(model=self.model, messages=[{"role": "user", "content": prompt}],
                         temperature=0.1, max_tokens=500)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            return client.chat.completions.create(**kwargs).choices[0].message.content.strip()
        elif self.provider == "gemini":
            import google.generativeai as genai
            api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        elif self.provider == "ollama":
            import requests
            resp = requests.post("http://localhost:11434/api/generate",
                json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=60)
            return resp.json().get("response", "").strip()
        raise ValueError(f"Unknown provider: {self.provider}")

    def estimate(self, job: Dict) -> Dict:
        if job.get("salary_min") and job.get("salary_max"):
            return {
                "salary_min": job["salary_min"], "salary_max": job["salary_max"],
                "total_comp_min": int(job["salary_min"] * 1.2),
                "total_comp_max": int(job["salary_max"] * 1.35),
                "level_estimate": "From listing", "confidence": "high",
                "notes": "Salary provided in the job listing.",
            }
        try:
            import json
            raw = self._llm(SALARY_PROMPT.format(
                title=job.get("title", ""), company=job.get("company", ""),
                location=job.get("location", ""), is_remote=job.get("is_remote", False),
                job_type=job.get("job_type", "fulltime"),
                description=(job.get("description") or "")[:1500],
            ), json_mode=(self.provider == "openai"))
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Salary estimate failed for {job.get('title')}: {e}")
            return {"salary_min": None, "salary_max": None, "level_estimate": "Unknown",
                    "confidence": "low", "notes": f"Estimation failed: {e}"}

    def get_negotiation_playbook(self, job: Dict) -> str:
        data = self.estimate(job)
        s_min = data.get("salary_min") or 0
        s_max = data.get("salary_max") or 0
        if not s_min or not s_max:
            return "[Salary estimate unavailable — cannot generate negotiation playbook]"
        try:
            return self._llm(NEGOTIATION_PROMPT.format(
                title=job.get("title", ""), company=job.get("company", ""),
                salary_min=s_min, salary_max=s_max, resume_excerpt=self.resume[:600],
            ))
        except Exception as e:
            return f"[Negotiation coaching unavailable: {e}]"

    def enrich_jobs(self, jobs: list) -> list:
        for job in jobs:
            if not job.get("salary_estimated"):
                data = self.estimate(job)
                if not job.get("salary_min"):
                    job["salary_min"] = data.get("salary_min")
                if not job.get("salary_max"):
                    job["salary_max"] = data.get("salary_max")
                job["total_comp_min"] = data.get("total_comp_min")
                job["total_comp_max"] = data.get("total_comp_max")
                job["salary_level"] = data.get("level_estimate", "")
                job["salary_confidence"] = data.get("confidence", "low")
                job["salary_notes"] = data.get("notes", "")
                job["salary_estimated"] = True
        return jobs
