"""
UBE Architect v5 — Minimal Adaptive Bar Trainer
- OpenAI Responses API (client.responses.create)
- 12 MEE subjects, Studicata-weighted topic selection
- Adaptive difficulty (correct +1, wrong -1, bounded 1-5)
- SQLite attempt logging with schema migration
- Clean one-page UI; metrics live in sidebar
"""

import re
import random
import sqlite3
from datetime import datetime

import streamlit as st
from openai import OpenAI

# ── Constants ──────────────────────────────────────────────────────────────────

DB_PATH = "ube_v4.db"
MODEL   = "gpt-4o"

MEE_SUBJECTS = [
    "Business Associations",
    "Civil Procedure",
    "Conflict of Laws",
    "Constitutional Law",
    "Contracts",
    "Criminal Law and Procedure",
    "Evidence",
    "Family Law",
    "Real Property",
    "Secured Transactions",
    "Torts",
    "Trusts and Estates",
]

# Studicata MEE appearance rates (1995-2024).
# Used as weights so high-tested rules appear more often.
TOPIC_WEIGHTS = {
    "Business Associations": [
        ("Authority of Agent to Bind Principal", 27.6),
        ("Apparent Authority", 27.6),
        ("Contract Liability of the Partnership", 19.0),
        ("Dissolution of the Partnership", 17.2),
        ("Business Judgment / Duty of Care", 17.2),
        ("Conflicting Interest Transactions", 15.5),
        ("Shareholder Derivative Claims", 15.5),
        ("Actual Authority", 15.5),
        ("General Partnership Formation", 15.5),
        ("Partner Duty of Loyalty", 12.1),
    ],
    "Civil Procedure": [
        ("Diversity Jurisdiction", 34.5),
        ("Citizenship for Diversity Purposes", 20.7),
        ("Federal Question Jurisdiction", 19.0),
        ("Venue", 13.8),
        ("Personal Jurisdiction", 13.8),
        ("Supplemental Jurisdiction", 13.8),
        ("Specific Jurisdiction", 12.1),
        ("Motion for Summary Judgment", 10.3),
        ("Change of Venue", 8.6),
        ("Compulsory Joinder", 8.6),
    ],
    "Conflict of Laws": [
        ("Collateral Estoppel", 8.6),
        ("Erie Doctrine", 8.6),
        ("Choice of Law Approaches", 6.9),
        ("Res Judicata", 5.2),
        ("Express COL Clauses in Contracts", 3.4),
        ("Full Faith and Credit", 3.4),
    ],
    "Constitutional Law": [
        ("State Action Requirement", 9.1),
        ("State Sovereign Immunity", 6.1),
        ("Dormant Commerce Clause", 6.1),
        ("14th Amendment Equal Protection", 6.1),
        ("1st Amendment Free Speech", 6.1),
        ("Commerce Power", 6.1),
        ("Takings Clause (Eminent Domain)", 3.0),
    ],
    "Contracts": [
        ("Common Law vs. UCC", 39.4),
        ("Requirements to Form a Contract", 27.3),
        ("Expectation Damages", 18.2),
        ("Statute of Frauds", 12.1),
        ("Terminating the Offer", 12.1),
        ("Terms Required in the Offer", 12.1),
        ("The Offer", 9.1),
        ("Acceptance", 9.1),
        ("Contract Modification", 9.1),
        ("Mirror Image Rule and UCC 2-207", 9.1),
    ],
    "Criminal Law and Procedure": [
        ("Mental State Requirements", 18.2),
        ("Miranda Analysis", 18.2),
        ("4th Amendment Searches", 15.2),
        ("Larceny", 12.1),
        ("Embezzlement", 9.1),
        ("Plain View", 9.1),
        ("Stop and Frisk (Terry Stop)", 9.1),
        ("Common Law Murder", 6.1),
        ("Voluntary Manslaughter", 6.1),
        ("Involuntary Manslaughter", 6.1),
    ],
    "Evidence": [
        ("Hearsay", 33.3),
        ("Non-Hearsay", 33.3),
        ("Logical Relevance", 30.3),
        ("Character Evidence", 27.3),
        ("M.I.M.I.C.", 24.2),
        ("Unavailability Requirement", 12.1),
        ("Present Sense Impression", 9.1),
        ("Excited Utterance", 9.1),
        ("Medical Diagnosis or Treatment", 9.1),
        ("Impeachment", 9.1),
    ],
    "Family Law": [
        ("Property Division at Divorce", 20.7),
        ("Child Custody: Best Interests", 15.5),
        ("Premarital Contracts", 12.1),
        ("Marital Action Jurisdiction", 12.1),
        ("Common Law Marriage", 8.6),
        ("Modification of Child Support", 8.6),
        ("Modification of Child Custody", 8.6),
    ],
    "Real Property": [
        ("Adverse Possession", 9.1),
        ("Deed Types and Merger", 9.1),
        ("Recording Statutes and Notice", 9.1),
        ("Leasehold Interest", 6.1),
        ("Assignments", 6.1),
        ("Abandonment", 6.1),
        ("Duty to Mitigate", 6.1),
        ("Termination of an Easement", 6.1),
        ("Implied Warranty of Fitness/Suitability", 6.1),
        ("Shelter Rule", 6.1),
    ],
    "Secured Transactions": [
        ("Scope of Article 9", 60.3),
        ("Attachment of the Security Interest", 53.4),
        ("Perfection of the Security Interest", 51.7),
        ("Purchase-Money Security Interest", 24.1),
        ("Perfected vs. Unperfected Interests", 24.1),
        ("Multiple Perfected Creditors", 19.0),
        ("Buyers in the Ordinary Course of Business", 15.5),
        ("Types of Collateral", 15.5),
        ("Right to Dispose of Collateral", 8.6),
        ("Debtor's Rights", 8.6),
    ],
    "Torts": [
        ("Negligence Elements", 39.4),
        ("Respondeat Superior", 24.2),
        ("The Reasonable Person Standard", 15.2),
        ("Actual and Proximate Cause", 15.2),
        ("Strict Liability", 12.1),
        ("Negligence Per Se", 12.1),
        ("Eggshell Plaintiff Rule", 9.1),
        ("Defective Products", 9.1),
        ("Comparative Fault", 9.1),
        ("Affirmative Duty to Act", 9.1),
    ],
    "Trusts and Estates": [
        ("Intestate Succession", 17.2),
        ("Incorporation by Reference", 15.5),
        ("Duty of Care (Trustee)", 13.8),
        ("Devises to Classes", 13.8),
        ("Creation of Express Trusts", 13.8),
        ("Judicial Modification of Trusts", 13.8),
        ("Lapsed Legacies", 12.1),
        ("Revocation of Will by Physical Act", 12.1),
        ("Rule Against Perpetuities", 12.1),
        ("Will Execution Requirements", 10.3),
    ],
}

