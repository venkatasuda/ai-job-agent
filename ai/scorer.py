"""
Job Scorer — uses LLM to score how well a job matches the user's resume.
Returns a score 0-100 plus a brief explanation.

Supports: OpenAI (gpt-4o-mini recommended), Google Gemini, Ollama (local/free).
"""

import json
import logging
import os
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


SCORE_PROMPT = """You are an expert recruiter and career coach.

## Candidate Resume
{resume}

## Job Posting
Title: {title}
Company: {company}
Location: {location}
Description:
{description}

## Task
Score how well this candidate matches this job on a scale of 0-100.
Consider: skills match, experience level, location/remote fit, industry fit.

Respond ONLY with valid JSON in this exact format:
{{
  "score": <integer 0-100>,
  "match_reasons": ["reason 1", "reason 2", "reason 3"],
  "gap_reasons": ["gap 1", "gap 2"],
  "verdict": "<one sentence summary>"
}}"""


class JobScorer:
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

    def _call_openai(self, prompt: str) -> str:
        client = self._get_openai_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    def _call_gemini(self, prompt: str) -> str:
        import google.generativeai as genai
        api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.model or "gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text

    def _call_ollama(self, prompt: str) -> str:
        """Use local Ollama (free). Run `ollama pull llama3` first."""
        import requests
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": self.model or "llama3", "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "{}")

    def _llm(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._call_openai(prompt)
        elif self.provider == "gemini":
            return self._call_gemini(prompt)
        elif self.provider == "ollama":
            return self._call_ollama(prompt)
        else:
            raise ValueError(f"Unknown AI provider: {self.provider}")

    def score_job(self, job: Dict) -> Tuple[int, str, list, list]:
        """
        Returns (score, verdict, match_reasons, gap_reasons)
        Score is 0-100. Falls back to (0, error_msg, [], []) on failure.
        """
        # Truncate description to avoid token limits
        description = (job.get("description") or "")[:3000]
        if not description:
            return 50, "No description available", [], []

        prompt = SCORE_PROMPT.format(
            resume=self.resume[:4000],
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=description,
        )

        try:
            raw = self._llm(prompt)
            # Extract JSON even if wrapped in markdown code blocks
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            score = max(0, min(100, int(data.get("score", 50))))
            verdict = data.get("verdict", "")
            match_reasons = data.get("match_reasons", [])
            gap_reasons = data.get("gap_reasons", [])
            return score, verdict, match_reasons, gap_reasons
        except Exception as e:
            logger.error(f"Scoring error for {job.get('title')} @ {job.get('company')}: {e}")
            return 0, f"Scoring error: {e}", [], []

    def score_jobs(self, jobs: list) -> list:
        """Score a list of jobs, adding score/verdict fields to each."""
        min_score = self.cfg.get("min_match_score", 70)
        scored = []
        for job in jobs:
            score, verdict, matches, gaps = self.score_job(job)
            job["score"] = score
            job["verdict"] = verdict
            job["match_reasons"] = matches
            job["gap_reasons"] = gaps
            if score >= min_score:
                scored.append(job)
                logger.info(f"✓ {score}/100 — {job['title']} @ {job['company']}")
            else:
                logger.debug(f"✗ {score}/100 (below threshold) — {job['title']} @ {job['company']}")

        scored.sort(key=lambda j: j["score"], reverse=True)
        return scored
