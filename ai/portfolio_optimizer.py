"""
GitHub / Portfolio Optimizer
=============================
Employers check GitHub. Most candidates have:
  - Outdated pinned projects
  - READMEs that say "a project I did for class"
  - Projects that don't match the jobs they're applying to

This module:
  1. Fetches your GitHub repos via API (no login needed for public repos)
  2. Scores each repo's relevance to your target jobs
  3. Recommends which 6 to pin (GitHub allows 6 pinned)
  4. Rewrites README for top repos to be recruiter-friendly
  5. Suggests quick improvements to boost repo quality
"""

import logging
import os
import re
from typing import Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

README_REWRITE_PROMPT = """You are rewriting a GitHub README to be more impressive to technical recruiters.

Repository: {repo_name}
Current README:
{current_readme}

Job context (what companies are looking for):
{job_context}

Rewrite the README with:
1. **One-line headline** that says what it does (not "This is a project for...")
2. **Key highlights** (3 bullets: what problem it solves, tech stack, scale/impact)
3. **Quick Start** (5 lines max — make it easy to run)
4. **Results/Outcomes** (metrics, accuracy, speed improvement, users, etc.)
5. **Tech Stack** badges/section

Rules:
- Replace "class project" / "coursework" with the actual technical description
- Use action verbs: "Built", "Implemented", "Achieved", "Reduced", "Scaled"
- Add specific numbers where possible
- Keep it under 400 words
- Make it sound like production work, not homework"""

REPO_SCORE_PROMPT = """Score this GitHub repository for job relevance.

Repository: {repo_name}
Description: {description}
Languages: {languages}
Topics: {topics}
Stars: {stars}
Last updated: {updated}

Target jobs context:
{job_context}

Return JSON:
{{
  "relevance_score": <0-10>,
  "should_pin": <true/false>,
  "recruiter_appeal": <0-10>,
  "improvements": ["specific improvement 1", "improvement 2", "improvement 3"],
  "pin_reason": "<why to pin or not pin>"
}}"""

PIN_STRATEGY_PROMPT = """Given these GitHub repositories, recommend the best 6 to pin for a job seeker
targeting {target_roles}.

Repositories:
{repos_summary}

Return JSON:
{{
  "recommended_pins": ["repo1", "repo2", "repo3", "repo4", "repo5", "repo6"],
  "pin_strategy": "<overall strategy explanation>",
  "repos_to_improve_before_pinning": [
    {{"repo": "name", "quick_fix": "what to do in 30 minutes to make it pin-worthy"}}
  ]
}}"""


class PortfolioOptimizer:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self.github_username = config.get("portfolio", {}).get("github_username", "")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 600, json_mode: bool = False) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            kwargs = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4, max_tokens=max_tokens,
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

    def fetch_repos(self, username: str = None) -> List[Dict]:
        """Fetch public repos from GitHub API."""
        username = username or self.github_username
        if not username:
            logger.warning("No GitHub username set. Add to config.yaml: portfolio.github_username")
            return []
        try:
            import requests
            resp = requests.get(
                f"https://api.github.com/users/{username}/repos",
                params={"sort": "updated", "per_page": 30},
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            resp.raise_for_status()
            repos = []
            for r in resp.json():
                repos.append({
                    "name": r.get("name", ""),
                    "description": r.get("description", "") or "",
                    "url": r.get("html_url", ""),
                    "language": r.get("language", ""),
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "topics": r.get("topics", []),
                    "updated": (r.get("updated_at") or "")[:10],
                    "is_fork": r.get("fork", False),
                })
            logger.info(f"GitHub: fetched {len(repos)} repos for {username}")
            return repos
        except Exception as e:
            logger.error(f"GitHub API failed: {e}")
            return []

    def fetch_readme(self, username: str, repo_name: str) -> str:
        """Fetch README content for a specific repo."""
        try:
            import requests
            resp = requests.get(
                f"https://api.github.com/repos/{username}/{repo_name}/readme",
                headers={"Accept": "application/vnd.github.v3.raw"},
                timeout=10,
            )
            return resp.text[:3000] if resp.status_code == 200 else ""
        except Exception:
            return ""

    def score_repos(self, repos: List[Dict], jobs: List[Dict]) -> List[Dict]:
        """Score repos for relevance to target jobs."""
        job_context = " ".join(
            f"{j.get('title')} at {j.get('company')}: {(j.get('description') or '')[:200]}"
            for j in jobs[:5]
        )
        import json as _json
        scored = []
        for repo in repos:
            if repo.get("is_fork") and repo.get("stars", 0) == 0:
                continue  # skip unmodified forks
            try:
                raw = self._llm(REPO_SCORE_PROMPT.format(
                    repo_name=repo["name"],
                    description=repo.get("description", ""),
                    languages=repo.get("language", ""),
                    topics=", ".join(repo.get("topics", [])),
                    stars=repo.get("stars", 0),
                    updated=repo.get("updated", ""),
                    job_context=job_context[:500],
                ), max_tokens=300, json_mode=(self.provider == "openai"))
                score_data = _json.loads(raw) if isinstance(raw, str) else raw
                repo.update(score_data)
            except Exception as e:
                logger.warning(f"Repo scoring failed for {repo['name']}: {e}")
                repo["relevance_score"] = 0
            scored.append(repo)

        scored.sort(key=lambda r: (r.get("relevance_score", 0) + r.get("recruiter_appeal", 0)), reverse=True)
        return scored

    def get_pin_strategy(self, scored_repos: List[Dict], target_roles: str = "Software/ML Engineer") -> Dict:
        """Recommend which 6 repos to pin."""
        import json as _json
        repos_summary = "\n".join(
            f"- {r['name']}: relevance={r.get('relevance_score',0)}, appeal={r.get('recruiter_appeal',0)}, "
            f"lang={r.get('language','')}, stars={r.get('stars',0)}"
            for r in scored_repos[:15]
        )
        try:
            raw = self._llm(PIN_STRATEGY_PROMPT.format(
                target_roles=target_roles,
                repos_summary=repos_summary,
            ), max_tokens=400, json_mode=(self.provider == "openai"))
            return _json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            logger.warning(f"Pin strategy failed: {e}")
            return {"recommended_pins": [r["name"] for r in scored_repos[:6]]}

    def rewrite_readme(self, repo: Dict, username: str, jobs: List[Dict]) -> str:
        """Generate improved README for a repo."""
        current_readme = self.fetch_readme(username or self.github_username, repo["name"])
        job_context = " ".join(
            f"{j.get('title')}: {(j.get('description') or '')[:100]}"
            for j in jobs[:3]
        )
        return self._llm(README_REWRITE_PROMPT.format(
            repo_name=repo["name"],
            current_readme=current_readme or f"Repository: {repo.get('description', 'No description')}",
            job_context=job_context[:400],
        ), max_tokens=600)

    def generate_report(self, jobs: List[Dict]) -> Dict:
        """Full portfolio analysis report."""
        username = self.github_username
        if not username:
            return {"error": "Set portfolio.github_username in config.yaml"}

        repos = self.fetch_repos(username)
        if not repos:
            return {"error": "No repos found or GitHub API failed"}

        scored = self.score_repos(repos, jobs)
        pin_strategy = self.get_pin_strategy(scored)

        return {
            "username": username,
            "total_repos": len(repos),
            "scored_repos": scored,
            "pin_strategy": pin_strategy,
            "top_repos": scored[:6],
        }
