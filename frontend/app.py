"""Streamlit frontend for the football training session planner.

Secrets (Streamlit Cloud -> App settings -> Secrets), in TOML format:
    API_URL = "https://your-backend.onrender.com"
    APP_API_KEY = "the same secret you set in Render"

Run locally (from the frontend folder):
    streamlit run app.py
"""

import os

import requests
import streamlit as st

from pdf_export import PHASE_LABELS, build_pdf

st.set_page_config(page_title="Football Session Planner", page_icon="⚽", layout="centered")


def secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


API_URL = secret("API_URL", "http://localhost:8000").rstrip("/")
API_KEY = secret("APP_API_KEY")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

AGE_LABELS = {
    "U10": "U10", "U12": "U12", "U14": "U14", "U16": "U16", "U19": "U19",
    "adult_amateur": "Adult amateur", "semi_pro": "Semi-pro",
}
SPACE_LABELS = {
    "small_area": "Small area (about 30 x 20 m)",
    "half_pitch": "Half pitch",
    "full_pitch": "Full pitch",
}
PHASE_ICONS = {"warm_up": "🔥", "main": "🎯", "game": "⚽", "cool_down": "🧘"}


def pretty(value: str) -> str:
    return value.replace("_", " ").replace("position ", "").replace("cm cdm", "CM/CDM").capitalize()


# ---------------------------------------------------------------------------
# Backend calls
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def load_options():
    r = requests.get(f"{API_URL}/options", timeout=90)  # long timeout: Render may be waking up
    r.raise_for_status()
    return r.json()


def generate(payload: dict) -> dict:
    r = requests.post(f"{API_URL}/generate-session", json=payload, headers=HEADERS, timeout=120)
    if r.status_code == 422:
        detail = r.json().get("detail")
        if isinstance(detail, list):  # input validation errors
            detail = "; ".join(str(e.get("msg")) for e in detail)
        raise ValueError(detail)
    if r.status_code == 401:
        raise ValueError("The app's API key doesn't match the backend. Check the secrets.")
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("⚽ Football Session Planner")
st.caption("Realistic training sessions built from a curated library of proven drills.")

try:
    with st.spinner("Connecting to the server... (the first visit can take up to a minute while it wakes up)"):
        options = load_options()
except Exception:
    st.error("Couldn't reach the server. It may still be waking up. Please refresh in a moment.")
    if st.button("Try again"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

mode_label = st.radio("Session type", ["Team", "Individual"], horizontal=True)
mode = mode_label.lower()

with st.form("session_form"):
    col1, col2 = st.columns(2)
    with col1:
        age_group = st.selectbox(
            "Age group / level", options["age_groups"],
            index=options["age_groups"].index("U19") if "U19" in options["age_groups"] else 0,
            format_func=lambda a: AGE_LABELS.get(a, a),
        )
    with col2:
        session_length = st.select_slider("Session length (min)", options["session_lengths"], value=60)

    players = 1
    position = None
    has_partner = False
    if mode == "team":
        players = st.number_input("Number of players", min_value=4, max_value=40, value=14, step=1)
    else:
        position = st.selectbox(
            "Position (optional)", [None] + options["positions"],
            format_func=lambda p: "Any" if p is None else pretty(p),
        )
        has_partner = st.checkbox("A partner or coach is available (to pass and give signals)", value=True)

    focus = st.multiselect(
        "Main focus (up to 3)", options["focus"][mode], max_selections=3,
        format_func=pretty,
    )
    equipment = st.multiselect(
        "Available equipment", options["equipment"], default=["balls", "cones"], format_func=pretty,
    )
    space = st.selectbox("Available space", options["spaces"], format_func=lambda s: SPACE_LABELS.get(s, s))

    submitted = st.form_submit_button("Generate session", type="primary", use_container_width=True)

if submitted:
    if not focus:
        st.warning("Pick at least one focus.")
    else:
        payload = {
            "mode": mode,
            "age_group": age_group,
            "players": int(players),
            "session_length": int(session_length),
            "focus": focus,
            "equipment": equipment,
            "space": space,
            "position": position,
            "has_partner": has_partner,
        }
        try:
            with st.spinner("Planning your session..."):
                st.session_state["plan"] = generate(payload)
        except ValueError as e:
            st.error(str(e))
        except requests.Timeout:
            st.error("The server took too long. Please try again.")
        except Exception as e:
            st.error(f"Something went wrong: {e}")

# ---------------------------------------------------------------------------
# Show the plan (kept in session_state so the download button doesn't clear it)
# ---------------------------------------------------------------------------

plan = st.session_state.get("plan")
if plan:
    st.divider()
    st.header(plan["title"])
    who = f"{plan['players']} players" if plan["mode"] == "team" else "Individual"
    st.caption(
        f"{AGE_LABELS.get(plan['age_group'], plan['age_group'])} · {who} · "
        f"{plan['total_minutes']} min · Focus: {', '.join(pretty(f) for f in plan['focus'])}"
    )
    if plan.get("summary"):
        st.write(plan["summary"])
    if plan["generated_by"] == "fallback":
        st.info("The AI wasn't available, so this plan was built directly from the drill library.")

    st.download_button(
        "📄 Download PDF", data=build_pdf(plan),
        file_name=f"session_{plan['age_group']}_{plan['session_length']}min.pdf",
        mime="application/pdf", use_container_width=True,
    )

    st.subheader("Overview")
    for d in plan["drills"]:
        st.markdown(
            f"{PHASE_ICONS.get(d['phase'], '')} **{PHASE_LABELS[d['phase']]}** · "
            f"{d['minutes']} min · {d['name']}"
        )

    st.subheader("Drills")
    for n, d in enumerate(plan["drills"], start=1):
        with st.expander(f"{n}. {PHASE_LABELS[d['phase']]}: {d['name']} ({d['minutes']} min)", expanded=n == 2):
            st.markdown(
                f"**Area:** {d['area']}  \n"
                f"**Players:** {d['players_setup']}  \n"
                f"**Equipment:** {', '.join(pretty(e) for e in d['equipment']) or 'None'}  \n"
                f"**Timing:** {d['work_rest']}  \n"
                f"**Trains:** {', '.join(d['trains'])}"
            )
            st.markdown("**How it works**")
            st.write(d["description"])
            if d.get("adaptation_note"):
                st.markdown(f"*For this group:* {d['adaptation_note']}")
            st.markdown("**Coaching points**")
            st.markdown("\n".join(f"- {p}" for p in d["coaching_points"]))
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Progressions**")
                st.markdown("\n".join(f"- {p}" for p in d["progressions"]))
            with c2:
                st.markdown("**Regressions**")
                st.markdown("\n".join(f"- {p}" for p in d["regressions"]))
            source = f"Inspired by: {d['inspired_by']}"
            if d.get("reference"):
                source += f" (Source: {d['reference']})"
            st.caption(source)
