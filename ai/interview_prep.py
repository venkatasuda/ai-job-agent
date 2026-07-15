"""
Interview Prep Generator + STAR Story Bank
==========================================
From MadsLorentzen/ai-job-search + career-ops interview prep features.

Generates per-job: behavioral questions, technical questions, STAR stories,
company talking points, questions to ask, red flags.
Maintains a cumulative STAR story bank across all evaluations.
"""

import json
import logging
import os
from typing import Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

INTERVIEW_PROMPT = """You are a senior interview coach preparing a candidate for a specific job interview.

## Candidate Resume
{resume}

## Job Posting
Title: {title}
Company: {company}
Description:
{description}

Generate a complete interview preparation pack:

### 1. LIKELY BEHAVIORAL QUESTIONS (5 questions)
Questions this company is very likely to ask. For each, suggest which STAR story to use.

### 2. LIKELY TECHNICAL QUESTIONS (5 questions)
Specific technical questions based on the job requirements.

### 3. CANDIDATE'S TOP 3 STAR STORIES
Extract from the resume 3 powerful stories in STAR+Reflection format:
- Situation / Task / Action / Result / Reflection (how it applies to this role)

### 4. COMPANY-SPECIFIC TALKING POINTS
3 specific things to mention that show you understand this company's challenges.

### 5. QUESTIONS TO ASK
5 thoughtful questions to ask the interviewer.

### 6. RED FLAGS TO WATCH
2-3 things in the job description that could indicate challenges."""

STORY_BANK_EXTRACT_PROMPT = """From this interview prep, extract ONLY the STAR stories as JSON array.

Interview Prep:
{interview_prep}

Return JSON array:
[
  {{
    "title": "short story title (5 words max)",
    "situation": "...",
    "task": "...",
    "action": "...",
    "result": "...",
    "reflection": "...",
    "applicable_questions": ["list of behavioral question types this answers"]
  }}
]"""


class InterviewPrep:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self.story_bank_path = Path("star_story_bank.json")
        self._client = None
        self._story_bank = self._load_story_bank()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 1200, json_mode: bool = False) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            kwargs = dict(model=self.model, messages=[{"role": "user", "content": prompt}],
                         temperature=0.5, max_tokens=max_tokens)
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

    def _load_story_bank(self) -> List[Dict]:
        if self.story_bank_path.exists():
            try:
                with open(self.story_bank_path) as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_story_bank(self):
        with open(self.story_bank_path, "w") as f:
            json.dump(self._story_bank, f, indent=2)

    def _update_story_bank(self, interview_prep: str):
        try:
            raw = self._llm(STORY_BANK_EXTRACT_PROMPT.format(
                interview_prep=interview_prep[:2000]), max_tokens=800,
                json_mode=(self.provider == "openai"))
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            parsed = json.loads(raw)
            stories = list(parsed.values())[0] if isinstance(parsed, dict) else parsed
            existing_titles = {s.get("title", "").lower() for s in self._story_bank}
            added = sum(1 for s in stories if s.get("title", "").lower() not in existing_titles
                        and not self._story_bank.append(s))
            if added:
                self._save_story_bank()
                logger.info(f"Added {added} stories to STAR bank ({len(self._story_bank)} total)")
        except Exception as e:
            logger.warning(f"Could not update story bank: {e}")

    def generate_for_job(self, job: Dict) -> str:
        try:
            prep = self._llm(INTERVIEW_PROMPT.format(
                resume=self.resume[:3000], title=job.get("title", ""),
                company=job.get("company", ""),
                description=(job.get("description") or "")[:2000],
            ), max_tokens=1500)
            self._update_story_bank(prep)
            return prep
        except Exception as e:
            logger.error(f"Interview prep failed for {job.get('title')}: {e}")
            return f"[Interview prep unavailable: {e}]"

    def get_story_bank_summary(self) -> str:
        if not self._story_bank:
            return "Story bank is empty. Apply to more jobs to build it up."
        lines = [f"# STAR Story Bank ({len(self._story_bank)} stories)\n"]
        for i, story in enumerate(self._story_bank, 1):
            applicable = ", ".join(story.get("applicable_questions", [])[:3])
            lines.append(f"**{i}. {story.get('title', f'Story {i}')}**")
            lines.append(f"  Result: {story.get('result', '')}")
            lines.append(f"  Answers: {applicable}\n")
        return "\n".join(lines)

    def enrich_jobs(self, jobs: list, threshold: int = 80) -> list:
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("interview_prep"):
                logger.info(f"Generating interview prep for {job['title']} @ {job['company']}")
                job["interview_prep"] = self.generate_for_job(job)
        return jobs
