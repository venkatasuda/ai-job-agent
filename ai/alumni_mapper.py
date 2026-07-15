"""
Alumni Network Mapper
======================
Maps your university alumni at target companies to facilitate warm outreach.

Strategy: A warm referral from a fellow alum increases interview chances by 50%.
The job agent finds alumni at target companies and helps draft messages.

Sources:
  - LinkedIn alumni search (via browser/Chrome extension)
  - University alumni directory hints (via DuckDuckGo)
  - GitHub profiles with university mentions

Output:
  - List of alumni at target companies
  - Personalized outreach messages (emphasize shared school)
  - Track response rates from alumni vs. cold outreach
"""

import json
import logging
import os
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ALUMNI_OUTREACH_PROMPT = """Write a warm alumni outreach LinkedIn message (under 200 chars for DM).

Sender (you): {your_name}, {your_degree} from {school} ({grad_year})
Recipient: {alumni_name}, {alumni_title} at {company}
Connection: Both attended {school}
Purpose: Asking for a referral / informational chat about {company}

Write 3 versions:
VERSION_A (casual): ...
VERSION_B (formal): ...
VERSION_C (direct-ask): ...

Keep each under 200 characters. Mention the school in each."""

REFERRAL_REQUEST_PROMPT = """Write a referral request email to a university alumnus.

Alumni: {alumni_name} ({alumni_title} at {company})
Your name: {your_name}, Masters in {field} from {school}
Job role: {job_title} at {company}
Job URL: {job_url}
Shared experience: Both {school} alumni

Write a polite referral request email:
- Mention the shared school connection
- Express genuine interest in the company
- Ask if they'd be willing to refer or chat for 15 minutes
- Keep it under 150 words
- Do NOT be entitled about the referral"""


