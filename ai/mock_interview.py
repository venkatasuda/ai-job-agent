"""
Mock Interview Simulator
=========================
A senior consultant role-plays interviews with you before the real thing.
They play the interviewer, push back on weak answers, and show you
exactly how to reframe a bad response into a great one.

Features:
  - Stateful interview session (tracks Q&A history)
  - Interviewer persona adapts to company culture
  - Critiques each answer: what worked, what didn't, better version
  - Detects filler words, vague answers, missing STAR structure
  - Generates final interview scorecard at session end
  - Supports: behavioral, technical, system design, culture-fit rounds
"""

import logging
import os
import json
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

INTERVIEWER_SYSTEM_PROMPT = """You are {interviewer_name}, a {interviewer_role} at {company}.
You are conducting a {round_type} interview for the {title} position.

Your style: {style}

Job context:
{description}

Candidate resume summary:
{resume_snippet}

Rules:
- Ask ONE question at a time
- After the candidate answers, give brief feedback then ask the next question
- Be realistic — not too easy, not impossibly hard
- After 5-6 questions, end the interview and give a scorecard

Feedback format for each answer:
FEEDBACK: <2-3 sentences — what was strong, what was weak>
BETTER_VERSION: <How they could have answered this better — be specific>
NEXT_QUESTION: <your next interview question>

Start by introducing yourself and asking the first question."""

ANSWER_CRITIQUE_PROMPT = """You are an expert interview coach. Critique this interview answer.

Question asked: {question}
Candidate answered: {answer}

Provide:
1. SCORE: <1-10>
2. STRONG: <what worked in 1 sentence>
3. WEAK: <what was missing or could improve in 1 sentence>
4. MISSING_STAR: <YES/NO — did they use Situation/Task/Action/Result structure?>
5. FILLER_WORDS: <list any filler words used: "um", "like", "basically", "you know" etc>
6. BETTER_VERSION: <rewrite their answer as it should have been said — 3-4 sentences>"""

SCORECARD_PROMPT = """You are an interviewer. The interview just ended. Generate a final scorecard.

Company: {company}
Role: {title}
Interview type: {round_type}

Q&A History:
{qa_history}

Generate a JSON scorecard:
{{
  "overall_score": <1-10>,
  "hire_recommendation": "<Strong Yes|Yes|Maybe|No|Strong No>",
  "strengths": ["list of 3 candidate strengths observed"],
  "improvements": ["list of 3 things to work on before real interview"],
  "best_answer": "<which question they answered best>",
  "weakest_answer": "<which question needs most work>",
  "interview_readiness": "<Ready|Almost Ready|Needs More Prep>",
  "specific_advice": "<2-3 sentences of personalized coaching advice>"
}}"""

ROUND_STYLES = {
    "behavioral": {
        "interviewer_name": "Sarah",
        "interviewer_role": "Senior Engineering Manager",
        "style": "Warm but thorough. Digs deep with follow-ups like 'Tell me more about that' and 'What would you do differently?'. Focuses on STAR stories.",
        "opening_q": "Tell me about yourself and why you're interested in this role."
    },
    "technical": {
        "interviewer_name": "Alex",
        "interviewer_role": "Staff Engineer",
        "style": "Methodical. Asks you to think out loud. Interested in your reasoning process, not just the answer. Will give hints if you're stuck.",
        "opening_q": "Let's start with a technical question related to your background."
    },
    "system_design": {
        "interviewer_name": "Jordan",
        "interviewer_role": "Principal Engineer",
        "style": "Collaborative. Wants to see how you think at scale. Will push on trade-offs, bottlenecks, and failure modes.",
        "opening_q": "Design a system relevant to what we build here. Walk me through your thought process."
    },
    "culture_fit": {
        "interviewer_name": "Morgan",
        "interviewer_role": "Head of People",
        "style": "Conversational. Looking for alignment with company values. Asks about work style, conflict resolution, and motivation.",
        "opening_q": "What drew you to this company specifically, and what do you know about our culture?"
    },
}