ERROR_TYPES = [
    "knowledge gap",
    "rule confusion",
    "careless reading",
    "analysis error",
    "distractor trap",
]

# ── Database ───────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            subject         TEXT,
            topic           TEXT,
            question        TEXT,
            selected_answer TEXT,
            correct_answer  TEXT,
            score           INTEGER,
            correct         INTEGER,
            error_type      TEXT,
            difficulty      INTEGER,
            timestamp       TEXT
        )
    """)
    # Migrate legacy schema: add any missing columns without data loss
    existing = {r[1] for r in conn.execute("PRAGMA table_info(attempts)").fetchall()}
    for col, dtype in [("selected_answer","TEXT"), ("correct_answer","TEXT"), ("difficulty","INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE attempts ADD COLUMN {col} {dtype}")
    conn.commit()
    return conn

# ── Helpers ────────────────────────────────────────────────────────────────────

def pick_topic(subject: str) -> str:
    entries = TOPIC_WEIGHTS.get(subject, [])
    if not entries:
        return subject
    topics, weights = zip(*entries)
    return random.choices(topics, weights=weights, k=1)[0]


def build_prompt(subject: str, difficulty: int, topic: str) -> str:
    style = {
        1: "straightforward — test basic rule recall",
        2: "moderate — one small wrinkle in the facts",
        3: "moderately tricky — use a common distractor",
        4: "difficult — subtle rule distinction required",
        5: "very difficult — dense facts, nuanced analysis",
    }.get(difficulty, "moderate")

    return (
        f"You are a UBE/MEE bar exam question drafter.\n\n"
        f"Subject: {subject}\n"
        f"Topic: {topic}\n"
        f"Difficulty: {difficulty}/5 ({style})\n\n"
        f"Write one multiple-choice bar exam question. "
        f"Wrong choices must be plausible but clearly wrong on analysis.\n\n"
        f"Return EXACTLY this format:\n"
        f"FACT PATTERN: [2-4 sentences]\n"
        f"QUESTION: [call of the question]\n"
        f"A) [choice]\n"
        f"B) [choice]\n"
        f"C) [choice]\n"
        f"D) [choice]\n"
        f"CORRECT ANSWER: [single letter A-D]\n"
        f"EXPLANATION: [2-3 sentence legal analysis]"
    )


def parse_response(text: str) -> dict:
    fields = {
        "fact_pattern": r"FACT PATTERN:\s*(.*?)\nQUESTION:",
        "question":     r"QUESTION:\s*(.*?)\nA\)",
        "a":            r"A\)\s*(.*?)\nB\)",
        "b":            r"B\)\s*(.*?)\nC\)",
        "c":            r"C\)\s*(.*?)\nD\)",
        "d":            r"D\)\s*(.*?)\nCORRECT ANSWER:",
        "correct":      r"CORRECT ANSWER:\s*([A-D])",
        "explanation":  r"EXPLANATION:\s*(.+)$",
    }
    return {k: (m.group(1).strip() if (m := re.search(p, text, re.S | re.I)) else "") for k, p in fields.items()}


def ensure_state():
    for k, v in {
        "q_block": None, "correct_answer": None, "explanation": None,
        "topic": "", "gen_subject": "", "difficulty": 2,
        "score": 0, "streak": 0, "total": 0, "answered": False,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ── App ────────────────────────────────────────────────────────────────────────

conn = init_db()
ensure_state()

@st.cache_resource
def get_client():
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

client = get_client()

st.set_page_config(page_title="UBE Architect v5", page_icon="⚖️")
st.title("⚖️ UBE Architect v5")
st.caption("Adaptive bar prep · 12 MEE subjects · Studicata-weighted topics")

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    subject = st.selectbox("Subject", MEE_SUBJECTS)

    acc = round(st.session_state.score * 100 / st.session_state.total, 1) if st.session_state.total else 0
    streak_display = f"{st.session_state.streak} 🔥" if st.session_state.streak >= 3 else st.session_state.streak
    st.caption(
        f"Score: **{st.session_state.score}** | "
        f"Streak: **{streak_display}** | "
        f"Accuracy: **{acc}%** | "
        f"Difficulty: **{st.session_state.difficulty}/5**"
    )

    generate = st.button("⚡ Generate Question", use_container_width=True)

    st.divider()
    if st.button("Reset Session", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ── Generate ───────────────────────────────────────────────────────────────────
if generate:
    topic = pick_topic(subject)
    with st.spinner(f"Drafting a {subject} question on *{topic}*…"):
        try:
            resp = client.responses.create(
                model=MODEL,
                input=build_prompt(subject, st.session_state.difficulty, topic),
                max_output_tokens=800,
            )
            parsed = parse_response(resp.output_text)

            if not parsed["correct"]:
                st.error("Parse failed — try generating again.")
            else:
                st.session_state.q_block = (
                    f"**FACT PATTERN**\n\n{parsed['fact_pattern']}\n\n"
                    f"**QUESTION**\n\n{parsed['question']}\n\n"
                    f"**A)** {parsed['a']}\n\n"
                    f"**B)** {parsed['b']}\n\n"
                    f"**C)** {parsed['c']}\n\n"
                    f"**D)** {parsed['d']}"
                )
                st.session_state.correct_answer = parsed["correct"]
                st.session_state.explanation    = parsed["explanation"]
                st.session_state.topic          = topic
                st.session_state.gen_subject    = subject
                st.session_state.answered       = False

        except Exception as e:
            st.error(f"OpenAI error: {e}")

# ── Question + Answer ──────────────────────────────────────────────────────────
if st.session_state.q_block:
    st.divider()
    st.caption(
        f"📚 {st.session_state.gen_subject} · {st.session_state.topic} · "
        f"Difficulty {st.session_state.difficulty}/5"
    )
    st.markdown(st.session_state.q_block)

    if not st.session_state.answered:
        with st.form("answer_form"):
            user_choice = st.radio("Your answer:", ["A", "B", "C", "D"], index=None, horizontal=True)
            submitted = st.form_submit_button("Submit Answer", use_container_width=True)

        if submitted:
            if not user_choice:
                st.warning("Select an answer first.")
            else:
                correct   = int(user_choice == st.session_state.correct_answer)
                prev_diff = st.session_state.difficulty

                st.session_state.total  += 1
                st.session_state.score  += correct
                st.session_state.streak  = st.session_state.streak + 1 if correct else 0
                st.session_state.difficulty = min(5, prev_diff + 1) if correct else max(1, prev_diff - 1)
                st.session_state.answered   = True

                error_type = "" if correct else random.choice(ERROR_TYPES)
                try:
                    conn.execute(
                        """INSERT INTO attempts
                           (subject, topic, question, selected_answer, correct_answer,
                            score, correct, error_type, difficulty, timestamp)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            st.session_state.gen_subject, st.session_state.topic,
                            st.session_state.q_block, user_choice,
                            st.session_state.correct_answer, st.session_state.score,
                            correct, error_type, prev_diff,
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    conn.commit()
                except Exception as db_err:
                    st.warning(f"DB write error: {db_err}")

                st.rerun()

    else:
        # Feedback
        ca = st.session_state.correct_answer
        if st.session_state.score > 0 and st.session_state.total > 0:
            last_correct = (st.session_state.score == st.session_state.total or
                            st.session_state.streak > 0)
        else:
            last_correct = False

        # Determine last result from DB
        last_row = conn.execute(
            "SELECT correct FROM attempts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last_row and last_row[0]:
            st.success(f"✅ Correct! Difficulty → **{st.session_state.difficulty}/5**")
        else:
            st.error(f"❌ Incorrect. Answer: **{ca}** · Difficulty → **{st.session_state.difficulty}/5**")

        with st.expander("📖 Legal Analysis", expanded=True):
            st.write(st.session_state.explanation)

        if st.button("Next Question →", use_container_width=True):
            st.session_state.q_block  = None
            st.session_state.answered = False
            st.rerun()

else:
    st.info("Select a subject and click **⚡ Generate Question** to begin.")