class AlumniMapper:
    def __init__(self, config: dict):
        self.cfg = config
        self.ai_cfg = config.get("ai", {})
        self.provider = self.ai_cfg.get("provider", "openai")
        self.model = self.ai_cfg.get("model", "gpt-4o-mini")
        self._client = None
        self.profile = config.get("profile", {})
        self.new_grad_cfg = config.get("new_grad", {})
        self.school = self.new_grad_cfg.get("school", "")
        self.grad_year = self.new_grad_cfg.get("graduation_year", 2024)
        self._alumni_path = Path("alumni_contacts.json")
        self._alumni = self._load_alumni()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.ai_cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 500) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6, max_tokens=max_tokens,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.ai_cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        except Exception as e:
            logger.warning(f"Alumni mapper LLM error: {e}")
        return ""

    def _load_alumni(self) -> dict:
        if self._alumni_path.exists():
            try:
                return json.loads(self._alumni_path.read_text())
            except Exception:
                pass
        return {"contacts": {}, "outreach_log": []}

    def _save_alumni(self):
        self._alumni_path.write_text(json.dumps(self._alumni, indent=2))

    def add_alumni(self, name: str, title: str, company: str,
                   linkedin_url: str = "", email: str = "",
                   graduation_year: Optional[int] = None,
                   department: str = "") -> str:
        alumni_id = re.sub(r"[^a-z0-9]", "_", name.lower())
        self._alumni["contacts"][alumni_id] = {
            "name": name, "title": title, "company": company,
            "linkedin_url": linkedin_url, "email": email,
            "graduation_year": graduation_year,
            "department": department,
            "school": self.school,
            "added_at": datetime.utcnow().isoformat(),
            "outreach_sent": False,
            "responded": False,
            "status": "not_contacted",
        }
        self._save_alumni()
        return alumni_id

    def search_alumni_linkedin_url(self, company: str) -> str:
        """Generate LinkedIn alumni search URL for a specific company."""
        school_name = quote_plus(self.school)
        company_name = quote_plus(company)
        return (
            f"https://www.linkedin.com/search/results/people/"
            f"?keywords={school_name}&currentCompany={company_name}"
            f"&network=%5B%22F%22%2C%22S%22%5D"
        )

    def discover_via_search(self, company: str) -> List[Dict]:
        """Search for alumni at a company using public sources."""
        if not self.school:
            return []
        alumni = []
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": f'"{self.school}" "{company}" software engineer linkedin',
                    "format": "json", "no_html": 1,
                },
                headers={"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"},
                timeout=8,
            )
            data = resp.json()
            for topic in data.get("RelatedTopics", [])[:5]:
                text = topic.get("Text", "")
                url = topic.get("FirstURL", "")
                if self.school.lower() in text.lower() and company.lower() in text.lower():
                    # Try to parse name from result
                    name_match = re.match(r"([A-Z][a-z]+ [A-Z][a-z]+)", text)
                    if name_match:
                        alumni.append({
                            "name": name_match.group(1),
                            "company": company,
                            "linkedin_url": url,
                            "title": "Software Engineer",
                            "source": "search",
                        })
        except Exception:
            pass
        return alumni

    def generate_outreach_messages(self, alumni_id: str, job: Dict) -> Dict:
        """Generate personalized outreach messages for an alum."""
        alumni = self._alumni["contacts"].get(alumni_id)
        if not alumni:
            return {}
        raw = self._llm(ALUMNI_OUTREACH_PROMPT.format(
            your_name=self.profile.get("name", "Your Name"),
            your_degree=self.new_grad_cfg.get("degree", "Masters"),
            school=self.school or "our university",
            grad_year=self.grad_year,
            alumni_name=alumni["name"],
            alumni_title=alumni.get("title", "Software Engineer"),
            company=alumni["company"],
        ))
        messages = {}
        for label in ["A", "B", "C"]:
            m = re.search(rf"VERSION_{label}[:\s]*(.*?)(?=VERSION_|$)", raw, re.DOTALL)
            if m:
                messages[f"version_{label}"] = m.group(1).strip()[:300]
        return messages

    def generate_referral_email(self, alumni_id: str, job: Dict) -> str:
        alumni = self._alumni["contacts"].get(alumni_id)
        if not alumni:
            return ""
        return self._llm(REFERRAL_REQUEST_PROMPT.format(
            alumni_name=alumni["name"], alumni_title=alumni.get("title"),
            company=alumni["company"],
            your_name=self.profile.get("name", "Your Name"),
            field=self.new_grad_cfg.get("field", "Computer Science"),
            school=self.school or "our university",
            job_title=job.get("title", "Software Engineer"),
            job_url=job.get("job_url", ""),
        ), max_tokens=400)

    def record_outreach(self, alumni_id: str, method: str):
        alumni = self._alumni["contacts"].get(alumni_id)
        if alumni:
            alumni["outreach_sent"] = True
            alumni["status"] = "contacted"
            alumni["contacted_at"] = datetime.utcnow().isoformat()
        self._alumni.setdefault("outreach_log", []).append({
            "alumni_id": alumni_id, "method": method,
            "date": datetime.utcnow().isoformat(), "responded": False,
        })
        self._save_alumni()

    def record_response(self, alumni_id: str, outcome: str = "positive"):
        alumni = self._alumni["contacts"].get(alumni_id)
        if alumni:
            alumni["responded"] = True
            alumni["status"] = outcome
        self._save_alumni()

    def get_untapped_alumni(self, company: str) -> List[Dict]:
        return [
            a for a in self._alumni["contacts"].values()
            if a.get("company") == company and not a.get("outreach_sent")
        ]

    def get_stats(self) -> Dict:
        total = len(self._alumni["contacts"])
        contacted = sum(1 for a in self._alumni["contacts"].values() if a.get("outreach_sent"))
        responded = sum(1 for a in self._alumni["contacts"].values() if a.get("responded"))
        return {
            "total_alumni": total,
            "contacted": contacted,
            "responded": responded,
            "response_rate": round(responded / contacted * 100, 1) if contacted else 0,
        }


def quote_plus(s: str) -> str:
    from urllib.parse import quote_plus as qp
    return qp(s)
