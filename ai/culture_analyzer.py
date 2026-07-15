"""
Company Culture Analyzer
=========================
A senior consultant warns you about toxic companies BEFORE you apply.
They've heard the horror stories. This module does the same.

Fetches and analyzes:
  - Glassdoor/Blind/Reddit sentiment for the company
  - Interview difficulty + process (how many rounds, types)
  - Red flags: high turnover, layoff history, management issues
  - Green flags: strong engineering culture, good growth, remote-friendly
  - Insider tips: what actually matters in their hiring process

Uses web search + LLM summarization since we can't scrape Glassdoor directly.
"""

import logging
import os
import re
from typing import Dict

logger = logging.getLogger(__name__)

CULTURE_ANALYSIS_PROMPT = """You are a recruiter who has worked with 500+ candidates at {company}.
Based on your knowledge of this company's culture, interview process, and reputation:

Company: {company}
Role: {title}

Provide an honest assessment in this exact JSON format:
{{
  "culture_score": <1-10 integer>,
  "culture_summary": "<2 sentences: overall vibe and what kind of person thrives here>",
  "interview_process": {{
    "rounds": <estimated number>,
    "types": ["phone screen", "technical", "system design", etc],
    "difficulty": "<Easy|Medium|Hard|Very Hard>",
    "tips": "<2 sentences of what actually matters in their hiring process>"
  }},
  "green_flags": ["list of genuine positives — max 4"],
  "red_flags": ["honest warnings candidates should know — max 4, empty if none"],
  "layoff_risk": "<Low|Medium|High|Unknown>",
  "remote_culture": "<Remote-first|Hybrid|Office-first|Unknown>",
  "growth_opportunity": "<Strong|Moderate|Limited|Unknown>",
  "glassdoor_sentiment": "<Positive|Mixed|Negative|Unknown>",
  "best_for": "<type of engineer/person this company is ideal for>"
}}

Be honest. Candidates deserve the truth, not a PR piece."""

WEB_SEARCH_SUMMARY_PROMPT = """Summarize what employees say about working at {company} based on these search results.
Focus on: culture, management, work-life balance, interview process, red flags.
Be honest and specific.

Search results:
{search_results}

Return a 3-4 sentence summary."""


class CultureAnalyzer:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache: Dict[str, Dict] = {}  # company → analysis (avoid re-fetching same company)

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str) -> dict:
        import json
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        else:
            # Gemini / Ollama — get text then parse
            if self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                text = genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
            else:
                import requests
                resp = requests.post("http://localhost:11434/api/generate",
                    json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=120)
                text = resp.json().get("response", "").strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {}

    def _llm(self, prompt: str, max_tokens: int = 400) -> str:
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

    def _try_web_search(self, company: str) -> str:
        """Try to fetch real Glassdoor/Reddit sentiment via DuckDuckGo."""
        try:
            import requests as req
            query = f"{company} glassdoor reviews employee culture 2024 site:glassdoor.com OR site:reddit.com"
            resp = req.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
                timeout=8,
            )
            data = resp.json()
            snippets = []
            for result in data.get("RelatedTopics", [])[:5]:
                text = result.get("Text", "")
                if text:
                    snippets.append(text)
            if snippets:
                return "\n".join(snippets)
        except Exception:
            pass
        return ""

    def analyze(self, company: str, title: str = "") -> Dict:
        """Analyze company culture. Returns structured dict."""
        if company in self._cache:
            logger.info(f"Culture cache hit: {company}")
            return self._cache[company]

        logger.info(f"Analyzing culture: {company}")

        # Try web search for real data first
        web_data = self._try_web_search(company)
        extra_context = ""
        if web_data:
            try:
                extra_context = self._llm(WEB_SEARCH_SUMMARY_PROMPT.format(
                    company=company, search_results=web_data[:1500]
                ), max_tokens=200)
            except Exception:
                pass

        # Main LLM analysis
        prompt = CULTURE_ANALYSIS_PROMPT.format(company=company, title=title)
        if extra_context:
            prompt += f"\n\nAdditional context from employee reviews:\n{extra_context}"

        result = self._llm_json(prompt)
        result["_web_context"] = extra_context  # store for transparency
        self._cache[company] = result
        return result

    def enrich_jobs(self, jobs: list, threshold: int = 70) -> list:
        """Add culture_analysis to jobs above threshold."""
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("culture_analysis"):
                company = job.get("company", "")
                if not company:
                    continue
                try:
                    result = self.analyze(company, job.get("title", ""))
                    job["culture_analysis"] = result
                    job["culture_score"] = result.get("culture_score")
                    job["culture_red_flags"] = result.get("red_flags", [])
                except Exception as e:
                    logger.error(f"Culture analysis failed for {company}: {e}")
        return jobs

    @staticmethod
    def format_report(analysis: dict) -> str:
        if not analysis:
            return "No culture data available."
        score = analysis.get("culture_score", "?")
        lines = [
            f"Culture Score: {score}/10",
            f"Summary: {analysis.get('culture_summary', '')}",
            f"Best For: {analysis.get('best_for', '')}",
            "",
            f"Remote Policy: {analysis.get('remote_culture', '?')}",
            f"Growth: {analysis.get('growth_opportunity', '?')}",
            f"Layoff Risk: {analysis.get('layoff_risk', '?')}",
            f"Glassdoor Sentiment: {analysis.get('glassdoor_sentiment', '?')}",
            "",
        ]
        interview = analysis.get("interview_process", {})
        if interview:
            lines += [
                f"Interview: {interview.get('rounds', '?')} rounds — {interview.get('difficulty', '?')} difficulty",
                f"Types: {', '.join(interview.get('types', []))}",
                f"Tips: {interview.get('tips', '')}",
                "",
            ]
        green = analysis.get("green_flags", [])
        if green:
            lines.append("Green Flags: " + " | ".join(green))
        red = analysis.get("red_flags", [])
        if red:
            lines.append("Red Flags: " + " | ".join(red))
        return "\n".join(lines)
