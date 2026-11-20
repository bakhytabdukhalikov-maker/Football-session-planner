"""Tests for the planner and the API. No Groq key needed: the AI is faked."""

import json
import itertools

import pytest
from fastapi.testclient import TestClient

from app.library import DrillLibrary
from app.main import app
from app.models import AGE_GROUPS, SessionRequest
from app.planner import build_shortlist, fallback_plan, generate_session

lib = DrillLibrary.load()
client = TestClient(app)

TEAM = dict(mode="team", age_group="U19", players=14, session_length=90,
            focus=["counter_pressing"], equipment=["balls", "cones", "bibs", "mini_goals"],
            space="half_pitch")
SOLO = dict(mode="individual", age_group="U19", session_length=60,
            focus=["scanning"], equipment=["balls", "cones"], space="small_area",
            position="position_cm_cdm", has_partner=True)


def check_plan(plan, req):
    assert plan.total_minutes == req.session_length
    phases = [d.phase for d in plan.drills]
    assert phases[0] == "warm_up" and phases[-1] == "cool_down"
    assert phases.count("game") == 1
    ids = [d.drill_id for d in plan.drills]
    if req.mode == "team" and req.equipment != ["balls", "cones"]:
        assert len(ids) == len(set(ids))          # no repeats when there's enough choice
    for d in plan.drills:
        assert d.drill_id in lib.by_id            # nothing invented
        assert d.inspired_by == lib.by_id[d.drill_id].attribution.inspired_by
        assert d.minutes >= 4


@pytest.mark.parametrize(
    "mode,age,length",
    list(itertools.product(["team", "individual"], AGE_GROUPS, [45, 60, 90])),
)
def test_fallback_always_valid(mode, age, length):
    req = SessionRequest(mode=mode, age_group=age, players=10, session_length=length,
                         focus=["passing"], equipment=["balls", "cones"], space="small_area")
    plan = fallback_plan(req, build_shortlist(req, lib))
    check_plan(plan, req)
    assert plan.generated_by == "fallback"


def fake_llm_good(messages):
    return json.dumps({
        "title": "Counter-pressing",
        "summary": "Win it back fast.",
        "blocks": [
            {"phase": "warm_up", "drill_id": "fifa_11plus", "minutes": 18},
            {"phase": "main", "drill_id": "rondo_4v2", "minutes": 14, "area_length_m": 12, "area_width_m": 12},
            {"phase": "main", "drill_id": "pressing_triggers_6v4", "minutes": 15},
            {"phase": "main", "drill_id": "counterpress_transition_game", "minutes": 18},
            {"phase": "game", "drill_id": "conditioned_game", "minutes": 18, "adaptation_note": "Double goals after regains."},
            {"phase": "cool_down", "drill_id": "cool_down_jog_stretch", "minutes": 7},
        ],
    })


def test_ai_plan_accepted():
    req = SessionRequest(**TEAM)
    plan = generate_session(req, lib, llm=fake_llm_good)
    assert plan.generated_by == "ai"
    check_plan(plan, req)
    assert plan.drills[1].area == "12 x 12 m"


def test_invented_drill_rejected_then_fallback():
    calls = []

    def fake_llm_invents(messages):
        calls.append(1)
        return json.dumps({"title": "x", "blocks": [
            {"phase": "warm_up", "drill_id": "klopp_secret_drill", "minutes": 20}]})

    req = SessionRequest(**TEAM)
    plan = generate_session(req, lib, llm=fake_llm_invents)
    assert len(calls) == 2                 # retried once
    assert plan.generated_by == "fallback"
    check_plan(plan, req)


def test_llm_error_falls_back():
    def broken(messages):
        raise RuntimeError("rate limited")

    plan = generate_session(SessionRequest(**SOLO), lib, llm=broken)
    assert plan.generated_by == "fallback"


def test_api_generate_and_options(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("APP_API_KEY", raising=False)
    assert client.get("/health").json()["status"] == "ok"
    assert "team" in client.get("/options").json()["focus"]
    r = client.post("/generate-session", json=SOLO)
    assert r.status_code == 200, r.text
    assert r.json()["total_minutes"] == 60


def test_api_key_required(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "secret123")
    assert client.post("/generate-session", json=SOLO).status_code == 401
    r = client.post("/generate-session", json=SOLO, headers={"X-API-Key": "secret123"})
    assert r.status_code == 200


def test_bad_input_rejected(monkeypatch):
    monkeypatch.delenv("APP_API_KEY", raising=False)
    bad = dict(SOLO, focus=["flying"])
    assert client.post("/generate-session", json=bad).status_code == 422


def test_impossible_setup_gives_clear_error(monkeypatch):
    monkeypatch.delenv("APP_API_KEY", raising=False)
    nothing = dict(SOLO, equipment=[], has_partner=False)
    r = client.post("/generate-session", json=nothing)
    assert r.status_code == 422
    assert "No suitable drills" in r.json()["detail"]