class MockInterviewSession:
    """Stateful interview session for one candidate + job."""

    def __init__(self, job: Dict, resume_text: str, config: dict,
                 round_type: str = "behavioral"):
        self.job = job
        self.resume = resume_text
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self.round_type = round_type
        self.round_style = ROUND_STYLES.get(round_type, ROUND_STYLES["behavioral"])
        self.history: List[Dict] = []  # [{"question": ..., "answer": ..., "feedback": ...}]
        self.current_question: Optional[str] = None
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._client = None
        self._started = False

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, messages: List[Dict], max_tokens: int = 600) -> str:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        else:
            # Flatten messages to single prompt for other providers
            prompt = "\n\n".join(m["content"] for m in messages)
            if self.provider == "gemini":
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

    def start(self) -> str:
        """Start the interview. Returns the interviewer's opening + first question."""
        style = self.round_style
        system = INTERVIEWER_SYSTEM_PROMPT.format(
            interviewer_name=style["interviewer_name"],
            interviewer_role=style["interviewer_role"],
            company=self.job.get("company", ""),
            round_type=self.round_type,
            title=self.job.get("title", ""),
            style=style["style"],
            description=(self.job.get("description") or "")[:800],
            resume_snippet=self.resume[:600],
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please start the interview."},
        ]
        response = self._llm(messages, max_tokens=300)
        self.current_question = response
        self._started = True
        return response

    def answer(self, candidate_answer: str) -> Dict[str, str]:
        """
        Submit a candidate answer. Returns:
          - feedback: interviewer's feedback on this answer
          - better_version: how to say it better
          - next_question: next question (or None if interview done)
          - done: True if interview is over
        """
        if not self._started:
            return {"error": "Call start() first."}

        # Record in history
        self.history.append({
            "question": self.current_question,
            "answer": candidate_answer,
        })

        # Build conversation history for context
        messages = [{"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT.format(
            interviewer_name=self.round_style["interviewer_name"],
            interviewer_role=self.round_style["interviewer_role"],
            company=self.job.get("company", ""),
            round_type=self.round_type,
            title=self.job.get("title", ""),
            style=self.round_style["style"],
            description=(self.job.get("description") or "")[:800],
            resume_snippet=self.resume[:600],
        )}]

        # Add history
        for turn in self.history[:-1]:
            messages.append({"role": "assistant", "content": turn["question"]})
            messages.append({"role": "user", "content": turn["answer"]})

        messages.append({"role": "assistant", "content": self.current_question})
        messages.append({"role": "user", "content": candidate_answer})

        response = self._llm(messages, max_tokens=500)

        # Parse response
        done = len(self.history) >= 6 or "scorecard" in response.lower() or "thank you for your time" in response.lower()

        # Extract next question from response
        next_q = None
        if "NEXT_QUESTION:" in response:
            next_q = response.split("NEXT_QUESTION:")[-1].strip()
        elif not done:
            next_q = response  # treat whole response as next question

        self.history[-1]["feedback"] = response
        self.current_question = next_q

        return {
            "feedback": response,
            "next_question": next_q,
            "done": done,
            "question_count": len(self.history),
        }

    def get_scorecard(self) -> Dict:
        """Generate final scorecard after interview ends."""
        qa_text = "\n\n".join(
            f"Q{i+1}: {t['question']}\nA: {t['answer']}"
            for i, t in enumerate(self.history)
        )
        prompt = SCORECARD_PROMPT.format(
            company=self.job.get("company", ""),
            title=self.job.get("title", ""),
            round_type=self.round_type,
            qa_history=qa_text[:3000],
        )
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                import json
                return json.loads(resp.choices[0].message.content)
        except Exception as e:
            logger.error(f"Scorecard generation failed: {e}")
        return {
            "overall_score": 0,
            "hire_recommendation": "Unknown",
            "interview_readiness": "Needs More Prep",
            "specific_advice": "Could not generate scorecard.",
        }

    def save_session(self, path: str = None):
        """Save interview session to JSON file."""
        if path is None:
            company = (self.job.get("company") or "company").replace(" ", "_")
            path = f"interview_{company}_{self.round_type}_{self.session_id}.json"
        with open(path, "w") as f:
            json.dump({
                "job": {k: v for k, v in self.job.items() if k != "description"},
                "round_type": self.round_type,
                "session_id": self.session_id,
                "history": self.history,
            }, f, indent=2)
        return path


class MockInterview:
    """Factory for creating interview sessions."""

    def __init__(self, config: dict, resume_text: str):
        self.config = config
        self.resume = resume_text

    def new_session(self, job: Dict, round_type: str = "behavioral") -> MockInterviewSession:
        """Create a new interview session for a job."""
        return MockInterviewSession(job, self.resume, self.config, round_type)

    @staticmethod
    def available_rounds() -> List[str]:
        return list(ROUND_STYLES.keys())
