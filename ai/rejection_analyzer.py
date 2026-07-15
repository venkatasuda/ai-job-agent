"""
Rejection Analyzer + Response Rate Tracker + Application Success Predictor
===========================================================================
A real job seeker tracks EVERYTHING and learns from rejections.
After 20+ applications, patterns emerge — this module finds them.

Rejection Analyzer:
  - At what stage are you getting rejected most? (no response / phone / technical)
  - Which company types reject you? (big tech vs startup vs fintech)
  - Which job titles match you worst?
  - What's missing from your profile vs jobs you're getting rejected from

Response Rate Tracker:
  - Which source (LinkedIn vs GitHub list vs ATS) gets most callbacks
  - Which keywords in cover letter improve response rate
  - Best days/times to apply (based on your own data)

Success Predictor:
  - Given a new job, predict interview callback probability
  - Based on your own historical win/loss data
"""

import logging
import os
import json
import re
from typing import Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

REJECTION_ANALYSIS_PROMPT = """You are a data-driven career coach analyzing a candidate's job application history.

Application history:
{applications}

Candidate resume snippet:
{resume}

Analyze the rejection patterns and provide insights in JSON:
{{
  "total_applications": <int>,
  "response_rate": "<e.g., 23%>",
  "stage_breakdown": {{
    "no_response": <count>,
    "phone_screen": <count>,
    "technical": <count>,
    "onsite": <count>,
    "offer": <count>,
    "rejected": <count>
  }},
  "rejection_patterns": [
    "<pattern 1: e.g., 'Getting rejected at technical round at big tech companies'>",
    "<pattern 2>",
    "<pattern 3>"
  ],
  "strongest_match_type": "<what type of company/role you do best with>",
  "weakest_match_type": "<where you consistently struggle>",
  "missing_from_profile": ["3-4 specific things missing that keep causing rejection"],
  "what_is_working": ["2-3 things that are getting you responses"],
  "action_items": [
    "<specific thing to change in the next 2 weeks>",
    "<specific thing to change>",
    "<specific thing to change>"
  ],
  "honest_assessment": "<2 sentences of frank advice based on the data>"
}}"""

SUCCESS_PREDICTION_PROMPT = """Based on this candidate's application history and success patterns,
predict the callback probability for this new job.

Candidate history (wins and losses):
{history}

New job:
Company: {company}
Title: {title}
Score: {score}
Visa Status: {visa_status}
Source: {source}
Description excerpt: {description}

Return JSON:
{{
  "callback_probability": <0-100 integer>,
  "confidence": "<Low|Medium|High>",
  "positive_signals": ["factors that increase probability"],
  "risk_factors": ["factors that decrease probability"],
  "recommendation": "<Apply|Apply with improvements|Skip>",
  "improvement_before_applying": "<one specific thing to do before submitting>"
}}"""


