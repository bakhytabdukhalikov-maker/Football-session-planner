"""FastAPI app for the football training session planner.

Run locally (from the backend folder):
    uvicorn app.main:app --reload

On Render:
    Root Directory:  backend
    Build Command:   pip install -r requirements.txt
    Start Command:   uvicorn app.main:app --host 0.0.0.0 --port $PORT

Environment variables (set in Render, never in code):
    GROQ_API_KEY   your Groq key (without it, the rule-based fallback is used)
    GROQ_MODEL     optional, e.g. llama-3.3-70b-versatile
    APP_API_KEY    shared secret; the frontend must send it as the X-API-Key header
"""

import logging
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException

from app.library import DrillLibrary
from app.models import AGE_GROUPS, EQUIPMENT, POSITIONS, SPACE_OPTIONS, SessionPlan, SessionRequest
from app.planner import PlanError, generate_session

logging.basicConfig(level=logging.INFO)

# Loaded once at startup. A broken drills.json stops the app with a clear message in the logs.
library = DrillLibrary.load()

app = FastAPI(title="Football Session Planner API", version="1.0")


def check_api_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("APP_API_KEY")
    if not expected:
        return  # no key configured (local development)
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/")
def root():
    return {"message": "Football Session Planner API. See /docs"}


@app.get("/health")
def health():
    return {"status": "ok", "drills": len(library.drills)}


@app.get("/options")
def options():
    """Lists for the frontend dropdowns, taken from the library."""
    return {
        "age_groups": AGE_GROUPS,
        "equipment": EQUIPMENT,
        "spaces": list(SPACE_OPTIONS),
        "positions": POSITIONS,
        "session_lengths": [45, 60, 75, 90],
        "focus": {
            "team": library.focus_options("team"),
            "individual": [f for f in library.focus_options("individual") if f not in POSITIONS],
        },
    }


@app.post("/generate-session", response_model=SessionPlan, dependencies=[Depends(check_api_key)])
def generate(req: SessionRequest):
    try:
        return generate_session(req, library)
    except PlanError as e:
        raise HTTPException(status_code=422, detail=str(e))
