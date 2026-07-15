"""
Career Path Advisor
====================
A 20-year consultant doesn't just find you jobs — they tell you
WHICH jobs to target to reach your 3-5 year goal, which titles
to avoid, what skills to build, and what moves to make strategically.

Features:
  - Career trajectory analysis (where you are vs where you want to be)
  - Role ladder: which titles to apply for NOW vs in 2 years
  - Skill gap roadmap to reach target role
  - Companies ranked by career growth potential for YOUR background
  - 90-day action plan: specific steps to land target role
  - Salary trajectory projection
"""

import logging
import os
import json
import re
from typing import Dict, List
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CAREER_ANALYSIS_PROMPT = """You are a senior career strategist with 20 years of experience
in tech recruiting. You help engineers navigate their career path strategically.

## Candidate Resume
{resume}

## Career Goal
Target Role: {target_role}
Target Timeline: {timeline}
Current Location: {location}
Remote Preference: {remote}

Analyze this candidate's situation and provide a comprehensive career strategy in JSON:

{{
  "current_level": "<current assessed level: Junior/Mid/Senior/Staff/Principal>",
  "current_titles_to_apply": ["3-5 titles the candidate should apply for RIGHT NOW — realistic matches"],
  "stretch_titles": ["2-3 titles that are a stretch but possible with strong application"],
  "avoid_titles": ["titles that are a step backward or poor fit — explain briefly"],
  "gap_to_target": {{
    "years_estimated": <integer>,
    "missing_skills": ["top 5 skills blocking target role"],
    "missing_experience": ["top 3 experience gaps — e.g., 'team leadership', 'system design at scale']",
    "what_you_have": ["3 strongest assets candidate already has for this path"]
  }},
  "skill_roadmap": [
    {{
      "skill": "<skill name>",
      "priority": "<High|Medium|Low>",
      "how_to_learn": "<specific resource or approach>",
      "time_to_learn": "<e.g., 4-6 weeks>"
    }}
  ],
  "company_targets": [
    {{
      "company_type": "<e.g., 'Series B AI startup', 'FAANG', 'mid-size SaaS'>",
      "why_good_fit": "<why this type accelerates their path>",
      "example_companies": ["3-4 specific company names"]
    }}
  ],
  "ninety_day_plan": [
    {{"week": "1-2", "action": "<specific actionable step>"}},
    {{"week": "3-4", "action": "<specific actionable step>"}},
    {{"week": "5-8", "action": "<specific actionable step>"}},
    {{"week": "9-12", "action": "<specific actionable step>"}}
  ],
  "salary_trajectory": {{
    "current_market_range": "<e.g., $120k-$150k>",
    "in_1_year": "<projected range>",
    "at_target_role": "<projected range>"
  }},
  "biggest_mistake_to_avoid": "<the #1 career mistake people at this level make>",
  "honest_assessment": "<2-3 sentences of frank, unvarnished advice>"
}}"""

JOBS_FIT_PROMPT = """Given this career strategy and candidate profile, rank these jobs
from best to worst for long-term career growth (not just immediate match).

Candidate goal: {target_role} in {timeline}
Current level: {current_level}

Jobs to rank:
{jobs_list}

Return JSON array of job URLs with ranking and one-line reason:
[
  {{"url": "<url>", "rank": 1, "career_fit": "<why this is best for their career path>"}},
  ...
]"""


class CareerAdvisor:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._advice_cache_path = Path("career_advice.json")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str, max_tokens: int = 1200) -> dict:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        else:
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

    def get_advice(self, target_role: str = "", timeline: str = "2-3 years",
                   force_refresh: bool = False) -> Dict:
        """
        Generate or load cached career advice.
        force_refresh=True regenerates even if cache exists.
        """
        if not force_refresh and self._advice_cache_path.exists():
            try:
                cached = json.loads(self._advice_cache_path.read_text())
                logger.info("Loaded career advice from cache")
                return cached
            except Exception:
                pass

        if not target_role:
            target_role = "Senior Software Engineer / Staff Engineer"

        logger.info(f"Generating career advice for target: {target_role}")
        advice = self._llm_json(CAREER_ANALYSIS_PROMPT.format(
            resume=self.resume[:4000],
            target_role=target_role,
            timeline=timeline,
            location=self.profile.get("location", "United States"),
            remote=str(self.profile.get("remote_ok", True)),
        ), max_tokens=1500)

        advice["_generated_at"] = datetime.now(timezone.utc).isoformat()
        advice["_target_role"] = target_role
        advice["_timeline"] = timeline

        # Cache it
        self._advice_cache_path.write_text(json.dumps(advice, indent=2))
        return advice

    def rank_jobs_by_career_fit(self, jobs: List[Dict], advice: Dict) -> List[Dict]:
        """Re-rank jobs by career growth potential, not just match score."""
        if not jobs or not advice:
            return jobs
        current_level = advice.get("current_level", "Mid")
        target_role = advice.get("_target_role", "Senior Engineer")
        timeline = advice.get("_timeline", "2-3 years")

        jobs_list = "\n".join(
            f"- URL: {j.get('url', '')} | {j.get('title')} @ {j.get('company')} | Score: {j.get('score')}"
            for j in jobs[:20]
        )
        try:
            result = self._llm_json(JOBS_FIT_PROMPT.format(
                target_role=target_role,
                timeline=timeline,
                current_level=current_level,
                jobs_list=jobs_list,
            ), max_tokens=600)
            rankings = result if isinstance(result, list) else result.get("rankings", [])
            url_to_rank = {r["url"]: r for r in rankings}
            for job in jobs:
                ranking = url_to_rank.get(job.get("url", ""), {})
                job["career_rank"] = ranking.get("rank")
                job["career_fit_reason"] = ranking.get("career_fit", "")
        except Exception as e:
            logger.warning(f"Career ranking failed: {e}")
        return jobs

    @staticmethod
    def format_report(advice: dict) -> str:
        if not advice:
            return "No career advice generated yet. Run python main.py --career-advice"
        lines = [
            f"# Career Strategy Report",
            f"Generated: {advice.get('_generated_at', '')[:10]}",
            f"Target: {advice.get('_target_role', '')} in {advice.get('_timeline', '')}",
            "",
            f"## Current Level: {advice.get('current_level', '?')}",
            "",
            "## Apply For These Titles NOW",
        ]
        for t in advice.get("current_titles_to_apply", []):
            lines.append(f"  ✓ {t}")

        lines += ["", "## 90-Day Action Plan"]
        for step in advice.get("ninety_day_plan", []):
            lines.append(f"  Week {step.get('week')}: {step.get('action')}")

        lines += ["", "## Salary Trajectory"]
        sal = advice.get("salary_trajectory", {})
        lines.append(f"  Now: {sal.get('current_market_range', '?')}")
        lines.append(f"  In 1 year: {sal.get('in_1_year', '?')}")
        lines.append(f"  At target role: {sal.get('at_target_role', '?')}")

        lines += ["", f"## Honest Assessment", advice.get("honest_assessment", "")]
        lines += ["", f"## Biggest Mistake to Avoid", advice.get("biggest_mistake_to_avoid", "")]
        return "\n".join(lines)