class RejectionAnalyzer:
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

    def _llm_json(self, prompt: str, max_tokens: int = 800) -> dict:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=max_tokens,
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
            return json.loads(match.group()) if match else {}

    def _summarize_applications(self, jobs: List[Dict]) -> str:
        """Summarize application history for LLM context."""
        applied = [j for j in jobs if j.get("applied")]
        if not applied:
            return "No applications yet."
        rows = []
        for j in applied[:50]:  # limit context
            rows.append(
                f"- {j.get('title')} @ {j.get('company')} | "
                f"Score: {j.get('score')} | Source: {j.get('source')} | "
                f"Stage: {j.get('interview_stage', 'unknown')} | "
                f"Response: {'Yes' if j.get('response_received') else 'No'} | "
                f"Visa: {j.get('visa_status', '?')}"
            )
        return "\n".join(rows)

    def analyze(self, jobs: List[Dict]) -> Dict:
        """Full rejection pattern analysis."""
        applied = [j for j in jobs if j.get("applied")]
        if len(applied) < 5:
            return {
                "error": f"Need at least 5 applications to analyze patterns. You have {len(applied)}.",
                "total_applications": len(applied),
            }

        history = self._summarize_applications(applied)
        try:
            return self._llm_json(REJECTION_ANALYSIS_PROMPT.format(
                applications=history,
                resume=self.resume[:1500],
            ), max_tokens=900)
        except Exception as e:
            logger.error(f"Rejection analysis failed: {e}")
            return self._compute_basic_stats(applied)

    def _compute_basic_stats(self, applied: List[Dict]) -> Dict:
        """Fallback: compute stats without LLM."""
        total = len(applied)
        responded = sum(1 for j in applied if j.get("response_received"))
        by_stage = {}
        for j in applied:
            stage = j.get("interview_stage", "no_response")
            by_stage[stage] = by_stage.get(stage, 0) + 1
        by_source = {}
        for j in applied:
            src = j.get("source", "unknown")
            if src not in by_source:
                by_source[src] = {"total": 0, "responses": 0}
            by_source[src]["total"] += 1
            if j.get("response_received"):
                by_source[src]["responses"] += 1
        return {
            "total_applications": total,
            "response_rate": f"{round(responded/total*100)}%" if total else "0%",
            "stage_breakdown": by_stage,
            "by_source": by_source,
        }

    def predict_success(self, job: Dict, jobs: List[Dict]) -> Dict:
        """Predict callback probability for a new job based on history."""
        applied = [j for j in jobs if j.get("applied")]
        if len(applied) < 10:
            return {
                "callback_probability": int(job.get("score") or 50),
                "confidence": "Low",
                "recommendation": "Apply" if (job.get("score") or 0) >= 65 else "Skip",
                "positive_signals": ["Score-based estimate (not enough history yet)"],
                "risk_factors": [],
                "improvement_before_applying": "Build more application history for accurate prediction.",
            }
        history = self._summarize_applications(applied[-30:])
        try:
            return self._llm_json(SUCCESS_PREDICTION_PROMPT.format(
                history=history,
                company=job.get("company", ""),
                title=job.get("title", ""),
                score=job.get("score", ""),
                visa_status=job.get("visa_status", "SILENT"),
                source=job.get("source", ""),
                description=(job.get("description") or "")[:400],
            ), max_tokens=500)
        except Exception as e:
            logger.warning(f"Success prediction failed: {e}")
            return {"callback_probability": job.get("score") or 50, "confidence": "Low"}

    def get_response_rate_by_source(self, jobs: List[Dict]) -> Dict[str, Dict]:
        """Calculate response rate per job source."""
        by_source = {}
        for j in [x for x in jobs if x.get("applied")]:
            src = j.get("source", "unknown")
            if src not in by_source:
                by_source[src] = {"applied": 0, "responded": 0, "interviews": 0}
            by_source[src]["applied"] += 1
            if j.get("response_received"):
                by_source[src]["responded"] += 1
            if j.get("interview_stage") not in ("not_applied", "applied", "rejected", "no_response"):
                by_source[src]["interviews"] += 1
        for src in by_source:
            d = by_source[src]
            d["response_rate"] = f"{round(d['responded']/d['applied']*100)}%" if d["applied"] else "0%"
        return by_source

    @staticmethod
    def format_report(analysis: dict) -> str:
        if "error" in analysis:
            return analysis["error"]
        lines = [
            f"# Application Analysis Report",
            f"Total Applications: {analysis.get('total_applications', '?')}",
            f"Response Rate: {analysis.get('response_rate', '?')}",
            "",
            "## Rejection Patterns",
        ]
        for p in analysis.get("rejection_patterns", []):
            lines.append(f"  ⚠ {p}")
        lines += ["", "## What's Working"]
        for w in analysis.get("what_is_working", []):
            lines.append(f"  ✓ {w}")
        lines += ["", "## Action Items (Do This Week)"]
        for a in analysis.get("action_items", []):
            lines.append(f"  → {a}")
        lines += ["", f"## Honest Assessment", analysis.get("honest_assessment", "")]
        return "\n".join(lines)
