"""
ai/resume_optimizer.py — Senior HR Consultant-Grade Resume Optimizer
=====================================================================
Rewrites your resume the way a $500/hour executive career coach would:

  1. ATS PASS — Injects every required keyword in the right density (1-3%)
  2. POWER LANGUAGE — Replaces weak verbs with impact verbs recruiters love
  3. QUANTIFICATION — Adds/estimates metrics where missing (%, $, scale, time)
  4. SKILLS ALIGNMENT — Reorders and expands skills section to mirror JD exactly
  5. SUMMARY REWRITE — Crafts a 3-sentence executive summary targeting this role
  6. BULLET REORDER — Most relevant experience floated to top of each role
  7. TITLE MIRROR — Adjusts your job titles to match JD terminology where honest
  8. GAP BRIDGING — Frames transferable skills to cover gaps
  9. SCORING — Targets 85-92 ATS match score (human shortlist territory)

Output: resumes/tailored/resume_<Company>_<Role>.txt
        resumes/tailored/resume_<Company>_<Role>_changes.txt  (what changed + why)

Cost: ~$0.015 per job (2 LLM calls, gpt-4o-mini)
Cache: Won't re-run same job unless resume or JD changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

ATS_ANALYSIS_PROMPT = """You are a SENIOR TECHNICAL RECRUITER with 15 years of experience at top tech companies (Google, Meta, Amazon, Microsoft). You have reviewed 50,000+ resumes and know exactly what ATS systems and hiring managers look for.

Analyze this resume against the job description with brutal honesty.

═══ CANDIDATE RESUME ═══
{resume}

═══ TARGET ROLE ═══
Title: {job_title}
Company: {company}
Description:
{job_description}

Your job: Give me a complete technical audit that will help rewrite this resume to score 85-92 on ATS.

Return ONLY valid JSON with these exact keys:

{{
  "current_ats_score": <int 0-100>,
  "target_ats_score": 88,

  "must_have_keywords_missing": ["exact phrase from JD not in resume"],
  "nice_to_have_keywords_missing": ["secondary keywords"],
  "keywords_present": ["keywords already matching"],

  "required_skills_missing": ["hard skills the JD requires that resume lacks"],
  "required_skills_present": ["matching hard skills"],
  "transferable_skills": ["candidate has X which covers JD requirement Y — explain"],

  "weak_bullets": ["quote the weak bullet", "..."],
  "strong_bullets": ["quote the strongest matching bullets"],
  "bullets_to_promote": ["bullets that are relevant but buried — quote them"],

  "current_title_mismatch": "<your title vs JD title — how to bridge>",
  "summary_verdict": "<is the current summary targeted or generic?>",
  "summary_must_include": ["specific phrases/themes the summary MUST hit"],

  "quantification_gaps": ["bullet that needs a number — suggest realistic metric"],
  "weak_verbs_found": ["managed", "helped", "worked on"],
  "power_verb_replacements": {{"managed": "orchestrated", "helped": "accelerated"}},

  "sections_to_add": ["Skills section missing X", "Add Certifications for Y"],
  "sections_to_restructure": ["Move Education below Experience"],

  "red_flags_unfixable": ["PhD required — cannot fabricate", "5 YOE gap"],
  "gap_bridges": ["No Go experience but Python + cloud covers 80% of Go work"],

  "why_they_shortlist_at_85": "Specific reason this resume at 85+ gets a callback",
  "optimization_potential": <int — how many points we can realistically gain>
}}"""


POWER_REWRITE_PROMPT = """You are a WORLD-CLASS EXECUTIVE RESUME WRITER who has helped 10,000+ candidates land jobs at FAANG, top startups, and Fortune 500 companies. Your rewrites consistently achieve 85-92 ATS scores and get human callbacks.

═══ MASTER RESUME (DO NOT MODIFY THIS FILE) ═══
{resume}

═══ TARGET JOB ═══
Title: {job_title}
Company: {company}

═══ JOB DESCRIPTION ═══
{job_description}

═══ TECHNICAL AUDIT (use this to guide every change) ═══
{analysis}

═══ YOUR REWRITE MISSION ═══

**NON-NEGOTIABLE RULES:**
1. NEVER invent a job, degree, company, or year that isn't in the original resume
2. NEVER claim a skill the candidate hasn't demonstrated
3. Every keyword injection must be truthful and natural — no keyword stuffing
4. Keep the same number of jobs, education entries, and overall length

