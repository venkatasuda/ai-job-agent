"""
Company Hiring Signal Monitor
==============================
Funding = hiring. Layoffs = avoid. This module monitors both.

Signals tracked:
  GREEN (apply now):
    - Recent Series A/B/C/D funding announcement
    - Company added headcount > 20% in last 6 months
    - CEO/CTO posted about "building the team"
    - New office opened

  RED (skip or caution):
    - Layoff announcement (Layoffs.fyi, TechCrunch)
    - Hiring freeze rumour (Blind, Reddit)
    - Recent earnings miss (public companies)
    - Mass resignation signals (Glassdoor review spike)

Sources: Crunchbase (free API), Layoffs.fyi, DuckDuckGo news search
"""

import logging
import os
import re
import json
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SIGNAL_ANALYSIS_PROMPT = """Analyze these news snippets about {company} and classify their hiring signal.

News/information:
{news_text}

Return JSON:
{{
  "signal": "<GREEN|YELLOW|RED>",
  "confidence": "<High|Medium|Low>",
  "signal_reason": "<one sentence why>",
  "funding_info": "<funding round/amount if mentioned, else null>",
  "layoff_info": "<layoff details if mentioned, else null>",
  "hiring_velocity": "<Accelerating|Stable|Decelerating|Unknown>",
  "apply_recommendation": "<Apply Now|Apply with Caution|Wait|Skip>",
  "summary": "<2 sentences about company's current hiring situation>"
}}"""

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}


class HiringSignalMonitor:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache_path = Path("hiring_signals_cache.json")
        self._cache = self._load_cache()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str) -> dict:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2, max_tokens=400,
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content)
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                text = genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text
                m = re.search(r'\{.*\}', text, re.DOTALL)
                return json.loads(m.group()) if m else {}
        except Exception as e:
            logger.warning(f"LLM signal analysis failed: {e}")
        return {"signal": "YELLOW", "confidence": "Low", "apply_recommendation": "Apply with Caution"}

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text())
                # Expire entries older than 3 days
                cutoff = (datetime.utcnow() - timedelta(days=3)).isoformat()
                return {k: v for k, v in data.items() if v.get("_cached_at", "") > cutoff}
            except Exception:
                pass
        return {}

    def _save_cache(self):
        self._cache_path.write_text(json.dumps(self._cache, indent=2))

    def _search_news(self, company: str) -> str:
        """Search DuckDuckGo for recent news about company hiring/funding/layoffs."""
        snippets = []
        queries = [
            f"{company} funding 2024 2025",
            f"{company} layoffs hiring freeze 2024 2025",
            f"{company} headcount growth hiring",
        ]
        for query in queries[:2]:
            try:
                resp = requests.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers=HEADERS, timeout=8,
                )
                data = resp.json()
                abstract = data.get("AbstractText", "")
                if abstract:
                    snippets.append(abstract)
                for topic in data.get("RelatedTopics", [])[:3]:
                    text = topic.get("Text", "")
                    if text and company.lower() in text.lower():
                        snippets.append(text)
            except Exception:
                pass
        return "\n".join(snippets[:5]) or f"No recent news found for {company}."

    def _check_layoffs_fyi(self, company: str) -> Optional[str]:
        """Check layoffs.fyi for recent layoff data."""
        try:
            resp = requests.get(
                "https://layoffs.fyi/",
                headers=HEADERS, timeout=8,
            )
            if company.lower() in resp.text.lower():
                return f"⚠️ {company} appears in recent layoff data on layoffs.fyi"
        except Exception:
            pass
        return None

    def analyze_company(self, company: str, force_refresh: bool = False) -> Dict:
        """Get hiring signal for a company. Cached for 3 days."""
        if company in self._cache and not force_refresh:
            return self._cache[company]

        logger.info(f"Checking hiring signals: {company}")
        news = self._search_news(company)
        layoff_warning = self._check_layoffs_fyi(company)
        if layoff_warning:
            news = layoff_warning + "\n" + news

        result = self._llm_json(SIGNAL_ANALYSIS_PROMPT.format(
            company=company, news_text=news[:2000]
        ))
        result["_cached_at"] = datetime.utcnow().isoformat()
        result["_company"] = company
        self._cache[company] = result
        self._save_cache()
        return result

    def enrich_jobs(self, jobs: List[Dict], threshold: int = 70) -> List[Dict]:
        """Add hiring_signal to high-score jobs."""
        seen_companies = set()
        for job in jobs:
            company = job.get("company", "")
            if not company or (job.get("score") or 0) < threshold:
                continue
            if company not in seen_companies:
                try:
                    signal = self.analyze_company(company)
                    seen_companies.add(company)
                except Exception as e:
                    logger.warning(f"Hiring signal failed for {company}: {e}")
                    signal = {}
            else:
                signal = self._cache.get(company, {})
            job["hiring_signal"] = signal.get("signal", "YELLOW")
            job["hiring_signal_reason"] = signal.get("signal_reason", "")
            job["apply_recommendation"] = signal.get("apply_recommendation", "Apply with Caution")
        return jobs

    def get_red_flag_companies(self) -> List[str]:
        return [c for c, d in self._cache.items() if d.get("signal") == "RED"]

    def get_green_signal_companies(self) -> List[str]:
        return [c for c, d in self._cache.items() if d.get("signal") == "GREEN"]
