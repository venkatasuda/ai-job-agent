"""
Thank You Email Generator
==========================
After every interview, send a personalized thank-you email within 2 hours.
Most candidates skip this. It's a massive differentiator.

A great thank-you email:
  - References SPECIFIC things discussed in the interview (not generic)
  - Reinforces your strongest point for this role
  - Shows you did homework on the company
  - Is short: 5-7 sentences max
  - Has a clear subject line

Also generates thank-you LinkedIn messages (shorter, for in-app messaging).
"""

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

THANKYOU_EMAIL_PROMPT = """Write a personalized thank-you email after a job interview.

Candidate: {name}
Interviewer: {interviewer_name} ({interviewer_role})
Company: {company}
Role: {title}
Interview type: {interview_type}
Key topics discussed: {topics_discussed}
Your strongest point from this interview: {strongest_point}

Requirements:
- Subject line on first line: "Subject: ..."
- 5-7 sentences max
- Reference one SPECIFIC thing from the conversation (use topics_discussed)
- Reiterate enthusiasm for THIS specific company/role
- One sentence reinforcing your strongest qualification
- Professional but warm — not stiff
- End with: looking forward to next steps
- Sign as: {name}

Write only the subject and email body."""

THANKYOU_LINKEDIN_PROMPT = """Write a brief LinkedIn thank-you message after a job interview.

Interviewer: {interviewer_name}
Company: {company}
Role: {title}
One specific thing you want to reference: {specific_reference}

Requirements:
- Under 150 characters (LinkedIn message limit for connections)
- Warm, personal, not template-sounding
- Reference the specific topic
- No subject line needed"""

PANEL_THANKYOU_PROMPT = """Write individual thank-you emails for each panelist after a panel interview.

Candidate: {name}
Company: {company}
Role: {title}
Panelists and their focus areas:
{panelists}

For each panelist, write a DIFFERENT email that references what THEY specifically
asked about or discussed. Return as:

--- Email to [Name] ---
Subject: ...
[email body]

--- Email to [Name 2] ---
..."""


class ThankYouGenerator:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 400) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            return client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6, max_tokens=max_tokens,
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

    def generate_email(
        self,
        job: Dict,
        interviewer_name: str = "the interviewer",
        interviewer_role: str = "Interviewer",
        interview_type: str = "technical",
        topics_discussed: str = "",
        strongest_point: str = "",
    ) -> str:
        """Generate a personalized thank-you email for one interviewer."""
        return self._llm(THANKYOU_EMAIL_PROMPT.format(
            name=self.profile.get("name", "Candidate"),
            interviewer_name=interviewer_name,
            interviewer_role=interviewer_role,
            company=job.get("company", ""),
            title=job.get("title", ""),
            interview_type=interview_type,
            topics_discussed=topics_discussed or "the technical requirements and team culture",
            strongest_point=strongest_point or "my relevant project experience and problem-solving approach",
        ), max_tokens=350)

    def generate_linkedin_message(
        self,
        job: Dict,
        interviewer_name: str,
        specific_reference: str = "",
    ) -> str:
        """Generate a short LinkedIn thank-you message."""
        return self._llm(THANKYOU_LINKEDIN_PROMPT.format(
            interviewer_name=interviewer_name,
            company=job.get("company", ""),
            title=job.get("title", ""),
            specific_reference=specific_reference or "our conversation about the role",
        ), max_tokens=80)

    def generate_panel_emails(
        self,
        job: Dict,
        panelists: List[Dict],
    ) -> str:
        """
        Generate individual emails for each panelist.
        panelists = [{"name": "...", "role": "...", "topics": "..."}]
        """
        panelists_text = "\n".join(
            f"- {p.get('name')} ({p.get('role', '')}): discussed {p.get('topics', 'general topics')}"
            for p in panelists
        )
        return self._llm(PANEL_THANKYOU_PROMPT.format(
            name=self.profile.get("name", "Candidate"),
            company=job.get("company", ""),
            title=job.get("title", ""),
            panelists=panelists_text,
        ), max_tokens=800)

    def quick_generate(self, job: Dict) -> str:
        """Quick thank-you email with minimal info — for immediate use after interview."""
        return self.generate_email(
            job,
            interviewer_name="the team",
            interview_type="interview",
            topics_discussed="the role requirements, team dynamics, and company vision",
            strongest_point="my technical background and enthusiasm for this specific opportunity",
        )


# Allow List type hint at module level
from typing import List