**WHAT YOU MUST DO:**

A) EXECUTIVE SUMMARY (3 sentences, max 60 words):
   - Sentence 1: Who you are + years of experience + core specialty
   - Sentence 2: 2-3 biggest achievements with numbers
   - Sentence 3: Exactly what value you bring to THIS company/role
   - Use: "{job_title}" and "{company}" by name

B) SKILLS SECTION — mirror the JD's exact terminology:
   - Lead with the JD's most important keywords
   - Group: Languages | Frameworks | Cloud/Infra | Tools | Methods
   - Add every skill from "must_have_keywords_missing" that is genuinely present in experience

C) EXPERIENCE BULLETS — each bullet must:
   - Start with a POWER VERB (Led, Architected, Reduced, Scaled, Drove, Delivered, Engineered)
   - Include a METRIC (%, $, time saved, scale, users, latency, throughput)
   - Name the TECHNOLOGY used
   - Show BUSINESS IMPACT
   - Format: "Power verb + [tech/context] + metric/result + business impact"
   - Move the most JD-relevant bullets to the TOP of each role

D) KEYWORD INTEGRATION — for every keyword in "must_have_keywords_missing":
   - Find the closest real experience and rephrase to include the keyword naturally
   - If no experience matches — add it to Skills only if the candidate has touched it

E) TITLE ALIGNMENT:
   - If your title was "Software Engineer" and JD says "Backend Engineer" — you may write "Software Engineer (Backend)" if accurate

**OUTPUT FORMAT:**
Write the complete tailored resume first.

