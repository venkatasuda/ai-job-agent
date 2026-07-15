"""
Upskill / Skill Gap Analyzer — from MadsLorentzen/ai-job-search's /upskill command

Analyzes the gap between the candidate's resume and jobs they're targeting.
Produces: skill gap heatmap + prioritized learning plan + quick wins + 30-day plan.
Run weekly (python main.py --upskill).
"""

import logging
import os
from typing import List, Dict
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

SKILL_EXTRACT_PROMPT = """Extract all technical skills, tools, frameworks, and methodologies from this job description.
Return ONLY a comma-separated list. Example: Python, FastAPI, PostgreSQL, Kubernetes, dbt

Job description:
{description}"""

UPSKILL_PROMPT = """You are a career development coach and senior tech educator.

## Candidate Resume
{resume}

## Market Analysis
These skills appear most in the {n_jobs} jobs they're targeting but are MISSING or WEAK in their resume:

{skill_gaps}

## Task
Create a prioritized upskill plan with these sections:

## SKILL GAP HEATMAP
[Table: Skill | Times in Job Market | Priority]

## QUICK WINS (< 1 week each)
[Skills closable quickly]

## HIGH IMPACT SKILLS (1-4 weeks each)
[Skills most likely to improve match scores]

## LONG-TERM INVESTMENTS (1-3 months each)
[Skills worth learning for sustained growth]

## RECOMMENDED 30-DAY PLAN
[Concrete weekly schedule with specific courses/resources]

Be specific — name actual courses, docs pages, or repositories."""


class UpskillAnalyzer:
    def __init__(self, config: dict, resume_text: str):
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

    def _llm(self, prompt: str, max_tokens: int = 300) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            return client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens,
            ).choices[0].message.content.strip()
        elif self.provider == "gemini":
            import google.generativeai as genai
            api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        elif self.provider == "ollama":
            import requests
            resp = requests.post("http://localhost:11434/api/generate",
                json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=90)
            return resp.json().get("response", "").strip()
        raise ValueError(f"Unknown provider: {self.provider}")

    def _extract_skills_from_job(self, job: Dict) -> List[str]:
        desc = (job.get("description") or "")[:2000]
        if not desc:
            return []
        try:
            raw = self._llm(SKILL_EXTRACT_PROMPT.format(description=desc), max_tokens=200)
            return [s.strip() for s in raw.split(",") if s.strip()]
        except Exception:
            return []

    def _extract_resume_skills(self) -> set:
        import re
        resume_lower = self.resume.lower()
        tech_skills = [
            "python", "javascript", "typescript", "java", "golang", "go", "rust", "c++", "sql",
            "react", "vue", "angular", "next.js", "fastapi", "django", "flask", "spring",
            "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
            "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka", "spark",
            "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
            "dbt", "airflow", "dagster", "prefect", "mlflow", "langchain",
            "git", "ci/cd", "rest", "graphql", "grpc", "microservices",
            "machine learning", "deep learning", "nlp", "llm", "rag",
        ]
        return {skill for skill in tech_skills if skill in resume_lower}

    def analyze(self, jobs: List[Dict]) -> str:
        if not jobs:
            return "No jobs to analyze."
        logger.info(f"Upskill analysis: extracting skills from {len(jobs)} jobs...")
        all_job_skills = []
        for job in jobs[:30]:
            all_job_skills.extend(self._extract_skills_from_job(job))
        if not all_job_skills:
            return "Could not extract skills from job descriptions."
        skill_counts = Counter(s.lower() for s in all_job_skills)
        resume_skills = self._extract_resume_skills()
        gaps = [(skill, count) for skill, count in skill_counts.most_common(30)
                if skill not in resume_skills and count >= 2]
        if not gaps:
            return "Great news — your resume covers the key skills in the job market you're targeting!"
        gap_text = "\n".join(f"- {skill}: mentioned in {count} jobs" for skill, count in gaps[:20])
        logger.info(f"Generating upskill report for {len(gaps)} skill gaps...")
        try:
            report = self._llm(UPSKILL_PROMPT.format(
                resume=self.resume[:2500], n_jobs=len(jobs), skill_gaps=gap_text,
            ), max_tokens=1500)
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            return f"# Upskill Report\n_Generated: {timestamp}_\n\n{report}"
        except Exception as e:
            return f"[Upskill report failed: {e}]\n\nTop skill gaps:\n{gap_text}"

    def save_report(self, report: str, path: str = "upskill_report.md"):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info(f"Upskill report saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save upskill report: {e}")
