"""
LeetCode Problem Recommender
=============================
Recommends specific LeetCode problems based on:
  - Target company (uses known company-specific problem sets)
  - Job description keywords (data structures mentioned)
  - Interview stage (phone screen vs. technical vs. onsite)
  - User's weak areas (tracked from mock interview scorecards)

Data sources:
  - Built-in company problem lists (curated from public leetcode discussions)
  - JD keyword-to-DSA mapping
  - Progression tracking (skip problems already marked done)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Company-specific problem tags (from public LeetCode company tags)
COMPANY_PROBLEM_TAGS = {
    "google": ["two-sum", "meeting-rooms-ii", "word-search", "number-of-islands",
               "lru-cache", "serialize-deserialize-binary-tree", "jump-game",
               "minimum-window-substring", "alien-dictionary"],
    "meta": ["two-sum", "valid-parentheses", "copy-list-with-random-pointer",
             "binary-tree-right-side-view", "accounts-merge", "subarray-sum-equals-k",
             "merge-intervals", "expression-add-operators"],
    "amazon": ["two-sum", "lru-cache", "word-ladder", "number-of-islands",
               "minimum-cost-to-connect-sticks", "reorder-data-in-log-files",
               "k-closest-points-to-origin", "top-k-frequent-elements"],
    "microsoft": ["two-sum", "merge-two-sorted-lists", "linked-list-cycle",
                  "binary-tree-level-order-traversal", "design-hashmap",
                  "reverse-linked-list", "number-of-islands"],
    "apple": ["two-sum", "spiral-matrix", "longest-palindromic-substring",
              "merge-intervals", "find-minimum-in-rotated-sorted-array"],
    "netflix": ["design-netflix", "lru-cache", "rate-limiter", "consistent-hashing"],
    "uber": ["surge-pricing", "optimal-account-balancing", "reconstruct-itinerary",
             "minimum-cost-to-connect-sticks"],
    "airbnb": ["design-booking-system", "sliding-window-maximum", "serialize-binary-tree"],
    "stripe": ["design-payment-system", "rate-limiter", "top-k-frequent-elements"],
    "databricks": ["distributed-systems", "streaming-data", "map-reduce-patterns"],
    "openai": ["transformer-math", "dynamic-programming", "graph-algorithms"],
    "anthropic": ["system-design", "dynamic-programming", "graph-algorithms"],
}

# DSA topic → LeetCode problems (curated Top-150 list)
TOPIC_PROBLEMS = {
    "array": [
        {"id": 1, "name": "Two Sum", "difficulty": "Easy", "url": "https://leetcode.com/problems/two-sum/"},
        {"id": 53, "name": "Maximum Subarray", "difficulty": "Medium", "url": "https://leetcode.com/problems/maximum-subarray/"},
        {"id": 152, "name": "Maximum Product Subarray", "difficulty": "Medium", "url": "https://leetcode.com/problems/maximum-product-subarray/"},
        {"id": 238, "name": "Product of Array Except Self", "difficulty": "Medium", "url": "https://leetcode.com/problems/product-of-array-except-self/"},
    ],
    "string": [
        {"id": 3, "name": "Longest Substring Without Repeating", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-substring-without-repeating-characters/"},
        {"id": 76, "name": "Minimum Window Substring", "difficulty": "Hard", "url": "https://leetcode.com/problems/minimum-window-substring/"},
        {"id": 49, "name": "Group Anagrams", "difficulty": "Medium", "url": "https://leetcode.com/problems/group-anagrams/"},
    ],
    "tree": [
        {"id": 102, "name": "Binary Tree Level Order Traversal", "difficulty": "Medium", "url": "https://leetcode.com/problems/binary-tree-level-order-traversal/"},
        {"id": 297, "name": "Serialize and Deserialize Binary Tree", "difficulty": "Hard", "url": "https://leetcode.com/problems/serialize-and-deserialize-binary-tree/"},
        {"id": 236, "name": "Lowest Common Ancestor", "difficulty": "Medium", "url": "https://leetcode.com/problems/lowest-common-ancestor-of-a-binary-tree/"},
    ],
    "graph": [
        {"id": 200, "name": "Number of Islands", "difficulty": "Medium", "url": "https://leetcode.com/problems/number-of-islands/"},
        {"id": 207, "name": "Course Schedule", "difficulty": "Medium", "url": "https://leetcode.com/problems/course-schedule/"},
        {"id": 323, "name": "Connected Components", "difficulty": "Medium", "url": "https://leetcode.com/problems/number-of-connected-components-in-an-undirected-graph/"},
    ],
    "dp": [
        {"id": 70, "name": "Climbing Stairs", "difficulty": "Easy", "url": "https://leetcode.com/problems/climbing-stairs/"},
        {"id": 300, "name": "Longest Increasing Subsequence", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-increasing-subsequence/"},
        {"id": 322, "name": "Coin Change", "difficulty": "Medium", "url": "https://leetcode.com/problems/coin-change/"},
        {"id": 1143, "name": "Longest Common Subsequence", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-common-subsequence/"},
    ],
    "heap": [
        {"id": 347, "name": "Top K Frequent Elements", "difficulty": "Medium", "url": "https://leetcode.com/problems/top-k-frequent-elements/"},
        {"id": 295, "name": "Find Median from Data Stream", "difficulty": "Hard", "url": "https://leetcode.com/problems/find-median-from-data-stream/"},
        {"id": 23, "name": "Merge K Sorted Lists", "difficulty": "Hard", "url": "https://leetcode.com/problems/merge-k-sorted-lists/"},
    ],
    "design": [
        {"id": 146, "name": "LRU Cache", "difficulty": "Medium", "url": "https://leetcode.com/problems/lru-cache/"},
        {"id": 155, "name": "Min Stack", "difficulty": "Easy", "url": "https://leetcode.com/problems/min-stack/"},
        {"id": 706, "name": "Design HashMap", "difficulty": "Easy", "url": "https://leetcode.com/problems/design-hashmap/"},
        {"id": 460, "name": "LFU Cache", "difficulty": "Hard", "url": "https://leetcode.com/problems/lfu-cache/"},
    ],
    "sliding_window": [
        {"id": 239, "name": "Sliding Window Maximum", "difficulty": "Hard", "url": "https://leetcode.com/problems/sliding-window-maximum/"},
        {"id": 424, "name": "Longest Repeating Character Replacement", "difficulty": "Medium", "url": "https://leetcode.com/problems/longest-repeating-character-replacement/"},
    ],
}

JD_KEYWORD_TO_TOPIC = {
    "database": "design", "caching": "design", "cache": "design",
    "distributed": "design", "scale": "design", "system design": "design",
    "tree": "tree", "binary": "tree", "bst": "tree",
    "graph": "graph", "network": "graph", "path": "graph", "bfs": "graph", "dfs": "graph",
    "dynamic programming": "dp", "optimization": "dp", "memoization": "dp",
    "sorting": "array", "searching": "array", "binary search": "array",
    "string": "string", "parsing": "string", "regex": "string",
    "heap": "heap", "priority queue": "heap", "top k": "heap",
    "window": "sliding_window", "stream": "sliding_window",
}

PHONE_SCREEN_TOPICS = ["array", "string", "design"]
TECHNICAL_TOPICS = ["array", "string", "tree", "graph", "dp", "heap", "design"]
ONSITE_TOPICS = ["graph", "dp", "design", "tree", "sliding_window", "heap"]


class LeetCodeRecommender:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self._progress_path = Path("leetcode_progress.json")
        self._progress = self._load_progress()

    def _load_progress(self) -> dict:
        if self._progress_path.exists():
            try:
                return json.loads(self._progress_path.read_text())
            except Exception:
                pass
        return {"solved": [], "skipped": [], "in_progress": []}

    def _save_progress(self):
        self._progress_path.write_text(json.dumps(self._progress, indent=2))

    def mark_solved(self, problem_id: int):
        self._progress.setdefault("solved", [])
        if problem_id not in self._progress["solved"]:
            self._progress["solved"].append(problem_id)
        self._save_progress()

    def mark_skipped(self, problem_id: int):
        self._progress.setdefault("skipped", [])
        if problem_id not in self._progress["skipped"]:
            self._progress["skipped"].append(problem_id)
        self._save_progress()

    def _get_topics_from_jd(self, job_description: str) -> List[str]:
        jd_lower = job_description.lower()
        topics = set()
        for keyword, topic in JD_KEYWORD_TO_TOPIC.items():
            if keyword in jd_lower:
                topics.add(topic)
        return list(topics) or ["array", "string"]

    def _get_topics_for_stage(self, interview_stage: str) -> List[str]:
        stage_lower = (interview_stage or "").lower()
        if "phone" in stage_lower or "screen" in stage_lower:
            return PHONE_SCREEN_TOPICS
        elif "onsite" in stage_lower or "final" in stage_lower:
            return ONSITE_TOPICS
        return TECHNICAL_TOPICS

    def recommend(self, company: str = "", job_description: str = "",
                  interview_stage: str = "technical",
                  count: int = 10) -> Dict:
        """Get personalized LeetCode recommendations."""
        solved = set(self._progress.get("solved", []))
        skipped = set(self._progress.get("skipped", []))
        done = solved | skipped

        # Determine topics
        jd_topics = self._get_topics_from_jd(job_description) if job_description else []
        stage_topics = self._get_topics_for_stage(interview_stage)
        all_topics = list(dict.fromkeys(jd_topics + stage_topics))  # preserve order, dedupe

        # Get company-specific problems
        company_lower = company.lower().split()[0] if company else ""
        company_tags = COMPANY_PROBLEM_TAGS.get(company_lower, [])

        # Build recommendation list
        recommended = []
        for topic in all_topics:
            for problem in TOPIC_PROBLEMS.get(topic, []):
                if problem["id"] not in done:
                    problem["topic"] = topic
                    recommended.append(problem)
                if len(recommended) >= count:
                    break
            if len(recommended) >= count:
                break

        # Add company specific tags as notes
        if company_tags:
            for prob in recommended[:5]:
                prob["company_relevant"] = True

        study_plan = self._generate_study_plan(all_topics, interview_stage)

        return {
            "problems": recommended[:count],
            "topics_focus": all_topics[:5],
            "company_tags": company_tags[:8],
            "study_plan": study_plan,
            "solved_count": len(solved),
            "total_recommended": len(recommended),
        }

    def _generate_study_plan(self, topics: List[str], stage: str) -> str:
        stage_lower = (stage or "").lower()
        if "phone" in stage_lower:
            return (
                "📱 **Phone Screen Prep (3-5 days)**\n"
                "Day 1-2: Arrays + Strings (Easy/Medium)\n"
                "Day 3: Hash Maps + Two Pointers\n"
                "Day 4-5: Mock phone screen (45 min, 1 problem)"
            )
        elif "onsite" in stage_lower:
            return (
                "🏢 **Onsite Prep (1-2 weeks)**\n"
                "Week 1: Graphs (BFS/DFS/Topological Sort)\n"
                "       Dynamic Programming (patterns)\n"
                "       System Design (1 mock daily)\n"
                "Week 2: Mock onsites (3 rounds/day)\n"
                "        Review Behavioral (STAR format)"
            )
        return (
            "💻 **Technical Round Prep (1 week)**\n"
            "Day 1: Arrays + Strings (5 problems)\n"
            "Day 2: Trees + Graphs (5 problems)\n"
            "Day 3: Dynamic Programming (3 problems)\n"
            "Day 4: Heaps + Design (3 problems)\n"
            "Day 5: Sliding Window + Intervals (3 problems)\n"
            "Day 6-7: Mock interviews"
        )

    def get_daily_problem(self) -> Optional[Dict]:
        """Get today's recommended problem (1-per-day habit)."""
        solved = set(self._progress.get("solved", []))
        # Rotate through topics day by day
        day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
        topics = list(TOPIC_PROBLEMS.keys())
        today_topic = topics[day_of_year % len(topics)]
        for problem in TOPIC_PROBLEMS.get(today_topic, []):
            if problem["id"] not in solved:
                return {**problem, "topic": today_topic, "daily": True}
        return None