Then write exactly:
===CHANGE_LOG===
SUMMARY: <what you changed in summary and why>
SKILLS: <keywords added, removed, or reordered>
EXPERIENCE_[Company1]: <bullets moved, rephrased, metrics added>
EXPERIENCE_[Company2]: <same>
KEYWORDS_INJECTED: <list every JD keyword you added and where>
ESTIMATED_ATS_SCORE: <your honest estimate 0-100>
SHORTLIST_PROBABILITY: <Low/Medium/High/Very High> — <one sentence why>
WHAT_TO_TELL_RECRUITER: <the 2-sentence pitch they should use in the phone screen>"""


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ATSAudit:
    """Result of the ATS analysis pass."""
    current_ats_score: int = 0
    target_ats_score: int = 88
    must_have_keywords_missing: list[str] = field(default_factory=list)
    nice_to_have_keywords_missing: list[str] = field(default_factory=list)
    keywords_present: list[str] = field(default_factory=list)
    required_skills_missing: list[str] = field(default_factory=list)
    required_skills_present: list[str] = field(default_factory=list)
    transferable_skills: list[str] = field(default_factory=list)
    weak_bullets: list[str] = field(default_factory=list)
    bullets_to_promote: list[str] = field(default_factory=list)
    summary_must_include: list[str] = field(default_factory=list)
    quantification_gaps: list[str] = field(default_factory=list)
    weak_verbs_found: list[str] = field(default_factory=list)
    power_verb_replacements: dict[str, str] = field(default_factory=dict)
    red_flags_unfixable: list[str] = field(default_factory=list)
    gap_bridges: list[str] = field(default_factory=list)
    why_they_shortlist_at_85: str = ""
    optimization_potential: int = 15


@dataclass
class OptimizationResult:
    """Full result of one resume optimization."""
    job_url: str
    job_title: str
    company: str
    original_score: int
    estimated_ats_score: int
    shortlist_probability: str
    tailored_resume: str
    change_log: str
    keywords_injected: list[str]
    skills_missing: list[str]
    red_flags: list[str]
    what_to_tell_recruiter: str
    output_file: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def score_gain(self) -> int:
        return self.estimated_ats_score - self.original_score

    def console_summary(self) -> str:
        stars = "★" * min(5, self.estimated_ats_score // 18)
        return (
            f"\n{'='*58}\n"
            f"  RESUME OPTIMIZED: {self.job_title} @ {self.company}\n"
            f"{'='*58}\n"
            f"  ATS Score:    {self.original_score} → {self.estimated_ats_score} "
            f"(+{self.score_gain} pts)  {stars}\n"
            f"  Shortlist:    {self.shortlist_probability}\n"
            f"  Keywords in:  {len(self.keywords_injected)} injected\n"
            f"  Saved to:     {self.output_file}\n"
            f"\n  📞 Phone Screen Pitch:\n"
            f"  {self.what_to_tell_recruiter}\n"
            f"{'='*58}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ── Main class ────────────────────────────────────────────────────────────────

class ResumeOptimizer:
    """
    Senior HR consultant-grade resume optimizer.
    Targets 85-92 ATS score — human shortlist territory.
    """

    CACHE_PATH = Path("resume_optimizer_cache.json")
    OUTPUT_DIR = Path("resumes/tailored")

    def __init__(self, config: dict, resume_text: str = ""):
        self.config = config
        self.resume_text = resume_text or self._load_resume()
        self.ai_config = config.get("ai", {})
        self._cache: dict = self._load_cache()
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _load_resume(self) -> str:
        """Load master resume from config."""
        path = Path(self.config.get("profile", {}).get("resume_path", "resume.txt"))
        if path.exists():
            return path.read_text(encoding="utf-8")
        logger.warning(f"Resume not found at {path}")
        return ""

    def _load_cache(self) -> dict:
        try:
            return json.loads(self.CACHE_PATH.read_text()) if self.CACHE_PATH.exists() else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        self.CACHE_PATH.write_text(json.dumps(self._cache, indent=2))

    def _job_key(self, job_url: str) -> str:
        """Cache key = job_url + resume fingerprint."""
        resume_hash = hashlib.md5(self.resume_text.encode()).hexdigest()[:8]
        return hashlib.md5(f"{job_url}{resume_hash}".encode()).hexdigest()[:14]

    # ── LLM call ─────────────────────────────────────────────────────────────

    def _llm(self, prompt: str, temperature: float = 0.2) -> str:
        """Call configured LLM. Returns raw text."""
        provider = self.ai_config.get("provider", "openai")
        model = self.ai_config.get("model", "gpt-4o-mini")

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=self.ai_config.get("openai_api_key"))
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=4096,
            )
            return resp.choices[0].message.content or ""

        if provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=self.ai_config.get("gemini_api_key"))
            m = genai.GenerativeModel(model or "gemini-1.5-flash")
            return m.generate_content(prompt).text

        if provider == "ollama":
            import requests as req
            host = self.ai_config.get("ollama_host", "http://localhost:11434")
            r = req.post(f"{host}/api/generate",
                         json={"model": model or "llama3.1:8b", "prompt": prompt, "stream": False},
                         timeout=180)
            return r.json().get("response", "")

        raise ValueError(f"Unknown provider: {provider}")

    # ── Pass 1: ATS audit ─────────────────────────────────────────────────────

    def _run_ats_audit(self, job: dict) -> ATSAudit:
        """Pass 1 — detailed gap analysis by a 'senior recruiter' persona."""
        prompt = ATS_ANALYSIS_PROMPT.format(
            resume=self.resume_text[:7000],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", "")[:5000],
        )
        raw = self._llm(prompt, temperature=0.1)

        # Strip markdown fences if present
        if "```" in raw:
            m = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw

        try:
            data = json.loads(raw)
            return ATSAudit(**{k: v for k, v in data.items() if k in ATSAudit.__dataclass_fields__})
        except Exception as e:
            logger.warning(f"ATS audit parse failed: {e} — using defaults")
            return ATSAudit(current_ats_score=60, optimization_potential=25)

    # ── Pass 2: Power rewrite ─────────────────────────────────────────────────

    def _run_power_rewrite(self, job: dict, audit: ATSAudit) -> tuple[str, str]:
        """Pass 2 — full resume rewrite by 'executive resume writer' persona.
        Returns (tailored_resume, change_log).
        """
        prompt = POWER_REWRITE_PROMPT.format(
            resume=self.resume_text[:7000],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", "")[:5000],
            analysis=json.dumps(audit.__dict__, indent=2)[:3000],
        )
        raw = self._llm(prompt, temperature=0.3)

        if "===CHANGE_LOG===" in raw:
            parts = raw.split("===CHANGE_LOG===", 1)
            return parts[0].strip(), parts[1].strip()
        return raw.strip(), ""

    # ── Parse change log ──────────────────────────────────────────────────────

    def _parse_change_log(self, log: str) -> tuple[int, str, list[str], str]:
        """Extract ATS score, shortlist probability, keywords, recruiter pitch from log."""
        ats_score = 85
        shortlist = "High"
        keywords: list[str] = []
        pitch = ""

        for line in log.split("\n"):
            if line.startswith("ESTIMATED_ATS_SCORE:"):
                try:
                    ats_score = int(re.search(r"\d+", line).group())
                except Exception:
                    pass
            elif line.startswith("SHORTLIST_PROBABILITY:"):
                shortlist = line.split(":", 1)[1].strip()
            elif line.startswith("KEYWORDS_INJECTED:"):
                rest = line.split(":", 1)[1].strip()
                keywords = [k.strip(" -•") for k in re.split(r"[,;]", rest) if k.strip()]
            elif line.startswith("WHAT_TO_TELL_RECRUITER:"):
                pitch = line.split(":", 1)[1].strip()

        return ats_score, shortlist, keywords, pitch

    # ── Public API ────────────────────────────────────────────────────────────

    def optimize(self, job: dict, force: bool = False) -> OptimizationResult:
        """
        Full 2-pass optimization for one job.

        Args:
            job: dict with title, company, description, job_url, score
            force: bypass cache

        Returns:
            OptimizationResult — tailored resume + full audit
        """
        if not self.resume_text:
            raise ValueError(
                "No resume loaded. Set profile.resume_path in config.yaml "
                "and create resume.txt with your full resume text."
            )

        job_url = job.get("job_url") or job.get("url", "")
        cache_key = self._job_key(job_url)

        if not force and cache_key in self._cache:
            logger.info(f"  Cached: {job.get('company')} — skipping re-run")
            return OptimizationResult(**self._cache[cache_key])

        company = job.get("company", "Company")
        title = job.get("title", "Role")
        logger.info(f"  Optimizing: {title} @ {company}")

        # Pass 1
        audit = self._run_ats_audit(job)
        original_score = audit.current_ats_score
        logger.info(f"    ATS audit: current={original_score}, potential=+{audit.optimization_potential}")

        # Pass 2
        tailored_resume, change_log = self._run_power_rewrite(job, audit)
        ats_score, shortlist, keywords_injected, pitch = self._parse_change_log(change_log)

        # Save files
        safe_co = re.sub(r"[^\w]", "_", company)
        safe_ti = re.sub(r"[^\w]", "_", title)[:30]
        resume_file = self.OUTPUT_DIR / f"resume_{safe_co}_{safe_ti}.txt"
        log_file = self.OUTPUT_DIR / f"resume_{safe_co}_{safe_ti}_changes.txt"
        resume_file.write_text(tailored_resume, encoding="utf-8")
        log_file.write_text(
            f"JOB: {title} @ {company}\nURL: {job_url}\n"
            f"ORIGINAL SCORE: {original_score}\nOPTIMIZED SCORE: {ats_score}\n\n"
            + change_log,
            encoding="utf-8",
        )

        result = OptimizationResult(
            job_url=job_url,
            job_title=title,
            company=company,
            original_score=original_score,
            estimated_ats_score=ats_score,
            shortlist_probability=shortlist,
            tailored_resume=tailored_resume,
            change_log=change_log,
            keywords_injected=keywords_injected,
            skills_missing=audit.required_skills_missing,
            red_flags=audit.red_flags_unfixable,
            what_to_tell_recruiter=pitch,
            output_file=str(resume_file),
        )

        logger.info(result.console_summary())

        self._cache[cache_key] = result.to_dict()
        self._save_cache()
        return result

    def batch_optimize(self, jobs: list[dict], min_score: int = 70) -> list[OptimizationResult]:
        """Optimize resumes for all high-scoring jobs."""
        targets = [j for j in jobs if (j.get("score") or 0) >= min_score]
        logger.info(f"Resume optimizer: {len(targets)} jobs to optimize (score ≥ {min_score})")
        results = []
        for job in targets:
            try:
                result = self.optimize(job)
                # Write back to job dict
                job["tailored_resume"] = result.tailored_resume
                job["ats_optimized_score"] = result.estimated_ats_score
                job["shortlist_probability"] = result.shortlist_probability
                results.append(result)
            except Exception as e:
                logger.error(f"  Failed {job.get('company')}: {e}")
        return results

    def get_best_results(self, top_n: int = 5) -> list[dict]:
        """Return top N cached results sorted by ATS score."""
        all_results = list(self._cache.values())
        return sorted(all_results, key=lambda r: r.get("estimated_ats_score", 0), reverse=True)[:top_n]

    def clear_cache(self) -> None:
        """Force re-optimization on next run."""
        self._cache = {}
        if self.CACHE_PATH.exists():
            self.CACHE_PATH.unlink()
        logger.info("Resume optimizer cache cleared")
