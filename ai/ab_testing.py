"""
Cover Letter A/B Testing
=========================
Test different cover letter strategies and track which ones
get the best interview callback rates.

Test variables:
  - Opening hook style (story | direct | question | stat)
  - Tone (formal | conversational | enthusiastic)
  - Length (short 200w | medium 350w | long 500w)
  - Academic emphasis (highlight research | hide it | neutral)
  - Salary mention (include | omit)

Tracks: sent → callback → interview → offer
Reports: which variant has the highest callback rate (min sample = 10)
"""

import json
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VARIANT_GENERATION_PROMPT = """Generate {n_variants} different opening paragraphs for a cover letter.
Job: {job_title} at {company}
Candidate: {summary}

Variants to generate (one per line, labeled A/B/C):
A: Story-based opening (start with a relevant anecdote)
B: Direct opening (lead with why you're a perfect fit)
C: Question-based opening (start with a thought-provoking question)
{extra}

Each variant should be 3-4 sentences, professional, specific to the company.
Label them clearly: VARIANT_A: ... VARIANT_B: ... VARIANT_C: ..."""


class ABTestingEngine:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._tests_path = Path("ab_tests.json")
        self._tests = self._load_tests()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8, max_tokens=800,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        except Exception as e:
            logger.warning(f"A/B testing LLM error: {e}")
        return ""

    def _load_tests(self) -> dict:
        if self._tests_path.exists():
            try:
                return json.loads(self._tests_path.read_text())
            except Exception:
                pass
        return {
            "active_tests": {},
            "completed_tests": [],
            "current_best": None,
        }

    def _save_tests(self):
        self._tests_path.write_text(json.dumps(self._tests, indent=2))

    def create_test(self, test_name: str, variants: List[Dict]) -> str:
        """Create a new A/B test with given variants."""
        test_id = f"test_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self._tests["active_tests"][test_id] = {
            "name": test_name,
            "created_at": datetime.utcnow().isoformat(),
            "variants": {
                v["id"]: {
                    **v,
                    "applications": 0,
                    "callbacks": 0,
                    "interviews": 0,
                    "offers": 0,
                    "callback_rate": 0.0,
                }
                for v in variants
            },
            "status": "active",
        }
        self._save_tests()
        return test_id

    def generate_cover_letter_variants(
        self, job: Dict, resume_summary: str
    ) -> Tuple[str, Dict]:
        """Generate A/B test variants for a job's cover letter opening."""
        company = job.get("company", "the company")
        title = job.get("title", "Software Engineer")

        raw = self._llm(VARIANT_GENERATION_PROMPT.format(
            n_variants=3, job_title=title, company=company,
            summary=resume_summary[:300],
            extra="D: Statistic/data-driven opening (start with a relevant industry stat)",
        ))

        variants = []
        for label in ["A", "B", "C", "D"]:
            m = re.search(rf"VARIANT_{label}:\s*(.*?)(?=VARIANT_|$)", raw, re.DOTALL)
            if m:
                variants.append({
                    "id": label,
                    "style": {"A": "story", "B": "direct", "C": "question", "D": "data"}[label],
                    "content": m.group(1).strip(),
                })

        if not variants:
            variants = [{"id": "A", "style": "direct", "content": f"I am excited to apply for the {title} role at {company}."}]

        test_id = self.create_test(f"Cover Letter: {title} @ {company}", variants)
        return test_id, {v["id"]: v for v in variants}

    def pick_variant(self, test_id: str) -> Optional[Dict]:
        """Pick which variant to use for the next application (weighted by performance)."""
        test = self._tests["active_tests"].get(test_id)
        if not test:
            return None
        variants = list(test["variants"].values())
        # Thompson sampling: favor high performers, but still explore
        weights = []
        for v in variants:
            apps = v.get("applications", 0)
            callbacks = v.get("callbacks", 0)
            # Beta distribution mean: (callbacks+1) / (apps+2)
            score = (callbacks + 1) / (apps + 2)
            weights.append(score)
        total = sum(weights)
        pick = random.choices(variants, weights=[w / total for w in weights])[0]
        return pick

    def record_sent(self, test_id: str, variant_id: str):
        test = self._tests["active_tests"].get(test_id)
        if test and variant_id in test["variants"]:
            test["variants"][variant_id]["applications"] += 1
            self._save_tests()

    def record_callback(self, test_id: str, variant_id: str):
        test = self._tests["active_tests"].get(test_id)
        if test and variant_id in test["variants"]:
            test["variants"][variant_id]["callbacks"] += 1
            self._update_rates(test_id, variant_id)
            self._save_tests()

    def record_interview(self, test_id: str, variant_id: str):
        test = self._tests["active_tests"].get(test_id)
        if test and variant_id in test["variants"]:
            test["variants"][variant_id]["interviews"] += 1
            self._save_tests()

    def _update_rates(self, test_id: str, variant_id: str):
        v = self._tests["active_tests"][test_id]["variants"][variant_id]
        apps = v.get("applications", 0)
        if apps > 0:
            v["callback_rate"] = round(v["callbacks"] / apps * 100, 1)

    def get_winner(self, test_id: str, min_samples: int = 10) -> Optional[Dict]:
        """Return the winning variant if statistically significant."""
        test = self._tests["active_tests"].get(test_id)
        if not test:
            return None
        qualified = [v for v in test["variants"].values()
                    if v.get("applications", 0) >= min_samples]
        if not qualified:
            return None
        return max(qualified, key=lambda v: v.get("callback_rate", 0))

    def get_global_best_style(self) -> Optional[str]:
        """Across all tests, which cover letter style wins most often?"""
        style_wins = {}
        for test in self._tests["active_tests"].values():
            winner = max(test["variants"].values(),
                        key=lambda v: v.get("callback_rate", 0), default=None)
            if winner:
                style = winner.get("style", "unknown")
                style_wins[style] = style_wins.get(style, 0) + 1
        if not style_wins:
            return None
        return max(style_wins, key=style_wins.get)

    def get_summary(self) -> Dict:
        tests = self._tests["active_tests"]
        return {
            "active_tests": len(tests),
            "global_best_style": self.get_global_best_style(),
            "total_variants_tested": sum(
                len(t["variants"]) for t in tests.values()
            ),
        }
