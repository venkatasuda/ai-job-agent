"""
Recruiter Message Responder
============================
When recruiters reach out on LinkedIn, most candidates either:
  A) Ignore it (big mistake)
  B) Reply "Yes I'm interested!" with no context (weak)

A consultant responds strategically:
  - Warm but not desperate
  - Asks smart qualifying questions
  - Gets the salary range FIRST before wasting time
  - Signals they're selective (creates scarcity)

Generates responses for:
  - Cold recruiter outreach ("Are you open to opportunities?")
  - Specific role pitch ("We have a {title} role at {company}")
  - Recruiters from target companies (prioritized)
  - Spam/irrelevant recruiter messages (polite decline)
"""

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

RECRUITER_RESPONSE_PROMPT = """You are a senior software engineer who is selectively exploring opportunities.
A recruiter just messaged you. Write the perfect response.

Your profile:
{resume_snippet}
Career goal: {career_goal}

Recruiter's message:
{recruiter_message}

Company/Role (if mentioned): {company} / {role}

Response strategy: {strategy}

Rules:
- Express interest but don't sound desperate
- Ask 1-2 qualifying questions (salary range, remote policy, tech stack)
- Keep it under 100 words
- Professional but human — not template-sounding
- If it's a target company (high interest): show genuine enthusiasm for THAT company
- If it's irrelevant: politely decline and briefly mention what you're actually looking for

Write only the response message."""

QUALIFYING_QUESTIONS = [
    "What's the compensation range for this role?",
    "Is this role remote-friendly or office-based?",
    "What's the tech stack / primary programming languages?",
    "Is visa sponsorship available?",
    "What stage is the company at?",
    "What does the interview process look like?",
]

STRATEGIES = {
    "target_company": "Express genuine enthusiasm for this specific company. Show you know something about them. Ask about tech stack and team.",
    "interesting": "Show moderate interest. Ask about salary range and remote policy first.",
    "unknown": "Be neutral but professional. Ask qualifying questions to determine fit.",
    "irrelevant": "Politely decline. Briefly mention what you're actually looking for so they can keep you in mind for better matches.",
    "spam": "Very short decline. Don't encourage further contact.",
}


class RecruiterResponder:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        # Load target companies from config
        self.target_companies = set()
        for target in config.get("sources", {}).get("ats_companies", {}).get("targets", []):
            if target:
                self.target_companies.add(target[0].lower())

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 200) -> str:
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

    def _detect_strategy(self, company: str, message: str) -> str:
        """Determine response strategy based on company and message content."""
        company_lower = company.lower()
        msg_lower = message.lower()

        if company_lower in self.target_companies:
            return "target_company"

        spam_signals = ["urgent", "immediate", "100% remote guaranteed", "6 figures", "dream job"]
        if any(s in msg_lower for s in spam_signals) and len(message) < 100:
            return "spam"

        irrelevant_signals = ["sales", "account executive", "business development", "recruiting"]
        if any(s in msg_lower for s in irrelevant_signals):
            return "irrelevant"

        if company and len(message) > 100:
            return "interesting"

        return "unknown"

    def generate_response(
        self,
        recruiter_message: str,
        company: str = "",
        role: str = "",
        career_goal: str = "Senior Software / ML / Data Engineer role",
        strategy: str = None,
    ) -> Dict[str, str]:
        """
        Generate recruiter response.
        Returns dict with 'response', 'strategy', 'qualifying_questions'.
        """
        if strategy is None:
            strategy = self._detect_strategy(company, recruiter_message)

        strategy_desc = STRATEGIES.get(strategy, STRATEGIES["unknown"])

        response = self._llm(RECRUITER_RESPONSE_PROMPT.format(
            resume_snippet=self.resume[:500],
            career_goal=career_goal,
            recruiter_message=recruiter_message[:500],
            company=company or "company mentioned",
            role=role or "role mentioned",
            strategy=strategy_desc,
        ), max_tokens=200)

        # Pick relevant qualifying questions based on strategy
        if strategy in ("target_company", "interesting"):
            questions = QUALIFYING_QUESTIONS[:3]
        elif strategy == "unknown":
            questions = QUALIFYING_QUESTIONS[:2]
        else:
            questions = []

        return {
            "response": response,
            "strategy": strategy,
            "qualifying_questions_used": questions,
        }

    def batch_generate(self, messages: List[Dict]) -> List[Dict]:
        """
        Process multiple recruiter messages.
        messages = [{"message": "...", "company": "...", "role": "..."}]
        """
        results = []
        for msg in messages:
            result = self.generate_response(
                recruiter_message=msg.get("message", ""),
                company=msg.get("company", ""),
                role=msg.get("role", ""),
            )
            result["original_message"] = msg
            results.append(result)
        return results


from typing import List
