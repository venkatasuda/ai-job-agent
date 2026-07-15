"""
Reference Manager
==================
Manage your professional references like a real job consultant would.

Features:
  - Store reference contacts (name, role, relationship, contact)
  - Track which references are being used for which applications
  - Generate reference request emails (timing matters — ask before they get called)
  - Follow-up tracker (remind references when they haven't responded)
  - Prepare reference talking points (what to tell them to emphasize)
  - Thank you notes to references after interviews/offers

Strategy:
  - Always brief your references on the specific role
  - Give them the JD + 3 talking points
  - Use different references for different types of roles
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REFERENCE_REQUEST_PROMPT = """Write a professional reference request email.

Reference: {ref_name} ({ref_title} at {ref_company})
Relationship: {relationship}
Job: {job_title} at {job_company}
Key talking points they should emphasize: {talking_points}

Write a warm, specific email that:
1. Reminds them of our work together briefly
2. Describes the specific role
3. Provides 2-3 specific talking points (skills/projects to highlight)
4. Gives them an easy out if they're too busy
5. Mentions approximate timing

Subject line + Email body. Keep it under 200 words."""

REFERENCE_BRIEF_PROMPT = """Write a reference briefing document for {ref_name}.

Job: {job_title} at {job_company}
JD summary: {jd_summary}
Candidate's relevant highlights: {highlights}

Create a 1-page briefing they can glance at before the call:
- What this company does (1 sentence)
- Why I'm a great fit for this role (3 bullets)
- Specific projects/achievements to mention (with numbers)
- Skills to emphasize
- Anything to NOT mention

Keep it brief and practical."""


class ReferenceManager:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._refs_path = Path("references.json")
        self._refs = self._load_refs()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 500) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=max_tokens,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        except Exception as e:
            logger.warning(f"Reference manager LLM error: {e}")
        return ""

    def _load_refs(self) -> dict:
        if self._refs_path.exists():
            try:
                return json.loads(self._refs_path.read_text())
            except Exception:
                pass
        return {"references": {}, "usage_log": []}

    def _save_refs(self):
        self._refs_path.write_text(json.dumps(self._refs, indent=2))

    def add_reference(self, name: str, title: str, company: str,
                      email: str = "", phone: str = "",
                      linkedin: str = "", relationship: str = "",
                      strengths: List[str] = None) -> str:
        """Add a professional reference."""
        ref_id = re.sub(r"[^a-z0-9]", "_", name.lower())
        self._refs["references"][ref_id] = {
            "name": name,
            "title": title,
            "company": company,
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "relationship": relationship,
            "strengths": strengths or [],
            "added_at": datetime.now(timezone.utc).isoformat(),
            "times_used": 0,
            "last_used": None,
            "status": "available",  # available | active | resting
        }
        self._save_refs()
        logger.info(f"Reference added: {name}")
        return ref_id

    def generate_request_email(self, ref_id: str, job: Dict,
                               talking_points: List[str] = None) -> str:
        ref = self._refs["references"].get(ref_id)
        if not ref:
            return "Reference not found"
        points = talking_points or ref.get("strengths", [])
        email = self._llm(REFERENCE_REQUEST_PROMPT.format(
            ref_name=ref["name"], ref_title=ref["title"],
            ref_company=ref["company"], relationship=ref.get("relationship", "colleague"),
            job_title=job.get("title", "Software Engineer"),
            job_company=job.get("company", "Company"),
            talking_points=", ".join(points[:3]) or "technical skills and teamwork",
        ))
        return email

    def generate_briefing(self, ref_id: str, job: Dict,
                          candidate_highlights: List[str] = None) -> str:
        ref = self._refs["references"].get(ref_id)
        if not ref:
            return "Reference not found"
        jd_summary = (job.get("description") or "")[:400]
        highlights = candidate_highlights or []
        brief = self._llm(REFERENCE_BRIEF_PROMPT.format(
            ref_name=ref["name"],
            job_title=job.get("title", "Software Engineer"),
            job_company=job.get("company", "Company"),
            jd_summary=jd_summary,
            highlights="; ".join(highlights) if highlights else "Strong technical background",
        ), max_tokens=600)
        return brief

    def mark_used(self, ref_id: str, job_id: str, company: str):
        ref = self._refs["references"].get(ref_id)
        if ref:
            ref["times_used"] = ref.get("times_used", 0) + 1
            ref["last_used"] = datetime.now(timezone.utc).isoformat()
            ref["status"] = "active"
        self._refs.setdefault("usage_log", []).append({
            "ref_id": ref_id,
            "job_id": job_id,
            "company": company,
            "date": datetime.now(timezone.utc).isoformat(),
        })
        self._save_refs()

    def get_available_refs(self, limit: int = 3) -> List[Dict]:
        """Return references sorted by least recently used."""
        refs = list(self._refs["references"].values())
        available = [r for r in refs if r.get("status") != "unavailable"]
        return sorted(available, key=lambda r: r.get("last_used") or "")[:limit]

    def check_overuse(self) -> List[str]:
        """Flag references used more than 3x in 30 days."""
        flagged = []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for ref_id, ref in self._refs["references"].items():
            recent_uses = sum(
                1 for log in self._refs.get("usage_log", [])
                if log.get("ref_id") == ref_id and log.get("date", "") > cutoff
            )
            if recent_uses >= 3:
                flagged.append(f"{ref['name']} (used {recent_uses}x in 30 days — give them a break)")
        return flagged

    def get_thank_you_email(self, ref_id: str, outcome: str = "interview") -> str:
        ref = self._refs["references"].get(ref_id)
        if not ref:
            return ""
        msg = (
            f"Subject: Thank you for being a reference!\n\n"
            f"Hi {ref['name'].split()[0]},\n\n"
            f"I wanted to reach out to thank you for serving as a reference for me. "
        )
        if outcome == "offer":
            msg += (
                f"I'm thrilled to share that I received an offer! "
                f"Your support meant a great deal to me. "
                f"I'll keep you posted as things develop.\n\n"
            )
        elif outcome == "interview":
            msg += (
                f"I have an interview scheduled and wanted to make sure "
                f"you had all the information you need. "
                f"I really appreciate your time and support.\n\n"
            )
        else:
            msg += (
                f"While this particular opportunity didn't work out, "
                f"your support means a lot. "
                f"I'll keep you updated as my search continues.\n\n"
            )
        msg += f"Thank you again!\nBest,\n[Your Name]"
        return msg

    def list_references(self) -> List[Dict]:
        return list(self._refs["references"].values())
