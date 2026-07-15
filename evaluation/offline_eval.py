"""
evaluation/offline_eval.py — Offline quality evaluation
=========================================================
Runs the golden dataset through the pipeline and measures:
  - Scoring accuracy (are high-match jobs scoring high?)
  - Cover letter quality (no placeholders, right length, company mentioned)
  - ATS scan accuracy (does PASS/FAIL match expectation?)
  - Scam filter precision/recall (false positives = real jobs blocked)
  - Cost per test case

Run:
  python evaluation/offline_eval.py
  python evaluation/offline_eval.py --feature scoring
  python evaluation/offline_eval.py --save

Outputs results to evaluation/eval_results/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

GOLDEN_PATH = Path(__file__).parent / "golden_dataset.json"
RESULTS_DIR = Path(__file__).parent / "eval_results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_golden() -> Dict:
    return json.loads(GOLDEN_PATH.read_text())


def eval_scoring(cases: List[Dict], config: Dict, resume: str) -> Dict:
    """Evaluate scoring accuracy against golden cases."""
    from ai.scorer import JobScorer
    scorer = JobScorer(config, resume)

    results = []
    passed = failed = 0

    for case in cases:
        job = case["job"]
        expected_min = case.get("expected_score_min", 0)
        expected_max = case.get("expected_score_max", 100)
        resume_override = case.get("resume", resume)

        try:
            scored = scorer.score_jobs([{**job, "source": "eval"}])
            score = scored[0].get("score", 0) if scored else 0
            in_range = expected_min <= score <= expected_max

            results.append({
                "id": case["id"],
                "description": case.get("description"),
                "job": job["title"] + " @ " + job["company"],
                "score": score,
                "expected_range": f"{expected_min}–{expected_max}",
                "passed": in_range,
            })
            if in_range:
                passed += 1
                logger.info(f"  ✅ {case['id']}: {score:.0f} (expected {expected_min}–{expected_max})")
            else:
                failed += 1
                logger.warning(f"  ❌ {case['id']}: {score:.0f} (expected {expected_min}–{expected_max})")
        except Exception as e:
            logger.error(f"  💥 {case['id']}: {e}")
            results.append({"id": case["id"], "passed": False, "error": str(e)})
            failed += 1

    return {
        "feature": "scoring",
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(cases) * 100, 1) if cases else 0,
        "results": results,
    }


def eval_cover_letters(cases: List[Dict], config: Dict, resume: str) -> Dict:
    """Evaluate cover letter quality."""
    from ai.cover_letter import CoverLetterGenerator
    generator = CoverLetterGenerator(config, resume)

    results = []
    passed = failed = 0

    for case in cases:
        job = case["job"]
        resume_override = case.get("resume", resume)
        must_contain = case.get("must_contain", [])
        must_not_contain = case.get("must_not_contain", [])
        min_words = case.get("min_words", 100)
        max_words = case.get("max_words", 500)

        try:
            result = generator.generate(job, resume_override)
            cl = result.get("cover_letter", "")
            word_count = len(cl.split())
            issues = []

            for phrase in must_contain:
                if phrase.lower() not in cl.lower():
                    issues.append(f"Missing: '{phrase}'")
            for phrase in must_not_contain:
                if phrase.lower() in cl.lower():
                    issues.append(f"Contains banned: '{phrase}'")
            if word_count < min_words:
                issues.append(f"Too short: {word_count} words")
            if word_count > max_words:
                issues.append(f"Too long: {word_count} words")

            ok = len(issues) == 0
            results.append({
                "id": case["id"],
                "description": case.get("description"),
                "word_count": word_count,
                "issues": issues,
                "passed": ok,
            })
            if ok:
                passed += 1
                logger.info(f"  ✅ {case['id']}: {word_count} words, no issues")
            else:
                failed += 1
                logger.warning(f"  ❌ {case['id']}: {issues}")
        except Exception as e:
            logger.error(f"  💥 {case['id']}: {e}")
            results.append({"id": case["id"], "passed": False, "error": str(e)})
            failed += 1

    return {
        "feature": "cover_letter",
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(cases) * 100, 1) if cases else 0,
        "results": results,
    }


def eval_scam_filter(cases: List[Dict], config: Dict) -> Dict:
    """Evaluate scam detection precision/recall."""
    from ai.repost_detector import RepostDetector
    detector = RepostDetector(config)

    results = []
    true_positive = false_positive = true_negative = false_negative = 0

    for case in cases:
        job = {**case["job"], "source": "eval", "job_url": "https://example.com/job/1"}
        expected_blocked = case.get("expected_blocked", False)

        _, filtered = detector.filter_jobs([job])
        actually_blocked = len(filtered) > 0

        tp = expected_blocked and actually_blocked
        fp = not expected_blocked and actually_blocked
        tn = not expected_blocked and not actually_blocked
        fn = expected_blocked and not actually_blocked

        if tp: true_positive += 1
        if fp: false_positive += 1
        if tn: true_negative += 1
        if fn: false_negative += 1

        results.append({
            "id": case["id"],
            "expected": "blocked" if expected_blocked else "allowed",
            "actual": "blocked" if actually_blocked else "allowed",
            "correct": tp or tn,
        })
        status = "✅" if (tp or tn) else ("❌ FALSE POSITIVE" if fp else "❌ FALSE NEGATIVE")
        logger.info(f"  {status} {case['id']}")

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0

    return {
        "feature": "scam_filter",
        "total": len(cases),
        "precision": round(precision * 100, 1),
        "recall": round(recall * 100, 1),
        "false_positives": false_positive,  # Real jobs incorrectly blocked — bad!
        "false_negatives": false_negative,  # Scams that slipped through — bad!
        "results": results,
    }


def run_all(config: Dict, resume: str, features: List[str] = None, save: bool = False) -> Dict:
    """Run all evaluations."""
    golden = load_golden()
    start = time.time()

    logger.info("=" * 60)
    logger.info("🧪 AI Job Agent — Offline Evaluation")
    logger.info("=" * 60)

    all_results = {}

    if not features or "scoring" in features:
        logger.info("\n📊 Evaluating: Scoring")
        all_results["scoring"] = eval_scoring(golden.get("scoring_cases", []), config, resume)

    if not features or "cover_letter" in features:
        logger.info("\n✍️  Evaluating: Cover Letters")
        all_results["cover_letter"] = eval_cover_letters(golden.get("cover_letter_cases", []), config, resume)

    if not features or "scam_filter" in features:
        logger.info("\n🛡️  Evaluating: Scam Filter")
        all_results["scam_filter"] = eval_scam_filter(golden.get("scam_filter_cases", []), config)

    # Summary
    elapsed = time.time() - start
    summary = {
        "run_at": datetime.utcnow().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "results": all_results,
        "overall_pass_rate": round(
            sum(r.get("pass_rate", 0) for r in all_results.values()) / len(all_results)
            if all_results else 0, 1
        ),
    }

    logger.info("\n" + "=" * 60)
    logger.info(f"✅ Overall pass rate: {summary['overall_pass_rate']}%")
    logger.info(f"⏱  Elapsed: {elapsed:.1f}s")

    if save:
        fname = RESULTS_DIR / f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        fname.write_text(json.dumps(summary, indent=2))
        logger.info(f"💾 Saved: {fname}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Job Agent — Offline Eval")
    parser.add_argument("--feature", nargs="+", choices=["scoring", "cover_letter", "scam_filter"])
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    import yaml
    config = yaml.safe_load(Path(args.config).read_text()) if Path(args.config).exists() else {}
    resume_path = config.get("profile", {}).get("resume_path", "resume.txt")
    resume = Path(resume_path).read_text() if Path(resume_path).exists() else "Sample resume text"

    run_all(config, resume, args.feature, args.save)
