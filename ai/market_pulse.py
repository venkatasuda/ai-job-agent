"""
Job Market Pulse — Weekly Trend Tracker
=========================================
Tracks real demand changes across job postings:
  - Which skills are trending UP / DOWN this week
  - Which companies are posting most aggressively (hiring surge)
  - New companies entering the market
  - Salary trend by role
  - Which sources (LinkedIn vs ATS vs New Grad) yield best quality

Runs weekly. Outputs a markdown report + dashboard widget.
Compares current week vs last week from YOUR own scraped data.
No external API needed — uses your own jobs.db as the data source.
"""

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

PULSE_PROMPT = """You are a job market analyst. Analyze this week's job postings data
and identify the most important trends a job seeker should know.

This week's data:
{data}

Previous week comparison:
{prev_data}

Write a concise weekly market pulse report in markdown:

## 🔥 This Week's Market Pulse — {date}

### Trending Up (apply now)
[skills/roles/companies seeing increased demand]

### Trending Down (deprioritize)
[skills/roles seeing decreased postings]

### 🚀 Companies on a Hiring Surge
[companies with most new postings this week]

### 💰 Salary Signals
[any notable salary trends]

### 🎯 This Week's Strategy
[2-3 specific action items based on the data]

Keep it under 400 words. Be specific with numbers."""


class MarketPulse:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._history_path = Path("market_pulse_history.json")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 600) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4, max_tokens=max_tokens,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        except Exception as e:
            logger.warning(f"Market pulse LLM failed: {e}")
        return ""

    def _extract_skills(self, jobs: List[Dict]) -> Counter:
        """Extract skill mentions from job descriptions."""
        SKILLS = [
            "Python", "Java", "Go", "Rust", "TypeScript", "JavaScript", "C++", "Scala",
            "PyTorch", "TensorFlow", "Kubernetes", "Docker", "AWS", "GCP", "Azure",
            "Spark", "Kafka", "Redis", "PostgreSQL", "MongoDB", "Elasticsearch",
            "React", "FastAPI", "Django", "GraphQL", "gRPC",
            "Machine Learning", "Deep Learning", "NLP", "LLM", "RAG", "MLOps",
            "Data Engineering", "Platform Engineering", "DevOps", "SRE",
            "Distributed Systems", "Microservices", "System Design",
        ]
        counts = Counter()
        for job in jobs:
            text = ((job.get("title") or "") + " " + (job.get("description") or "")).lower()
            for skill in SKILLS:
                if skill.lower() in text:
                    counts[skill] += 1
        return counts

    def _compute_stats(self, jobs: List[Dict]) -> Dict:
        """Compute weekly stats from jobs list."""
        companies = Counter(j.get("company", "") for j in jobs)
        sources = Counter(j.get("source", "") for j in jobs)
        skills = self._extract_skills(jobs)
        scores = [j.get("score") or 0 for j in jobs if j.get("score")]
        salaries = [j.get("salary_min") for j in jobs if j.get("salary_min")]
        return {
            "total_jobs": len(jobs),
            "top_companies": companies.most_common(10),
            "top_skills": skills.most_common(15),
            "by_source": dict(sources),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_salary_min": round(sum(salaries) / len(salaries)) if salaries else 0,
            "remote_count": sum(1 for j in jobs if j.get("is_remote")),
            "new_grad_count": sum(1 for j in jobs if j.get("is_new_grad")),
        }

    def _load_history(self) -> List[Dict]:
        if self._history_path.exists():
            try:
                return json.loads(self._history_path.read_text())
            except Exception:
                pass
        return []

    def generate_report(self, db) -> str:
        """Generate weekly market pulse report from DB data."""
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()
        two_weeks_ago = (now - timedelta(days=14)).isoformat()

        all_jobs = db.get_all_jobs(limit=2000)
        this_week = [j for j in all_jobs if (j.get("scraped_at") or "") > week_ago]
        last_week = [j for j in all_jobs
                     if two_weeks_ago < (j.get("scraped_at") or "") <= week_ago]

        if len(this_week) < 5:
            return "Not enough data yet. Run the agent for a few days to generate market pulse."

        this_stats = self._compute_stats(this_week)
        prev_stats = self._compute_stats(last_week) if last_week else {}

        data_text = json.dumps(this_stats, indent=2, default=str)
        prev_text = json.dumps(prev_stats, indent=2, default=str) if prev_stats else "No previous week data yet."

        report = self._llm(PULSE_PROMPT.format(
            data=data_text[:2000],
            prev_data=prev_text[:1000],
            date=now.strftime("%B %d, %Y"),
        ), max_tokens=600)

        if not report:
            # Fallback: generate basic stats report
            report = self._format_basic_report(this_stats, prev_stats, now)

        # Save history
        history = self._load_history()
        history.append({"week": now.strftime("%Y-W%V"), "stats": this_stats, "report": report})
        history = history[-12:]  # keep 12 weeks
        self._history_path.write_text(json.dumps(history, indent=2))

        # Save markdown file
        fname = f"market_pulse_{now.strftime('%Y_%m_%d')}.md"
        Path(fname).write_text(report, encoding="utf-8")
        logger.info(f"Market pulse saved: {fname}")
        return report

    def _format_basic_report(self, stats: Dict, prev: Dict, now: datetime) -> str:
        top_skills = stats.get("top_skills", [])[:5]
        top_companies = stats.get("top_companies", [])[:5]
        lines = [
            f"## 🔥 Market Pulse — {now.strftime('%B %d, %Y')}",
            f"",
            f"**This week:** {stats['total_jobs']} jobs scraped | "
            f"Avg score: {stats['avg_score']} | "
            f"Remote: {stats['remote_count']} | New grad: {stats['new_grad_count']}",
            f"",
            f"### Top Skills in Demand",
        ]
        for skill, count in top_skills:
            lines.append(f"- {skill}: {count} mentions")
        lines += ["", "### Most Active Companies Hiring"]
        for company, count in top_companies:
            lines.append(f"- {company}: {count} postings")
        return "\n".join(lines)

    def get_skill_trend(self, skill: str) -> str:
        """Get trend direction for a specific skill based on history."""
        history = self._load_history()
        if len(history) < 2:
            return "Unknown (not enough history)"
        counts = []
        for entry in history[-4:]:
            skill_data = dict(entry.get("stats", {}).get("top_skills", []))
            counts.append(skill_data.get(skill, 0))
        if len(counts) >= 2:
            if counts[-1] > counts[0] * 1.2:
                return "📈 Trending UP"
            elif counts[-1] < counts[0] * 0.8:
                return "📉 Trending DOWN"
        return "➡️ Stable"
