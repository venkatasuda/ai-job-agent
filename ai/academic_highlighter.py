"""
Academic Project Highlighter
=============================
Masters grads' biggest differentiator over undergrads:
thesis, capstone projects, research papers, lab work.

Most grads bury this in the Education section.
A consultant puts it FRONT AND CENTER in the cover letter and resume.

This module:
  1. Extracts thesis/research/projects from resume
  2. Scores relevance of each project to the target job
  3. Injects the most relevant academic work into cover letters
  4. Suggests how to frame academic work as industry experience
"""

import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """Extract all academic projects, thesis work, research, and publications from this resume.

Resume:
{resume}

Return a JSON array:
[
  {{
    "name": "project/thesis name",
    "type": "thesis|capstone|research|publication|course_project|lab_work",
    "technologies": ["list of tech used"],
    "description": "what it was about in 1-2 sentences",
    "outcome": "result, grade, publication, award, etc.",
    "relevance_keywords": ["domain keywords: NLP, distributed systems, ML, etc."]
  }}
]

Include everything academic: class projects, research assistant work, papers, datasets built, competitions."""

RELEVANCE_PROMPT = """Score how relevant this academic project is to the target job.

Project: {project}
Job Title: {title}
Job Description excerpt: {description}

Return JSON:
{{
  "relevance_score": <0-10>,
  "why_relevant": "<one sentence>",
  "how_to_frame": "<how to present this as industry-relevant experience — be specific>"
}}"""

INJECT_PROMPT = """You are enhancing a cover letter to highlight this candidate's academic work.

Original cover letter:
{cover_letter}

Most relevant academic projects for this job:
{projects}

Job: {title} at {company}

Rewrite the cover letter to naturally weave in the most relevant academic project(s).
- Replace or enhance the 'middle' paragraph with academic achievements
- Frame research/thesis as real-world problem solving experience
- Use industry terms, not academic jargon ("built a production-grade X" not "implemented X for coursework")
- Keep it under 300 words
- Return only the enhanced cover letter"""


class AcademicHighlighter:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._projects_cache = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 800, json_mode: bool = False) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            kwargs = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=max_tokens,
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

    def _parse_json(self, text: str):
        import json
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return []

    def extract_projects(self) -> List[Dict]:
        """Extract all academic projects from resume. Cached after first call."""
        if self._projects_cache is not None:
            return self._projects_cache

        logger.info("Extracting academic projects from resume...")
        raw = self._llm(EXTRACT_PROMPT.format(resume=self.resume[:4000]),
                        max_tokens=1000, json_mode=(self.provider == "openai"))
        parsed = self._parse_json(raw)
        projects = parsed if isinstance(parsed, list) else parsed.get("projects", [])
        self._projects_cache = projects
        logger.info(f"Found {len(projects)} academic projects")
        return projects

    def score_for_job(self, job: Dict) -> List[Dict]:
        """Score all projects for relevance to this job. Returns sorted list."""
        projects = self.extract_projects()
        if not projects:
            return []

        scored = []
        desc = (job.get("description") or "")[:800]
        for project in projects:
            try:
                raw = self._llm(RELEVANCE_PROMPT.format(
                    project=str(project)[:400],
                    title=job.get("title", ""),
                    description=desc,
                ), max_tokens=200, json_mode=(self.provider == "openai"))
                result = self._parse_json(raw)
                if isinstance(result, dict):
                    project_copy = dict(project)
                    project_copy.update(result)
                    scored.append(project_copy)
            except Exception as e:
                logger.warning(f"Project scoring failed: {e}")
                scored.append(project)

        scored.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
        return scored

    def enhance_cover_letter(self, job: Dict, cover_letter: str) -> str:
        """Inject most relevant academic projects into an existing cover letter."""
        top_projects = self.score_for_job(job)[:2]
        if not top_projects or all(p.get("relevance_score", 0) < 4 for p in top_projects):
            return cover_letter  # not relevant enough to inject

        projects_text = "\n".join(
            f"- {p.get('name', 'Project')}: {p.get('how_to_frame', p.get('description', ''))}"
            for p in top_projects
        )
        try:
            enhanced = self._llm(INJECT_PROMPT.format(
                cover_letter=cover_letter,
                projects=projects_text,
                title=job.get("title", ""),
                company=job.get("company", ""),
            ), max_tokens=600)
            return enhanced
        except Exception as e:
            logger.warning(f"Cover letter enhancement failed: {e}")
            return cover_letter

    def enrich_jobs(self, jobs: List[Dict], threshold: int = 65) -> List[Dict]:
        """Add academic_projects field and enhance cover letters for qualifying jobs."""
        projects = self.extract_projects()
        for job in jobs:
            if (job.get("score") or 0) < threshold:
                continue
            try:
                scored = self.score_for_job(job)
                job["academic_projects"] = scored[:3]
                # Enhance cover letter if one exists
                if job.get("cover_letter") and scored and scored[0].get("relevance_score", 0) >= 5:
                    job["cover_letter"] = self.enhance_cover_letter(job, job["cover_letter"])
            except Exception as e:
                logger.error(f"Academic highlight failed for {job.get('title')}: {e}")
        return jobs

    def get_project_summary(self) -> str:
        """Get formatted summary of all academic projects for display."""
        projects = self.extract_projects()
        if not projects:
            return "No academic projects found in resume. Add your thesis/capstone/research to resume.txt"
        lines = [f"## Academic Projects ({len(projects)} found)\n"]
        for p in projects:
            lines.append(f"**{p.get('name', 'Unknown')}** [{p.get('type', '')}]")
            lines.append(f"  {p.get('description', '')}")
            tech = ", ".join(p.get("technologies", []))
            if tech:
                lines.append(f"  Tech: {tech}")
            lines.append("")
        return "\n".join(lines)
