"""
New Grad Salary Intelligence
==============================
Masters graduates often undersell themselves OR overshoot.
Both get you rejected. This module gives you:

  1. Market rate for your specific role + location + degree
  2. Masters premium (typically +$10-20k over BS)
  3. How to answer "What are your salary expectations?" (exact script)
  4. When to negotiate vs when to just accept
  5. Total comp breakdown: base + bonus + equity + benefits
  6. Company-specific pay data (levels.fyi data patterns)
"""

import logging
import os
import re
import json
from typing import Dict, List

logger = logging.getLogger(__name__)

SALARY_RESEARCH_PROMPT = """You are a compensation expert specializing in new graduate salaries in tech.

Candidate profile:
- Degree: Masters in {field} from {school_tier} university
- Target role: {title}
- Location: {location}
- Years of experience: {experience} (including internships)
- Key skills: {skills}

Provide detailed salary intelligence in JSON:
{{
  "base_salary_range": {{
    "low": <int>,
    "median": <int>,
    "high": <int>,
    "currency": "USD"
  }},
  "total_comp_range": {{
    "low": <int>,
    "median": <int>,
    "high": <int>
  }},
  "masters_premium": "<e.g., +$10-15k over BS in same role>",
  "by_company_tier": {{
    "faang_equivalent": "<range>",
    "top_startup": "<range>",
    "mid_size_tech": "<range>",
    "enterprise": "<range>"
  }},
  "equity_typical": "<e.g., $50k-$200k over 4 years>",
  "signing_bonus_typical": "<range>",
  "negotiation_room": "<e.g., 10-15% above initial offer>",
  "answer_to_salary_question": "<exact script for 'what are your expectations?'>",
  "red_flags": ["salary red flags to watch for"],
  "pro_tips": ["3 specific tips for negotiating as a new grad"]
}}"""

EXPECTATION_ANSWER_PROMPT = """Coach me on answering the salary expectations question.

Context:
- Role: {title} at {company}
- My target: {target_salary}
- Company stage: {company_stage}
- My leverage: {leverage}

Give me:
1. WHAT_TO_SAY: exact script (2-3 sentences)
2. IF_THEY_PUSH_BACK: what to say if they say "we need a number"
3. WHEN_TO_SHARE_FIRST: situation where I should name first
4. ANCHOR_NUMBER: the specific number to say (slightly above target)"""


class NewGradSalary:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache: Dict[str, Dict] = {}

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

    def _extract_skills(self) -> str:
        """Extract key skills from resume."""
        skill_keywords = re.findall(
            r'\b(Python|Java|JavaScript|TypeScript|C\+\+|Go|Rust|SQL|'
            r'PyTorch|TensorFlow|Kubernetes|Docker|AWS|GCP|Azure|'
            r'React|Node\.js|FastAPI|Django|Spark|Kafka|Redis|'
            r'Machine Learning|Deep Learning|NLP|Computer Vision|'
            r'Data Engineering|MLOps|DevOps|Full Stack)\b',
            self.resume, re.IGNORECASE
        )
        return ", ".join(list(dict.fromkeys(skill_keywords))[:10])

    def get_market_rate(
        self,
        title: str,
        location: str = "United States",
        field: str = "Computer Science",
        school_tier: str = "Top-50",
        experience: str = "0-1 years (internships only)",
    ) -> Dict:
        """Get market rate for a specific role."""
        cache_key = f"{title}_{location}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._llm_json(SALARY_RESEARCH_PROMPT.format(
            field=field,
            school_tier=school_tier,
            title=title,
            location=location,
            experience=experience,
            skills=self._extract_skills(),
        ), max_tokens=800)

        self._cache[cache_key] = result
        return result

    def coach_salary_answer(
        self,
        title: str,
        company: str,
        target_salary: int,
        company_stage: str = "Unknown",
        leverage: str = "Masters degree, relevant internships",
    ) -> str:
        """Get coached script for answering salary expectations question."""
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": EXPECTATION_ANSWER_PROMPT.format(
                    title=title, company=company,
                    target_salary=f"${target_salary:,}",
                    company_stage=company_stage,
                    leverage=leverage,
                )}],
                temperature=0.4, max_tokens=400,
            )
            return resp.choices[0].message.content.strip()
        return f"Target ${target_salary:,}. Say: 'Based on my research and the Masters premium for this role in {company_stage} companies, I'm targeting ${target_salary:,} in base salary, though I'm open to discussing the full compensation package.'"

    def enrich_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Add new_grad_salary_data to jobs missing salary info."""
        for job in jobs:
            if job.get("salary_min") or job.get("new_grad_salary_data"):
                continue
            if (job.get("score") or 0) < 65:
                continue
            try:
                data = self.get_market_rate(
                    title=job.get("title", ""),
                    location=job.get("location", "United States"),
                )
                job["new_grad_salary_data"] = data
                # Set estimated salary from research
                base = data.get("base_salary_range", {})
                if base.get("median"):
                    job["salary_estimate"] = f"~${base['median']:,} (est. for new grad)"
            except Exception as e:
                logger.warning(f"New grad salary research failed for {job.get('title')}: {e}")
        return jobs

    @staticmethod
    def format_report(data: dict) -> str:
        if not data:
            return "No salary data."
        base = data.get("base_salary_range", {})
        total = data.get("total_comp_range", {})
        lines = [
            f"Base: ${base.get('low',0):,} – ${base.get('high',0):,} (median: ${base.get('median',0):,})",
            f"Total Comp: ${total.get('low',0):,} – ${total.get('high',0):,}",
            f"Masters Premium: {data.get('masters_premium', '?')}",
            f"Equity: {data.get('equity_typical', '?')}",
            f"Signing Bonus: {data.get('signing_bonus_typical', '?')}",
            f"Negotiation Room: {data.get('negotiation_room', '?')}",
            "",
            "By Company Tier:",
        ]
        for tier, range_val in data.get("by_company_tier", {}).items():
            lines.append(f"  {tier}: {range_val}")
        lines += ["", "How to answer salary question:"]
        lines.append(f'  "{data.get("answer_to_salary_question", "")}"')
        return "\n".join(lines)
