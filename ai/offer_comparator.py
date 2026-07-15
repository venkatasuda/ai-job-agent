"""
Offer Comparator + Salary Negotiation Coach
============================================
When you finally get offers (and you will), don't just compare base salary.
A senior consultant compares total compensation, growth trajectory, culture,
risk, and then coaches you word-for-word on how to negotiate.

Features:
  - Total comp calculation (base + bonus + equity + benefits)
  - Side-by-side comparison table
  - Risk-adjusted value (startup equity discount, vest schedule)
  - Career growth score per offer
  - Negotiation playbook: exact scripts to say
  - Counteroffer recommendation
  - Walk-away number calculation
"""

import logging
import os
import json
import re
from typing import Dict, List
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COMPARISON_PROMPT = """You are a compensation expert and career strategist.
Compare these job offers and recommend the best one.

Candidate profile:
{resume_snippet}
Career goal: {career_goal}

Offers:
{offers_json}

Return a detailed JSON comparison:
{{
  "recommended_offer": "<company name of best offer>",
  "recommendation_reason": "<2-3 sentences why>",
  "ranking": [
    {{
      "rank": 1,
      "company": "<company>",
      "total_comp_estimate": "<e.g., $180k-$220k including equity>",
      "equity_value_4yr": "<estimated 4-year equity value>",
      "career_growth_score": <1-10>,
      "risk_score": <1-10, 10 = highest risk>,
      "pros": ["list of 3 pros"],
      "cons": ["list of 2-3 cons"],
      "negotiation_potential": "<High|Medium|Low>"
    }}
  ],
  "negotiation_playbook": {{
    "best_offer_to_negotiate": "<company>",
    "opening_line": "<exact words to say when counter-offering>",
    "counter_offer_range": "<specific $ range to ask for>",
    "leverage_points": ["things you can use as leverage"],
    "competing_offer_script": "<how to mention competing offers without being aggressive>",
    "walk_away_number": "<minimum acceptable total comp>"
  }},
  "questions_to_ask": ["list of 5 questions to ask before accepting any offer"],
  "decision_deadline_advice": "<advice on handling offer deadlines>"
}}"""

NEGOTIATION_ROLEPLAY_PROMPT = """You are playing the role of an HR recruiter at {company}.
You just made an offer of {current_offer} to a candidate.

The candidate is about to counter-offer. Coach them on exactly what to say.

Candidate's counter: They want {target_comp}.
Their leverage: {leverage}

Provide:
1. WHAT_TO_SAY: <exact script — what to say word for word on the call>
2. WHAT_NOT_TO_SAY: <common mistakes to avoid>
3. RECRUITER_LIKELY_RESPONSE: <what the recruiter will probably say back>
4. HOW_TO_RESPOND: <how to handle each likely response>
5. FINAL_OUTCOME: <realistic outcome — what they can likely get>"""


class OfferComparator:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._offers_path = Path("job_offers.json")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 1000, json_mode: bool = False) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            kwargs = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            return client.chat.completions.create(**kwargs).choices[0].message.content.strip()
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

    def add_offer(self, offer: Dict) -> None:
        """
        Save an offer to local file.
        offer = {
          "company": "Stripe",
          "title": "Senior Engineer",
          "base_salary": 160000,
          "bonus_pct": 15,
          "equity_value": 200000,  # total grant value
          "vest_years": 4,
          "signing_bonus": 20000,
          "benefits_value": 15000,  # health, 401k, etc estimated yearly
          "stage": "Series B",  # public/series-X/etc for risk assessment
          "notes": "Remote ok, great team",
          "deadline": "2024-12-01",
        }
        """
        offers = self._load_offers()
        offer["_added_at"] = datetime.now(timezone.utc).isoformat()
        offers.append(offer)
        self._offers_path.write_text(json.dumps(offers, indent=2))
        logger.info(f"Offer saved: {offer.get('company')} — {offer.get('title')}")

    def _load_offers(self) -> List[Dict]:
        if self._offers_path.exists():
            try:
                return json.loads(self._offers_path.read_text())
            except Exception:
                return []
        return []

    def _calculate_total_comp(self, offer: Dict) -> Dict:
        base = offer.get("base_salary", 0) or 0
        bonus = base * (offer.get("bonus_pct", 0) or 0) / 100
        equity_annual = (offer.get("equity_value", 0) or 0) / max(offer.get("vest_years", 4), 1)
        signing_annual = (offer.get("signing_bonus", 0) or 0) / 4  # amortize over 4 years
        benefits = offer.get("benefits_value", 0) or 0
        total = base + bonus + equity_annual + signing_annual + benefits
        return {
            "base": base,
            "bonus": bonus,
            "equity_annual": equity_annual,
            "signing_annual": signing_annual,
            "benefits": benefits,
            "total_annual": round(total),
        }

    def compare(self, career_goal: str = "Senior Engineer") -> Dict:
        """Compare all saved offers. Returns comparison dict."""
        offers = self._load_offers()
        if not offers:
            return {"error": "No offers saved yet. Use add_offer() to add offers."}

        # Calculate total comp for each
        for offer in offers:
            offer["_comp_breakdown"] = self._calculate_total_comp(offer)

        raw = self._llm(COMPARISON_PROMPT.format(
            resume_snippet=self.resume[:600],
            career_goal=career_goal,
            offers_json=json.dumps(offers, indent=2)[:3000],
        ), max_tokens=1200, json_mode=(self.provider == "openai"))

        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            result = json.loads(match.group()) if match else {"raw": raw}

        result["_offers"] = offers
        return result

    def negotiation_roleplay(self, company: str, current_offer: str,
                              target_comp: str, leverage: str = "") -> str:
        """Generate negotiation script for a specific offer."""
        return self._llm(NEGOTIATION_ROLEPLAY_PROMPT.format(
            company=company,
            current_offer=current_offer,
            target_comp=target_comp,
            leverage=leverage or "competing offers, strong skill match",
        ), max_tokens=600)

    @staticmethod
    def format_comparison(comparison: dict) -> str:
        if "error" in comparison:
            return comparison["error"]
        lines = [
            f"# Offer Comparison",
            f"Recommended: **{comparison.get('recommended_offer', '?')}**",
            f"Reason: {comparison.get('recommendation_reason', '')}",
            "",
            "## Rankings",
        ]
        for r in comparison.get("ranking", []):
            lines += [
                f"### #{r.get('rank')} — {r.get('company')}",
                f"Total Comp: {r.get('total_comp_estimate', '?')}",
                f"4-yr Equity: {r.get('equity_value_4yr', '?')}",
                f"Career Growth: {r.get('career_growth_score', '?')}/10  |  Risk: {r.get('risk_score', '?')}/10",
                f"Negotiation Potential: {r.get('negotiation_potential', '?')}",
                "Pros: " + " | ".join(r.get("pros", [])),
                "Cons: " + " | ".join(r.get("cons", [])),
                "",
            ]
        pb = comparison.get("negotiation_playbook", {})
        if pb:
            lines += [
                "## Negotiation Playbook",
                f"Best to negotiate: {pb.get('best_offer_to_negotiate', '?')}",
                f"Ask for: {pb.get('counter_offer_range', '?')}",
                f"Opening line: \"{pb.get('opening_line', '')}\"",
                f"Walk-away number: {pb.get('walk_away_number', '?')}",
            ]
        return "\n".join(lines)
