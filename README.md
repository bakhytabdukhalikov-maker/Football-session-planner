# Football Session Planner

**Live demo:** https://football-session-planner.streamlit.app/

> The backend runs on Render's free tier, so the first request after a quiet period can take up to a minute while the server wakes up.

AI-assisted football training session planner. A coach or player enters the
age group, number of players, session length, focus, equipment and space, and
gets a complete session (warm-up, main part, game, cool-down) with a PDF export.

## How it avoids made-up drills

- Every drill comes from a curated library: `backend/app/data/drills.json`.
- The backend filters the library to drills that fit the setup, and the AI
  (Groq) only picks drill IDs, minutes and area sizes from that shortlist.
- The answer is validated. Unknown drills are rejected, and if the AI fails,
  a rule-based planner builds the session instead.
- Drill descriptions, coaching points and "inspired by" notes always come from
  the library, with honest, general attributions unless a source is documented.

## Tech

- Backend: Python, FastAPI, Pydantic, Groq API (deployed on Render)
- Frontend: Streamlit with fpdf2 for PDF export (Streamlit Community Cloud)

## Project structure

```
backend/
  app/main.py        API endpoints (/health, /options, /generate-session)
  app/planner.py     shortlist -> AI -> validation -> fallback
  app/library.py     loads, validates and filters the drill library
  app/models.py      data models and vocabularies
  app/data/drills.json
  tests/
frontend/
  app.py             Streamlit UI
  pdf_export.py      PDF builder
```

## Run locally

```bash
cd backend
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload        # API on http://localhost:8000/docs

cd ../frontend
pip install -r requirements.txt
streamlit run app.py
```

Environment variables (backend): `GROQ_API_KEY`, optional `GROQ_MODEL`, `APP_API_KEY`.
Streamlit secrets (frontend): `API_URL`, `APP_API_KEY`.
