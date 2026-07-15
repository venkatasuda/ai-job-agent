"""
Streamlit Dashboard v3 — 7-tab AI Job Agent Dashboard
=======================================================
Tabs: 🎯 Jobs | 📬 Follow-Ups | 📚 Upskill | 🏆 Story Bank
      🎤 Mock Interview | 🧭 Career Advisor | 💼 Offer Comparator

Run with: streamlit run dashboard/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from database.db import JobDatabase

st.set_page_config(
    page_title="AI Job Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.score-badge {
    display: inline-block;
    padding: 6px 14px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 22px;
    color: white;
    min-width: 56px;
    text-align: center;
}
.grade-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 14px;
    color: white;
    margin-left: 6px;
}
.pill-match {
    background:#dcfce7;color:#166534;
    padding:2px 8px;border-radius:12px;
    font-size:12px;margin-right:4px;
}
.pill-gap {
    background:#fee2e2;color:#991b1b;
    padding:2px 8px;border-radius:12px;
    font-size:12px;margin-right:4px;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def score_color(score: int) -> str:
    if score >= 85: return "#22c55e"
    if score >= 70: return "#3b82f6"
    if score >= 55: return "#f59e0b"
    return "#ef4444"


def letter_grade(score: int) -> str:
    if score >= 90: return "A+"
    if score >= 85: return "A"
    if score >= 80: return "A-"
    if score >= 75: return "B+"
    if score >= 70: return "B"
    if score >= 65: return "B-"
    if score >= 60: return "C+"
    if score >= 55: return "C"
    return "D"


@st.cache_resource
def get_db():
    return JobDatabase("jobs.db")


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar():
    st.sidebar.title("🤖 AI Job Agent v2")
    st.sidebar.markdown("---")

    filters = {}
    filters["min_score"] = st.sidebar.slider("Min AI Score", 0, 100, 70, 5)

    sources = ["All", "linkedin", "indeed", "glassdoor", "google", "zip_recruiter",
               "greenhouse", "lever", "ashby"]
    filters["source"] = st.sidebar.selectbox("Source", sources)

    filters["show_applied"] = st.sidebar.checkbox("Show Applied Jobs", value=False)
    filters["remote_only"] = st.sidebar.checkbox("Remote Only", value=False)

    st.sidebar.markdown("---")
    filters["search"] = st.sidebar.text_input("🔍 Search title / company", "")

    st.sidebar.markdown("---")
    filters["sort"] = st.sidebar.radio(
        "Sort by", ["Score ↓", "Date ↓", "Company A-Z"],
        label_visibility="visible"
    )

    st.sidebar.markdown("---")
    db = get_db()
    s = db.stats()
    st.sidebar.metric("Total Jobs", s.get("total", 0))
    st.sidebar.metric("Applied", s.get("applied", 0))
    st.sidebar.metric("High Match (≥80)", s.get("high_match", 0))
    st.sidebar.metric("Avg Score", s.get("avg_score", 0))

    return filters


# ── Tab 1: Jobs ───────────────────────────────────────────────────────────────

def _posted_label(date_posted: str) -> str:
    """Convert date_posted string to human-readable '3 days ago' label."""
    if not date_posted:
        return ""
    try:
        from datetime import date
        posted = datetime.fromisoformat(date_posted[:10]).date()
        days = (datetime.utcnow().date() - posted).days
        if days == 0:
            return "📅 Today"
        if days == 1:
            return "📅 Yesterday"
        if days <= 7:
            return f"📅 {days}d ago"
        if days <= 30:
            return f"📅 {days // 7}w ago"
        return f"📅 {date_posted[:10]}"
    except Exception:
        return f"📅 {date_posted[:10]}" if date_posted else ""


def render_job_card(job: dict):
    score = job.get("score") or 0
    color = score_color(score)
    grade = letter_grade(score)

    col1, col2 = st.columns([5, 1])
    with col1:
        applied_badge = " ✅ Applied" if job.get("applied") else ""
        salary = ""
        if job.get("salary_min") and job.get("salary_max"):
            salary = f" 💰 ${int(job['salary_min']):,}–${int(job['salary_max']):,}"
        elif job.get("salary_estimate"):
            salary = f" 💰 ~{job['salary_estimate']}"

        posted = _posted_label(job.get("date_posted", ""))
        posted_str = f"&nbsp;&nbsp;{posted}" if posted else ""

        st.markdown(
            f"**[{job['title']}]({job['url']})** — {job['company']}"
            f"&nbsp;&nbsp;📍 {job.get('location','?')}"
            f"&nbsp;&nbsp;🔗 `{(job.get('source') or '').upper()}`"
            f"{posted_str}{salary}{applied_badge}",
            unsafe_allow_html=True,
        )

        if job.get("verdict"):
            st.caption(f"💡 {job['verdict']}")

        match_reasons = job.get("match_reasons") or []
        gap_reasons = job.get("gap_reasons") or []
        if match_reasons or gap_reasons:
            pills = " ".join(
                f'<span class="pill-match">✓ {r}</span>' for r in match_reasons[:3]
            )
            pills += " " + " ".join(
                f'<span class="pill-gap">✗ {r}</span>' for r in gap_reasons[:2]
            )
            st.markdown(pills, unsafe_allow_html=True)

    with col2:
        st.markdown(
            f'<div class="score-badge" style="background:{color}">{score}</div>'
            f'<div class="grade-badge" style="background:{color}">{grade}</div>',
            unsafe_allow_html=True,
        )

    # ATS + Culture quick badges
    badge_parts = []
    if job.get("ats_score") is not None:
        ats_color = "#22c55e" if job["ats_score"] >= 75 else "#f59e0b" if job["ats_score"] >= 55 else "#ef4444"
        badge_parts.append(f'<span style="background:{ats_color};color:white;padding:2px 8px;border-radius:8px;font-size:12px;">ATS {job["ats_score"]}</span>')
    if job.get("ats_verdict"):
        badge_parts.append(f'<span style="font-size:12px;color:#6b7280;">ATS: {job["ats_verdict"]}</span>')
    if job.get("culture_score") is not None:
        badge_parts.append(f'<span style="font-size:12px;">🏢 Culture: {job["culture_score"]}/10</span>')
    if badge_parts:
        st.markdown(" &nbsp; ".join(badge_parts), unsafe_allow_html=True)

    # Inline detail tabs
    detail_tabs = []
    detail_labels = []
    if job.get("cover_letter"):
        detail_labels.append("📝 Cover Letter")
        detail_tabs.append("cover_letter")
    if job.get("email_draft"):
        detail_labels.append("📧 Email Draft")
        detail_tabs.append("email_draft")
    if job.get("tailored_resume"):
        detail_labels.append("📄 Tailored Resume")
        detail_tabs.append("tailored_resume")
    if job.get("ats_scan"):
        from ai.ats_scanner import ATSScanner
        ats_text = ATSScanner.format_report(job["ats_scan"])
        job["_ats_report"] = ats_text
        detail_labels.append("🤖 ATS Scan")
        detail_tabs.append("_ats_report")
    if job.get("outreach_linkedin_dm"):
        detail_labels.append("📨 LinkedIn DM")
        detail_tabs.append("outreach_linkedin_dm")
    if job.get("outreach_cold_email"):
        detail_labels.append("✉️ Cold Email")
        detail_tabs.append("outreach_cold_email")
    if job.get("company_research"):
        detail_labels.append("🏢 Company Research")
        detail_tabs.append("company_research")
    if job.get("culture_analysis"):
        from ai.culture_analyzer import CultureAnalyzer
        job["_culture_report"] = CultureAnalyzer.format_report(job["culture_analysis"])
        detail_labels.append("🏛️ Culture")
        detail_tabs.append("_culture_report")
    if job.get("contact_info"):
        detail_labels.append("👤 Contact")
        detail_tabs.append("contact_info")
    if job.get("interview_prep"):
        detail_labels.append("🎯 Interview Prep")
        detail_tabs.append("interview_prep")

    if detail_labels:
        chosen = st.radio(
            "View details",
            ["—"] + detail_labels,
            horizontal=True,
            key=f"detail_{job['url'][-30:]}",
            label_visibility="collapsed",
        )
        if chosen != "—":
            idx = detail_labels.index(chosen)
            field = detail_tabs[idx]
            with st.container():
                st.text_area(
                    chosen,
                    job[field],
                    height=220,
                    key=f"ta_{field}_{job['url'][-20:]}",
                )

    col_a, col_b, _ = st.columns([1, 1, 4])
    with col_a:
        st.link_button("Apply →", job.get("apply_url") or job["url"])
    with col_b:
        if not job.get("applied"):
            if st.button("Mark Applied", key=f"mark_{job['url'][-30:]}"):
                get_db().mark_applied(job["url"])
                st.rerun()

    st.divider()


def render_jobs_tab(filters: dict):
    db = get_db()
    all_jobs = db.get_all_jobs()

    # Summary metrics
    total = len(all_jobs)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Found", total)
    c2.metric("High Match (≥80)", sum(1 for j in all_jobs if (j.get("score") or 0) >= 80))
    c3.metric("Applied", sum(1 for j in all_jobs if j.get("applied")))
    avg = int(sum(j.get("score") or 0 for j in all_jobs) / total) if total else 0
    c4.metric("Avg Score", avg)

    # Score distribution
    if total > 3:
        try:
            import plotly.express as px
            df_all = pd.DataFrame(all_jobs)
            df_all["score"] = df_all["score"].fillna(0).astype(int)
            fig = px.histogram(df_all, x="score", nbins=20,
                               title="Score Distribution",
                               color_discrete_sequence=["#3b82f6"])
            fig.update_layout(height=180, margin=dict(t=30, b=10, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            pass

    st.markdown("---")

    # Filter + sort
    jobs = all_jobs
    jobs = [j for j in jobs if (j.get("score") or 0) >= filters["min_score"]]
    if not filters["show_applied"]:
        jobs = [j for j in jobs if not j.get("applied")]
    if filters["remote_only"]:
        jobs = [j for j in jobs if j.get("is_remote")]
    if filters["source"] != "All":
        jobs = [j for j in jobs if j.get("source") == filters["source"]]
    if filters["search"]:
        q = filters["search"].lower()
        jobs = [j for j in jobs if q in (j.get("title") or "").lower()
                or q in (j.get("company") or "").lower()]

    if filters["sort"] == "Score ↓":
        jobs.sort(key=lambda j: j.get("score") or 0, reverse=True)
    elif filters["sort"] == "Date ↓":
        jobs.sort(key=lambda j: j.get("scraped_at") or "", reverse=True)
    else:
        jobs.sort(key=lambda j: j.get("company") or "")

    st.subheader(f"Showing {len(jobs)} jobs")

    if not jobs:
        st.info("No jobs match your filters. Try lowering the min score.")
        return

    for job in jobs:
        render_job_card(job)

    if st.sidebar.button("⬇️ Export CSV"):
        df = pd.DataFrame(jobs)
        csv = df.drop(columns=["cover_letter", "interview_prep", "company_research",
                                "email_draft", "contact_info"], errors="ignore").to_csv(index=False)
        st.sidebar.download_button("Download CSV", csv, "jobs.csv", "text/csv")


# ── Tab 2: Follow-Ups ─────────────────────────────────────────────────────────

def render_followups_tab():
    st.subheader("📬 Follow-Up Reminders")
    st.caption("Track your submitted applications and know when to follow up.")

    db = get_db()
    all_jobs = db.get_all_jobs()
    applied = [j for j in all_jobs if j.get("applied") and j.get("applied_at")]

    if not applied:
        st.info("No applied jobs yet. Apply to jobs and mark them as Applied to track follow-ups.")
        return

    now = datetime.utcnow()
    CADENCE = [
        {"day": 5,  "label": "First Follow-Up",  "color": "#f59e0b"},
        {"day": 10, "label": "Second Follow-Up",  "color": "#ef4444"},
        {"day": 14, "label": "Final / Archive",   "color": "#6b7280"},
    ]

    overdue = []
    upcoming = []
    for job in applied:
        try:
            applied_at = datetime.fromisoformat(job["applied_at"])
        except Exception:
            continue
        days = (now - applied_at).days
        for step in CADENCE:
            if days >= step["day"]:
                overdue.append({**job, "_days": days, "_label": step["label"], "_color": step["color"]})
                break
        else:
            next_step = CADENCE[0]
            days_until = next_step["day"] - days
            upcoming.append({**job, "_days": days, "_days_until": days_until})

    if overdue:
        st.markdown(f"### ⚠️ Action Needed ({len(overdue)})")
        for job in sorted(overdue, key=lambda j: j["_days"], reverse=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{job['title']}** @ {job['company']}")
                st.caption(f"Applied {job['_days']} days ago — {job['_label']}")
            with col2:
                st.markdown(
                    f'<span style="background:{job["_color"]};color:white;'
                    f'padding:4px 10px;border-radius:8px;font-size:12px;">'
                    f'{job["_label"]}</span>',
                    unsafe_allow_html=True,
                )
            st.link_button("View Job →", job["url"])
            st.divider()

    if upcoming:
        st.markdown(f"### 🕐 Upcoming Follow-Ups ({len(upcoming)})")
        for job in upcoming:
            st.markdown(
                f"**{job['title']}** @ {job['company']} — "
                f"applied {job['_days']} days ago, "
                f"follow up in **{job['_days_until']} days**"
            )

    st.markdown("---")
    st.markdown("**All Applied Jobs**")
    df = pd.DataFrame([{
        "Title": j["title"], "Company": j["company"],
        "Score": j.get("score", ""), "Applied At": j.get("applied_at", ""),
    } for j in applied])
    st.dataframe(df, use_container_width=True)


# ── Tab 3: Upskill ────────────────────────────────────────────────────────────

def render_upskill_tab():
    st.subheader("📚 Skill Gap Analysis")
    st.caption("Weekly analysis of skills demanded across all scraped jobs vs. your resume.")

    # Find latest report
    reports = sorted(Path(".").glob("upskill_report_*.md"), reverse=True)
    if not reports:
        st.info(
            "No upskill report yet. Run `python main.py --upskill` to generate one, "
            "or wait for the weekly automatic run."
        )
        return

    selected = st.selectbox(
        "Select report",
        reports,
        format_func=lambda p: p.name.replace("upskill_report_", "").replace(".md", "").replace("_", " "),
    )
    content = Path(selected).read_text(encoding="utf-8")
    st.markdown(content)

    with open(selected, "rb") as f:
        st.download_button("⬇️ Download Report", f, file_name=selected.name)


# ── Tab 4: Story Bank ─────────────────────────────────────────────────────────

def render_story_bank_tab():
    st.subheader("🏆 STAR Story Bank")
    st.caption("Cumulative bank of interview stories extracted from your interview prep sessions.")

    import json
    bank_path = Path("star_story_bank.json")
    if not bank_path.exists():
        st.info(
            "Story bank is empty. Generate interview prep for high-scoring jobs "
            "(score ≥ 80) to start building your story bank automatically."
        )
        return

    try:
        stories = json.loads(bank_path.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"Could not read story bank: {e}")
        return

    if not stories:
        st.info("Story bank is empty.")
        return

    st.success(f"**{len(stories)} STAR stories** in your bank")
    st.markdown("---")

    search = st.text_input("🔍 Filter stories", "")

    for i, story in enumerate(stories, 1):
        if search and search.lower() not in str(story).lower():
            continue
        with st.expander(f"**{i}. {story.get('title', f'Story {i}')}**"):
            col_s, col_t = st.columns(2)
            with col_s:
                st.markdown(f"**Situation:** {story.get('situation', '—')}")
                st.markdown(f"**Task:** {story.get('task', '—')}")
            with col_t:
                st.markdown(f"**Action:** {story.get('action', '—')}")
                st.markdown(f"**Result:** {story.get('result', '—')}")
            if story.get("reflection"):
                st.markdown(f"**Reflection:** {story['reflection']}")
            if story.get("applicable_questions"):
                qs = story["applicable_questions"]
                st.caption("Answers: " + " | ".join(qs[:5]))

    st.markdown("---")
    with open(bank_path, "rb") as f:
        st.download_button("⬇️ Export Story Bank (JSON)", f, file_name="star_story_bank.json")


# ── Tab 5: Mock Interview ─────────────────────────────────────────────────────

def render_mock_interview_tab():
    st.subheader("🎤 Mock Interview Simulator")
    st.caption("Practice with an AI interviewer. Get scored, critiqued, and coached after every answer.")

    db = get_db()
    jobs = db.get_all_jobs(limit=100)
    high_score_jobs = [j for j in jobs if (j.get("score") or 0) >= 70]

    if not high_score_jobs:
        st.info("No high-scoring jobs yet. Run the agent to find and score jobs first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        job_options = {f"{j['title']} @ {j['company']}": j for j in high_score_jobs}
        selected_label = st.selectbox("Select Job to Interview For", list(job_options.keys()))
        selected_job = job_options[selected_label]
    with col2:
        round_type = st.selectbox("Interview Round", ["behavioral", "technical", "system_design", "culture_fit"])

    # Session state for interview
    session_key = f"interview_{selected_job.get('url', '')[:20]}_{round_type}"
    if session_key not in st.session_state:
        st.session_state[session_key] = None
        st.session_state[f"{session_key}_history"] = []
        st.session_state[f"{session_key}_done"] = False

    import yaml
    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
        with open(config.get("profile", {}).get("resume_path", "resume.txt"), encoding="utf-8", errors="ignore") as f:
            resume = f.read()
    except Exception:
        st.error("Could not load config.yaml or resume.txt")
        return

    from ai.mock_interview import MockInterview
    mi = MockInterview(config, resume)

    if st.button("🚀 Start New Interview", type="primary"):
        session = mi.new_session(selected_job, round_type)
        opening = session.start()
        st.session_state[session_key] = session
        st.session_state[f"{session_key}_history"] = [{"role": "interviewer", "text": opening}]
        st.session_state[f"{session_key}_done"] = False
        st.rerun()

    session = st.session_state.get(session_key)
    history = st.session_state.get(f"{session_key}_history", [])
    done = st.session_state.get(f"{session_key}_done", False)

    if history:
        st.markdown("---")
        st.markdown("### Interview in Progress")
        for turn in history:
            role = turn["role"]
            text = turn["text"]
            if role == "interviewer":
                st.markdown(f"**🎙️ Interviewer:** {text}")
            else:
                st.markdown(f"**👤 You:** {text}")
            if turn.get("feedback"):
                with st.expander("📊 Feedback on your answer"):
                    st.markdown(turn["feedback"])

        if not done and session:
            answer = st.text_area("Your answer:", height=120, key=f"answer_{len(history)}")
            if st.button("Submit Answer"):
                if answer.strip():
                    result = session.answer(answer)
                    history.append({"role": "candidate", "text": answer, "feedback": result.get("feedback", "")})
                    if result.get("done"):
                        st.session_state[f"{session_key}_done"] = True
                        scorecard = session.get_scorecard()
                        st.session_state[f"{session_key}_scorecard"] = scorecard
                    elif result.get("next_question"):
                        history.append({"role": "interviewer", "text": result["next_question"]})
                    st.session_state[f"{session_key}_history"] = history
                    st.rerun()

        if done:
            st.success("Interview Complete!")
            scorecard = st.session_state.get(f"{session_key}_scorecard", {})
            if scorecard:
                st.markdown("### 📊 Scorecard")
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Overall Score", f"{scorecard.get('overall_score', '?')}/10")
                col_b.metric("Recommendation", scorecard.get("hire_recommendation", "?"))
                col_c.metric("Readiness", scorecard.get("interview_readiness", "?"))
                st.markdown(f"**Advice:** {scorecard.get('specific_advice', '')}")
                st.markdown("**Strengths:** " + " | ".join(scorecard.get("strengths", [])))
                st.markdown("**Improve:** " + " | ".join(scorecard.get("improvements", [])))


# ── Tab 6: Career Advisor ─────────────────────────────────────────────────────

def render_career_advisor_tab():
    st.subheader("🧭 Career Path Advisor")
    st.caption("Strategic career guidance — what roles to target now, skill gaps, 90-day action plan.")

    import json
    from pathlib import Path

    advice_path = Path("career_advice.json")
    md_path = Path("career_advice.md")

    col1, col2 = st.columns([3, 1])
    with col1:
        target_role = st.text_input("Your target role", "Senior Software Engineer / Staff Engineer")
        timeline = st.selectbox("Timeline", ["1-2 years", "2-3 years", "3-5 years"])
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        generate = st.button("🔄 Generate Advice", type="primary")

    if generate:
        import yaml
        try:
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            with open(config.get("profile", {}).get("resume_path", "resume.txt"), encoding="utf-8", errors="ignore") as f:
                resume = f.read()
        except Exception as e:
            st.error(f"Could not load config: {e}")
            return

        from ai.career_advisor import CareerAdvisor
        with st.spinner("Analyzing your career trajectory..."):
            advisor = CareerAdvisor(config, resume)
            advice = advisor.get_advice(target_role=target_role, timeline=timeline, force_refresh=True)
            md_path.write_text(CareerAdvisor.format_report(advice), encoding="utf-8")
        st.success("Career advice generated!")
        st.rerun()

    if advice_path.exists():
        try:
            advice = json.loads(advice_path.read_text())

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Current Level", advice.get("current_level", "?"))
            sal = advice.get("salary_trajectory", {})
            col_b.metric("Market Rate Now", sal.get("current_market_range", "?"))
            col_c.metric("At Target Role", sal.get("at_target_role", "?"))

            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### Apply for These Titles NOW")
                for t in advice.get("current_titles_to_apply", []):
                    st.success(f"✓ {t}")
                st.markdown("### Stretch Titles")
                for t in advice.get("stretch_titles", []):
                    st.warning(f"↑ {t}")

            with col2:
                st.markdown("### 90-Day Action Plan")
                for step in advice.get("ninety_day_plan", []):
                    st.markdown(f"**Week {step.get('week')}:** {step.get('action')}")

            st.markdown("---")
            st.markdown("### Skill Roadmap")
            skills = advice.get("skill_roadmap", [])
            if skills:
                import pandas as pd
                df = pd.DataFrame(skills)
                st.dataframe(df, use_container_width=True)

            st.markdown("---")
            st.markdown(f"### 💬 Honest Assessment")
            st.info(advice.get("honest_assessment", ""))
            st.warning(f"**Biggest mistake to avoid:** {advice.get('biggest_mistake_to_avoid', '')}")

            if md_path.exists():
                with open(md_path, "rb") as f:
                    st.download_button("⬇️ Download Full Report", f, "career_advice.md")
        except Exception as e:
            st.error(f"Could not load career advice: {e}")
    else:
        st.info("No career advice generated yet. Enter your target role above and click Generate.")


# ── Tab 7: Offer Comparator ───────────────────────────────────────────────────

def render_offer_comparator_tab():
    st.subheader("💼 Offer Comparator")
    st.caption("Compare multiple offers on total comp, equity, growth, and risk. Get negotiation scripts.")

    import json
    from pathlib import Path

    offers_path = Path("job_offers.json")

    # Add new offer form
    with st.expander("➕ Add New Offer"):
        col1, col2 = st.columns(2)
        with col1:
            company = st.text_input("Company")
            title = st.text_input("Role Title")
            base = st.number_input("Base Salary ($)", min_value=0, step=5000)
            bonus_pct = st.number_input("Bonus %", min_value=0, max_value=100, step=5)
            signing = st.number_input("Signing Bonus ($)", min_value=0, step=1000)
        with col2:
            equity = st.number_input("Equity Grant Total ($)", min_value=0, step=10000)
            vest_years = st.number_input("Vest Period (years)", min_value=1, max_value=6, value=4)
            benefits = st.number_input("Benefits Value/yr ($)", min_value=0, step=1000, value=15000)
            stage = st.selectbox("Company Stage", ["Public", "Series D+", "Series B/C", "Series A", "Seed", "Startup"])
            notes = st.text_input("Notes")

        if st.button("Save Offer") and company:
            offer = {
                "company": company, "title": title, "base_salary": base,
                "bonus_pct": bonus_pct, "equity_value": equity, "vest_years": vest_years,
                "signing_bonus": signing, "benefits_value": benefits, "stage": stage, "notes": notes,
            }
            import yaml
            try:
                with open("config.yaml") as f:
                    config = yaml.safe_load(f)
                with open(config.get("profile", {}).get("resume_path", "resume.txt"), encoding="utf-8", errors="ignore") as f:
                    resume = f.read()
                from ai.offer_comparator import OfferComparator
                OfferComparator(config, resume).add_offer(offer)
                st.success(f"Offer from {company} saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving offer: {e}")

    # Display offers
    if offers_path.exists():
        try:
            offers = json.loads(offers_path.read_text())
        except Exception:
            offers = []

        if not offers:
            st.info("No offers added yet. Use the form above to add offers.")
            return

        st.markdown(f"### {len(offers)} Offer(s) Saved")

        # Quick comp table
        rows = []
        for o in offers:
            base = o.get("base_salary", 0)
            bonus = base * (o.get("bonus_pct", 0) / 100)
            equity_annual = (o.get("equity_value", 0) or 0) / max(o.get("vest_years", 4), 1)
            total = base + bonus + equity_annual + o.get("benefits_value", 0)
            rows.append({
                "Company": o.get("company"), "Title": o.get("title"),
                "Base": f"${base:,}", "Bonus": f"${bonus:,.0f}",
                "Equity/yr": f"${equity_annual:,.0f}", "Total/yr": f"${total:,.0f}",
                "Stage": o.get("stage"), "Notes": o.get("notes", ""),
            })
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            career_goal = st.text_input("Your career goal (for AI ranking)", "Senior Engineer")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            compare_btn = st.button("🤖 AI Compare & Negotiate", type="primary")

        if compare_btn:
            import yaml
            try:
                with open("config.yaml") as f:
                    config = yaml.safe_load(f)
                with open(config.get("profile", {}).get("resume_path", "resume.txt"), encoding="utf-8", errors="ignore") as f:
                    resume = f.read()
                from ai.offer_comparator import OfferComparator
                comparator = OfferComparator(config, resume)
                with st.spinner("Analyzing offers..."):
                    result = comparator.compare(career_goal=career_goal)
                st.session_state["offer_comparison"] = result
            except Exception as e:
                st.error(f"Comparison failed: {e}")

        result = st.session_state.get("offer_comparison")
        if result and "error" not in result:
            st.markdown("---")
            st.success(f"**Recommended: {result.get('recommended_offer', '?')}** — {result.get('recommendation_reason', '')}")

            for r in result.get("ranking", []):
                with st.expander(f"#{r.get('rank')} {r.get('company')} — {r.get('total_comp_estimate', '')}"):
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("4yr Equity", r.get("equity_value_4yr", "?"))
                    col_b.metric("Career Growth", f"{r.get('career_growth_score', '?')}/10")
                    col_c.metric("Negotiate Potential", r.get("negotiation_potential", "?"))
                    st.markdown("**Pros:** " + " | ".join(r.get("pros", [])))
                    st.markdown("**Cons:** " + " | ".join(r.get("cons", [])))

            pb = result.get("negotiation_playbook", {})
            if pb:
                st.markdown("---")
                st.markdown("### 💬 Negotiation Playbook")
                st.markdown(f"**Best to negotiate:** {pb.get('best_offer_to_negotiate', '?')}")
                st.markdown(f"**Ask for:** {pb.get('counter_offer_range', '?')}")
                st.info(f"**Say this:** \"{pb.get('opening_line', '')}\"")
                st.markdown(f"**Walk-away number:** {pb.get('walk_away_number', '?')}")

                questions = result.get("questions_to_ask", [])
                if questions:
                    st.markdown("**Questions to ask before signing:**")
                    for q in questions:
                        st.markdown(f"- {q}")
    else:
        st.info("No offers yet. Add your first offer using the form above.")


# ── Main ──────────────────────────────────────────────────────────────────────

def render_quota_widget(db):
    """Top-of-page daily quota + streak widget."""
    import yaml
    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
        from ai.daily_routine import DailyRoutine
        routine = DailyRoutine(config)
        widgets = routine.get_dashboard_widgets(db)
        quota = widgets["quota"]
        fatigue = widgets["fatigue"]

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Today's Apps", f"{quota['applied_today']}/{quota['quota']}")
        col2.metric("Streak 🔥", f"{quota['streak']} days")
        col3.metric("Response Rate", f"{widgets['response_stats'].get('response_rate', 0)}%")
        col4.metric("Fatigue", fatigue["fatigue_level"])

        pct = quota["percentage"]
        bar_color = "🟢" if pct >= 80 else "🟡" if pct >= 40 else "🔴"
        col5.markdown(f"**Progress:** {bar_color} {pct}%")

        if fatigue["fatigue_score"] >= 6:
            st.warning(f"⚠️ High fatigue detected. {fatigue['recommendations'][0] if fatigue['recommendations'] else ''}")

        milestone = widgets.get("milestone")
        if milestone:
            st.balloons()
            st.success(milestone)
    except Exception:
        pass


def render_pipeline_tab():
    """Kanban-style interview pipeline view."""
    st.subheader("🗂️ Interview Pipeline")
    st.caption("Track every application through the full interview process.")

    db = get_db()
    pipeline = db.get_pipeline()

    STAGE_LABELS = {
        "applied": "📨 Applied",
        "phone_screen": "📞 Phone Screen",
        "technical": "💻 Technical",
        "system_design": "🏗️ System Design",
        "onsite": "🏢 Onsite",
        "offer": "🎉 Offer",
        "negotiating": "💰 Negotiating",
        "accepted": "✅ Accepted",
        "rejected": "❌ Rejected",
        "withdrawn": "🚪 Withdrawn",
    }

    ACTIVE_STAGES = ["applied", "phone_screen", "technical", "system_design", "onsite", "offer", "negotiating"]

    # Active pipeline
    st.markdown("### Active Applications")
    cols = st.columns(len(ACTIVE_STAGES))
    for i, stage in enumerate(ACTIVE_STAGES):
        with cols[i]:
            jobs_in_stage = pipeline.get(stage, [])
            st.markdown(f"**{STAGE_LABELS[stage]}**")
            st.markdown(f"*{len(jobs_in_stage)} jobs*")
            for job in jobs_in_stage[:4]:
                score = job.get("score") or 0
                color = score_color(score)
                st.markdown(
                    f'<div style="border:1px solid #e5e7eb;border-radius:6px;padding:6px;margin:4px 0;font-size:12px;">'
                    f'<b>{job.get("title","")[:20]}</b><br>'
                    f'{job.get("company","")[:18]}<br>'
                    f'<span style="background:{color};color:white;padding:1px 5px;border-radius:4px;">{score}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # Stage update tool
    st.markdown("---")
    st.markdown("### Update Application Stage")
    all_jobs = db.get_all_jobs(limit=200)
    applied_jobs = [j for j in all_jobs if j.get("applied")]
    if applied_jobs:
        col1, col2, col3 = st.columns(3)
        with col1:
            options = {f"{j['title']} @ {j['company']}": j for j in applied_jobs}
            selected_label = st.selectbox("Application", list(options.keys()))
            selected_job = options[selected_label]
        with col2:
            new_stage = st.selectbox("New Stage", list(STAGE_LABELS.keys())[1:])
        with col3:
            notes = st.text_input("Notes (optional)")
            if st.button("Update Stage", type="primary"):
                db.update_stage(selected_job["url"], new_stage, notes)
                st.success(f"Updated to {STAGE_LABELS[new_stage]}")
                st.rerun()

    # Outcomes summary
    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### ✅ Accepted")
        for j in pipeline.get("accepted", []):
            st.success(f"{j.get('title')} @ {j.get('company')}")

    with col_b:
        st.markdown("### ❌ Rejected")
        for j in pipeline.get("rejected", [])[:10]:
            reason = j.get("rejection_reason", "")
            st.error(f"{j.get('title')} @ {j.get('company')}" + (f" — {reason}" if reason else ""))


def main():
    filters = sidebar()

    st.title("🤖 AI Job Agent — Your Personal Consultant")

    # Quota widget always visible at top
    render_quota_widget(get_db())
    st.markdown("---")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "🎯 Jobs", "🗂️ Pipeline", "📬 Follow-Ups", "📚 Upskill",
        "🏆 Story Bank", "🎤 Mock Interview", "🧭 Career Advisor", "💼 Offer Comparator"
    ])

    with tab1:
        render_jobs_tab(filters)

    with tab2:
        render_pipeline_tab()

    with tab3:
        render_followups_tab()

    with tab4:
        render_upskill_tab()

    with tab5:
        render_story_bank_tab()

    with tab6:
        render_mock_interview_tab()

    with tab7:
        render_career_advisor_tab()

    with tab8:
        render_offer_comparator_tab()


if __name__ == "__main__":
    main()
