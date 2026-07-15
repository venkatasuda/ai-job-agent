"""
Voice Interview Practice
=========================
Simulates a voice-based interview using Text-to-Speech (TTS) for the
interviewer and Speech-to-Text (STT) for the candidate.

Modes:
  1. Text mode (default) — type answers, get feedback
  2. Voice mode — speak answers, AI transcribes and evaluates
     Requires: pip install openai (for Whisper STT + TTS API)
     OR: pip install pyttsx3 SpeechRecognition pyaudio (local, free)

Evaluates:
  - Content quality (STAR structure, relevance)
  - Filler words (um, uh, like, you know)
  - Answer length (too short < 90s, ideal 90-150s, too long > 180s)
  - Confidence indicators
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VOICE_FEEDBACK_PROMPT = """You are an expert interview coach evaluating this candidate answer.

Question: {question}
Answer transcript: {answer}
Answer duration: {duration_seconds} seconds

Evaluate and return JSON:
{{
  "content_score": <1-10>,
  "star_structure": "<Complete|Partial|Missing>",
  "filler_count": <int>,
  "ideal_length": <true|false>,
  "key_strengths": ["<strength1>", "<strength2>"],
  "improvements": ["<improvement1>", "<improvement2>"],
  "better_answer_tip": "<one specific tip>",
  "overall_grade": "<A|B|C|D>",
  "coaching_note": "<2 sentence coaching note>"
}}"""

FILLER_WORDS = [
    r"\bum\b", r"\buh\b", r"\blike\b(?! a )", r"\byou know\b",
    r"\bbasically\b", r"\bactually\b", r"\bliterally\b", r"\bso\b(?= \w)",
    r"\bright\b(?= \w)", r"\bokay\b(?= \w)",
]

BEHAVIORAL_QUESTIONS = [
    "Tell me about a time you dealt with a difficult team member.",
    "Describe a project where you had to learn something new quickly.",
    "Tell me about your biggest technical failure and what you learned.",
    "Give an example of a time you improved a process or system.",
    "Describe a situation where you disagreed with your manager. What did you do?",
    "Tell me about a time you had to meet a tight deadline.",
    "Give an example of leading a project without formal authority.",
    "Tell me about a time you received critical feedback. How did you respond?",
]

TECHNICAL_OPENER_QUESTIONS = [
    "Walk me through how you'd design a URL shortener.",
    "Explain the difference between SQL and NoSQL databases.",
    "How would you debug a slow API endpoint?",
    "What happens when you type a URL in a browser?",
    "Explain REST vs gRPC. When would you choose each?",
]


class VoiceInterviewSession:
    def __init__(self, config: dict, mode: str = "text"):
        """
        mode: 'text' (type answers) or 'voice' (speak answers via microphone)
        """
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self.mode = mode
        self._client = None
        self._session_path = Path("voice_session_log.json")
        self.history: List[Dict] = []
        self.current_question = ""
        self.question_start_time: Optional[float] = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str) -> dict:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3, max_tokens=500,
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content)
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                text = genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text
                m = re.search(r'\{.*\}', text, re.DOTALL)
                return json.loads(m.group()) if m else {}
        except Exception as e:
            logger.warning(f"Voice interview LLM error: {e}")
        return {}

    def _count_fillers(self, text: str) -> int:
        count = 0
        for pattern in FILLER_WORDS:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        return count

    def speak(self, text: str):
        """Text-to-speech for interviewer questions."""
        if self.mode != "voice":
            print(f"\n🎤 Interviewer: {text}\n")
            return
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 160)
            engine.say(text)
            engine.runAndWait()
        except ImportError:
            print(f"\n🎤 Interviewer: {text}\n")

    def listen(self, timeout: int = 120) -> tuple:
        """Speech-to-text for candidate answers. Returns (transcript, duration)."""
        if self.mode != "voice":
            print("📝 Your answer (press Enter twice when done):")
            lines = []
            try:
                while True:
                    line = input()
                    if line == "" and lines and lines[-1] == "":
                        break
                    lines.append(line)
            except (EOFError, KeyboardInterrupt):
                pass
            transcript = "\n".join(lines).strip()
            word_count = len(transcript.split())
            duration = max(30, word_count * 0.5)  # estimate ~2 words/sec
            return transcript, duration

        # Voice mode — use microphone
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            print("🎙️  Listening... (speak now, Ctrl+C to stop early)")
            start = time.time()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
                try:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=timeout)
                    duration = time.time() - start
                    # Try Whisper API first (more accurate)
                    if self.provider == "openai":
                        try:
                            client = self._get_openai_client()
                            audio_bytes = audio.get_wav_data()
                            import io
                            transcript = client.audio.transcriptions.create(
                                model="whisper-1",
                                file=("audio.wav", io.BytesIO(audio_bytes)),
                            ).text
                            return transcript, duration
                        except Exception:
                            pass
                    # Fallback: Google STT (free)
                    transcript = recognizer.recognize_google(audio)
                    return transcript, time.time() - start
                except sr.WaitTimeoutError:
                    return "", 0
        except ImportError:
            logger.warning("Voice mode requires: pip install SpeechRecognition pyaudio")
            return "", 0

    def start_session(self, round_type: str = "behavioral") -> str:
        """Start a new mock interview session."""
        if round_type == "behavioral":
            questions = BEHAVIORAL_QUESTIONS
        elif round_type in ("technical", "system_design"):
            questions = TECHNICAL_OPENER_QUESTIONS
        else:
            questions = BEHAVIORAL_QUESTIONS + TECHNICAL_OPENER_QUESTIONS

        intro = (
            f"Hi! I'm your interviewer today. This is a {round_type} interview practice session. "
            "I'll ask you a series of questions and give you feedback after each answer. "
            "Let's get started!\n\n"
            f"**First question:**"
        )
        import random
        self.current_question = random.choice(questions)
        full_intro = intro + "\n\n" + self.current_question
        self.speak(full_intro)
        self.question_start_time = time.time()
        self.history = []
        return full_intro

    def evaluate_answer(self, transcript: str, duration: float) -> Dict:
        """Evaluate a candidate's answer and return feedback."""
        filler_count = self._count_fillers(transcript)
        result = self._llm_json(VOICE_FEEDBACK_PROMPT.format(
            question=self.current_question,
            answer=transcript[:2000],
            duration_seconds=int(duration),
        ))
        result["filler_words_detected"] = filler_count
        result["duration_seconds"] = int(duration)
        result["transcript"] = transcript
        result["question"] = self.current_question
        return result

    def next_question(self, round_type: str = "behavioral") -> str:
        """Move to the next question."""
        transcript, duration = self.listen()
        if not transcript:
            return "Couldn't hear your answer. Let's try again."

        feedback = self.evaluate_answer(transcript, duration)
        self.history.append(feedback)

        # Build feedback message
        grade = feedback.get("overall_grade", "B")
        content = feedback.get("content_score", 5)
        star = feedback.get("star_structure", "Partial")
        fillers = feedback.get("filler_words_detected", 0)
        tip = feedback.get("better_answer_tip", "")
        coaching = feedback.get("coaching_note", "")

        feedback_text = (
            f"\n📊 **Feedback:**\n"
            f"Grade: {grade} | Content: {content}/10 | STAR: {star}\n"
            f"Filler words: {fillers} | Duration: {int(duration)}s\n"
            f"💡 Tip: {tip}\n"
            f"🎯 {coaching}\n"
        )
        self.speak(feedback_text)

        # Next question
        import random
        questions = BEHAVIORAL_QUESTIONS if round_type == "behavioral" else TECHNICAL_OPENER_QUESTIONS
        prev = self.current_question
        remaining = [q for q in questions if q != prev]
        if remaining:
            self.current_question = random.choice(remaining)
            self.question_start_time = time.time()
            self.speak(f"\nNext question:\n{self.current_question}")
            return feedback_text + f"\n\nNext: {self.current_question}"
        return feedback_text + "\n\n✅ Session complete!"

    def get_session_scorecard(self) -> Dict:
        if not self.history:
            return {"error": "No answers recorded yet"}
        avg_content = sum(h.get("content_score", 5) for h in self.history) / len(self.history)
        total_fillers = sum(h.get("filler_words_detected", 0) for h in self.history)
        grades = [h.get("overall_grade", "B") for h in self.history]
        return {
            "questions_answered": len(self.history),
            "average_content_score": round(avg_content, 1),
            "total_filler_words": total_fillers,
            "grade_distribution": {g: grades.count(g) for g in set(grades)},
            "top_improvement": self.history[-1].get("improvements", []),
            "session_date": datetime.now(timezone.utc).isoformat(),
        }

    def save_session(self):
        """Save session to file for tracking progress."""
        all_sessions = []
        if self._session_path.exists():
            try:
                all_sessions = json.loads(self._session_path.read_text())
            except Exception:
                pass
        all_sessions.append({
            "date": datetime.now(timezone.utc).isoformat(),
            "scorecard": self.get_session_scorecard(),
            "history": self.history,
        })
        self._session_path.write_text(json.dumps(all_sessions[-20:], indent=2))
