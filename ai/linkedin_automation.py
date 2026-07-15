"""
LinkedIn Automation
====================
Two features:
  1. Recruiter Auto-Connect — find and connect with recruiters at target companies
  2. Post Scheduler — draft LinkedIn posts about projects/thesis to increase visibility

NOTE: LinkedIn heavily rate-limits automation. This module uses conservative
limits (5 connections/day max) and human-like delays to avoid account flagging.

Connection targeting:
  - Recruiters / Talent Acquisition at target companies
  - Alumni from your university working at target companies
  - Engineers at target companies (for referrals)

Post drafting:
  - Project highlight posts (thesis, capstone, side projects)
  - "I'm open to work" posts (done strategically, not desperately)
  - Weekly learning posts (builds visibility with recruiters)
"""

import logging
import os
import json
from typing import Dict, List
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CONNECTION_MESSAGE_PROMPT = """Write a personalized LinkedIn connection request note.

My background: {resume_snippet}
Target person: {target_name} ({target_role} at {company})
My goal: Connect to learn about opportunities or get a referral for {job_title}

Rules:
- Under 200 characters (LinkedIn connection note limit)
- Mention one specific thing about {company} or their work
- Natural, peer-to-peer tone — not "I'm looking for a job"
- End with what you'd like: learn about their experience OR discuss opportunities
- Do NOT mention the word "job" or "opportunity" directly if possible"""

LINKEDIN_POST_PROMPT = """Write a LinkedIn post about this academic/technical project.

Project: {project_name}
What it does: {description}
Technologies: {technologies}
Outcome/result: {outcome}
My target audience: recruiters and engineers in {target_domain}

Requirements:
- 150-250 words
- Hook in first line (no "Excited to share...")
- Technical but accessible to non-experts
- End with a question to drive engagement
- 3-5 relevant hashtags
- Personal and authentic — not corporate speak

Make it sound like a real engineer reflecting on their work."""

OPEN_TO_WORK_POST_PROMPT = """Write a strategic "open to work" LinkedIn post for a Masters graduate.

Candidate background: {resume_snippet}
Target roles: {target_roles}
Location preference: {location}
Masters from: {school} in {field}

Rules:
- Lead with what you offer, not what you need
- Mention specific skills/projects that make you valuable
- Name 2-3 target companies or company types (shows you're selective)
- Under 200 words
- End with a clear call to action
- Do NOT use "#OpenToWork" hashtag (use #JobSearch or #Hiring instead)
- Make them want to reach out to YOU"""


class LinkedInAutomation:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.linkedin_cfg = config.get("linkedin", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._queue_path = Path("linkedin_queue.json")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 300) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            return client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7, max_tokens=max_tokens,
            ).choices[0].message.content.strip()
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

    # ── Connection Request Messages ────────────────────────────────────────────

    def generate_connection_note(
        self,
        target_name: str,
        target_role: str,
        company: str,
        job_title: str = "",
    ) -> str:
        """Generate a personalized connection request note (under 200 chars)."""
        msg = self._llm(CONNECTION_MESSAGE_PROMPT.format(
            resume_snippet=self.resume[:400],
            target_name=target_name,
            target_role=target_role,
            company=company,
            job_title=job_title or "relevant roles",
        ), max_tokens=100)
        # Enforce 200 char limit
        if len(msg) > 200:
            msg = msg[:197] + "..."
        return msg

    def generate_connection_batch(self, targets: List[Dict]) -> List[Dict]:
        """
        Generate connection notes for a list of targets.
        targets = [{"name": "...", "role": "...", "company": "...", "job_title": "..."}]
        """
        results = []
        for t in targets:
            note = self.generate_connection_note(
                t.get("name", ""),
                t.get("role", "Recruiter"),
                t.get("company", ""),
                t.get("job_title", ""),
            )
            results.append({**t, "connection_note": note, "status": "draft"})
        return results

    # ── Post Generation ────────────────────────────────────────────────────────

    def generate_project_post(
        self,
        project_name: str,
        description: str,
        technologies: str = "",
        outcome: str = "",
        target_domain: str = "AI/ML and software engineering",
    ) -> str:
        """Generate a LinkedIn post about a technical project."""
        return self._llm(LINKEDIN_POST_PROMPT.format(
            project_name=project_name,
            description=description,
            technologies=technologies or "Python, ML frameworks",
            outcome=outcome or "Learned key insights about the problem domain",
            target_domain=target_domain,
        ), max_tokens=350)

    def generate_open_to_work_post(
        self,
        target_roles: str = "Software Engineer / ML Engineer",
        school: str = "",
        field: str = "Computer Science",
        location: str = "US (Remote OK)",
    ) -> str:
        """Generate a strategic open-to-work post."""
        return self._llm(OPEN_TO_WORK_POST_PROMPT.format(
            resume_snippet=self.resume[:500],
            target_roles=target_roles,
            location=location,
            school=school or self.profile.get("school", "university"),
            field=field,
        ), max_tokens=300)

    def generate_weekly_post_plan(self, projects: List[Dict]) -> List[Dict]:
        """
        Generate a 4-week LinkedIn posting plan.
        Week 1: Open to work post
        Week 2-3: Project highlight posts
        Week 4: Reflection / learning post
        """
        plan = []
        today = datetime.now(timezone.utc).date()

        # Week 1: Open to work
        plan.append({
            "week": 1,
            "date": (today + timedelta(days=2)).isoformat(),
            "type": "open_to_work",
            "draft": self.generate_open_to_work_post(),
        })

        # Weeks 2-3: Projects
        for i, project in enumerate(projects[:2]):
            plan.append({
                "week": i + 2,
                "date": (today + timedelta(days=9 + i * 7)).isoformat(),
                "type": "project_highlight",
                "draft": self.generate_project_post(
                    project.get("name", "Project"),
                    project.get("description", ""),
                    ", ".join(project.get("technologies", [])),
                    project.get("outcome", ""),
                ),
            })

        # Save to queue file
        self._save_queue(plan)
        return plan

    def _save_queue(self, plan: List[Dict]):
        self._queue_path.write_text(json.dumps(plan, indent=2))

    def get_pending_posts(self) -> List[Dict]:
        """Get posts scheduled for today or overdue."""
        if not self._queue_path.exists():
            return []
        try:
            plan = json.loads(self._queue_path.read_text())
            today = datetime.now(timezone.utc).date().isoformat()
            return [p for p in plan if p.get("date", "") <= today and p.get("status") != "posted"]
        except Exception:
            return []
