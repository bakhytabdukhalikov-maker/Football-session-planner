"""Builds a training session from the drill library.

How it works:
1. The library filters drills that fit the user's setup (age, players,
   equipment, space) and ranks them by focus.
2. The AI (Groq) receives ONLY this shortlist and returns drill IDs,
   minutes, area sizes and a short adaptation note per drill.
3. We validate the AI answer: every ID must be in the shortlist for the
   right phase, and the structure must be correct. If it isn't, we retry
   once with the error, then fall back to a rule-based plan.
4. All facts shown to the user (name, description, coaching points,
   "inspired by") come from the library, never from the AI.
"""

import json
import logging
import os
from typing import Callable, Optional

from app.library import SCALE_FACTOR, DrillLibrary
from app.models import PHASES, SPACE_OPTIONS, Drill, SessionDrill, SessionPlan, SessionRequest

log = logging.getLogger("planner")

# How many candidates per phase we show the AI (keeps prompts small).
SHORTLIST_SIZE = {"warm_up": 5, "main": 8, "game": 4, "cool_down": 2}

# Share of the session for each phase.
PHASE_SHARE = {"warm_up": 0.20, "main": 0.50, "game": 0.20, "cool_down": 0.10}

MIN_BLOCK_MINUTES = 4

LLM = Callable[[list[dict]], str]  # takes chat messages, returns the reply text


class PlanError(Exception):
    """The AI answer broke a rule (unknown drill, wrong structure...)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def main_drill_count(session_length: int) -> tuple[int, int]:
    """Allowed (min, max) number of main-part drills for a session length."""
    if session_length <= 50:
        return 2, 2
    if session_length <= 75:
        return 2, 3
    return 3, 4


def phase_targets(session_length: int) -> dict[str, int]:
    targets = {p: round(session_length * share) for p, share in PHASE_SHARE.items()}
    targets["main"] += session_length - sum(targets.values())  # fix rounding
    return targets


def build_shortlist(req: SessionRequest, lib: DrillLibrary) -> dict[str, list[Drill]]:
    groups = lib.candidates_by_phase(
        mode=req.mode,
        age_group=req.age_group,
        equipment=req.equipment,
        space=req.space,
        focus=req.focus,
        players=req.players,
        has_partner=req.has_partner,
        position=req.position,
    )
    shortlist = {p: groups[p][: SHORTLIST_SIZE[p]] for p in PHASES}
    missing = [p for p in PHASES if not shortlist[p]]
    if missing:
        raise PlanError(
            "No suitable drills for: " + ", ".join(missing)
            + ". Try adding equipment, more space, or a partner."
        )
    return shortlist


def default_area(drill: Drill, space: str) -> tuple[int, int]:
    """Drill's listed area, shrunk if needed to fit the available space."""
    avail_l, avail_w = SPACE_OPTIONS[space]
    length, width = drill.space.length_m, drill.space.width_m
    if length > avail_l or width > avail_w:
        factor = max(SCALE_FACTOR, min(avail_l / length, avail_w / width))
        length, width = round(length * factor), round(width * factor)
    return min(length, avail_l), min(width, avail_w)


def clamp_area(drill: Drill, space: str, length: Optional[int], width: Optional[int]) -> tuple[int, int]:
    """Keep the AI's area within sensible limits; use the default if missing."""
    if not isinstance(length, int) or not isinstance(width, int):
        return default_area(drill, space)
    avail_l, avail_w = SPACE_OPTIONS[space]
    min_l = max(5, round(drill.space.length_m * 0.5))
    min_w = max(5, round(drill.space.width_m * 0.5))
    return (
        max(min_l, min(length, avail_l, drill.space.length_m * 2)),
        max(min_w, min(width, avail_w, drill.space.width_m * 2)),
    )


def fit_minutes(blocks: list[dict], total: int) -> None:
    """Adjust block minutes in place so they add up exactly to `total`.

    First respects each drill's min/max duration, then (if still needed)
    stretches or shortens the main-part drills.
    """
    for b in blocks:
        d = b["drill"].duration
        b["minutes"] = max(d.min, min(d.max, b["minutes"]))

    order = ["main", "game", "warm_up", "cool_down"]
    ranked = sorted(blocks, key=lambda b: order.index(b["phase"]))

    diff = total - sum(b["minutes"] for b in blocks)
    # Pass 1: within each drill's own limits
    while diff != 0:
        moved = False
        for b in ranked:
            d = b["drill"].duration
            if diff > 0 and b["minutes"] < d.max:
                b["minutes"] += 1
                diff -= 1
                moved = True
            elif diff < 0 and b["minutes"] > d.min:
                b["minutes"] -= 1
                diff += 1
                moved = True
            if diff == 0:
                break
        if not moved:
            break
    # Pass 2: stretch/shorten main drills (then others) beyond their limits
    while diff != 0:
        moved = False
        for b in ranked:
            if diff > 0:
                b["minutes"] += 1
                diff -= 1
                moved = True
            elif b["minutes"] > MIN_BLOCK_MINUTES:
                b["minutes"] -= 1
                diff += 1
                moved = True
            if diff == 0:
                break
        if not moved:
            break


def players_setup(drill: Drill, req: SessionRequest) -> str:
    if req.mode == "individual":
        text = "1 player"
        if drill.needs_partner:
            text += " + partner/coach"
        return text
    n = req.players
    if n > drill.players.max and drill.players.parallel_groups:
        groups = -(-n // drill.players.ideal)  # ceiling division
        text = f"{n} players in {groups} groups"
    else:
        text = f"{n} players"
    if drill.players.note:
        text += f" ({drill.players.note})"
    return text


def to_session_drill(block: dict, req: SessionRequest) -> SessionDrill:
    d: Drill = block["drill"]
    length, width = block["area"]
    return SessionDrill(
        phase=block["phase"],
        drill_id=d.id,
        name=d.name,
        minutes=block["minutes"],
        area=f"{length} x {width} m",
        players_setup=players_setup(d, req),
        work_rest=block.get("work_rest") or d.work_rest,
        adaptation_note=block.get("adaptation_note") or "",
        equipment=sorted(set(d.equipment) | (set(d.equipment_optional) & set(req.equipment))),
        description=d.description,
        coaching_points=d.coaching_points,
        progressions=d.progressions,
        regressions=d.regressions,
        trains=d.trains,
        focus=d.focus,
        inspired_by=d.attribution.inspired_by,
        attribution_level=d.attribution.level,
        reference=d.attribution.reference,
    )


def finish_plan(blocks: list[dict], req: SessionRequest, title: str, summary: str, by: str) -> SessionPlan:
    blocks.sort(key=lambda b: PHASES.index(b["phase"]))  # stable: keeps main order
    fit_minutes(blocks, req.session_length)
    drills = [to_session_drill(b, req) for b in blocks]
    return SessionPlan(
        title=title,
        summary=summary,
        mode=req.mode,
        age_group=req.age_group,
        players=req.players,
        session_length=req.session_length,
        total_minutes=sum(d.minutes for d in drills),
        focus=req.focus,
        generated_by=by,
        drills=drills,
    )


def pretty(focus: list[str]) -> str:
    return ", ".join(f.replace("_", " ") for f in focus)


# ---------------------------------------------------------------------------
# Rule-based fallback (works without AI)
# ---------------------------------------------------------------------------

def fallback_plan(req: SessionRequest, shortlist: dict[str, list[Drill]]) -> SessionPlan:
    targets = phase_targets(req.session_length)
    n_main = min(main_drill_count(req.session_length)[0], len(shortlist["main"]))

    blocks, used = [], set()
    # Pick the main part first (most important), then the rest, never repeating a drill
    # unless a phase has no other option.
    for phase in ["main", "game", "warm_up", "cool_down"]:
        want = n_main if phase == "main" else 1
        fresh = [d for d in shortlist[phase] if d.id not in used]
        picks = (fresh or shortlist[phase])[:want]
        used.update(d.id for d in picks)
        for d in picks:
            blocks.append({
                "phase": phase,
                "drill": d,
                "minutes": targets[phase] // len(picks),
                "area": default_area(d, req.space),
            })
    title = f"{pretty(req.focus).title()} session ({req.session_length} min)"
    summary = (
        f"A {req.session_length}-minute {req.mode} session for {req.age_group.replace('_', ' ')} "
        f"focusing on {pretty(req.focus)}. Built from the drill library without AI."
    )
    return finish_plan(blocks, req, title, summary, "fallback")


# ---------------------------------------------------------------------------
# AI plan
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an experienced UEFA-licensed football coach planning a training session.
You may ONLY use drills from the candidate list you are given, referenced by their exact "id".
Never invent drills, names or attributions.

Return ONLY a JSON object with this shape:
{
  "title": "short session title",
  "summary": "2-3 sentences explaining the session's logic and progression",
  "blocks": [
    {
      "phase": "warm_up" | "main" | "game" | "cool_down",
      "drill_id": "id from the candidates for that phase",
      "minutes": integer,
      "area_length_m": integer,
      "area_width_m": integer,
      "work_rest": "sets/reps/rest adapted to the age group and time",
      "adaptation_note": "1-2 sentences: why this drill fits and how to adapt it for this group"
    }
  ]
}

Rules:
- Order: exactly 1 warm_up, then the main drills, then exactly 1 game, then exactly 1 cool_down.
- Each drill_id must come from the candidates of the SAME phase. Use each drill at most once.
- Main drills should build logically (e.g. technical/unopposed -> opposed -> game-like) towards the focus.
- Minutes should add up to the session length and stay within each drill's duration range where possible.
- Areas must fit the available space. Match intensity and complexity to the age group.
"""


def compact(d: Drill) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "focus": d.focus,
        "intensity": d.intensity,
        "players": {"min": d.players.min, "ideal": d.players.ideal, "max": d.players.max},
        "area_m": [d.space.length_m, d.space.width_m],
        "minutes": [d.duration.min, d.duration.default, d.duration.max],
        "work_rest": d.work_rest,
    }


def build_messages(req: SessionRequest, shortlist: dict[str, list[Drill]]) -> list[dict]:
    lo, hi = main_drill_count(req.session_length)
    length, width = SPACE_OPTIONS[req.space]
    brief = {
        "mode": req.mode,
        "age_group": req.age_group,
        "players": req.players if req.mode == "team" else 1,
        "has_partner_or_coach": req.has_partner,
        "position": req.position,
        "session_length_minutes": req.session_length,
        "focus": req.focus,
        "equipment": req.equipment,
        "available_space_m": [length, width],
        "number_of_main_drills": f"{lo}-{hi}" if lo != hi else str(lo),
        "suggested_minutes_per_phase": phase_targets(req.session_length),
    }
    candidates = {p: [compact(d) for d in shortlist[p]] for p in PHASES}
    user = (
        "Session brief:\n" + json.dumps(brief, indent=1)
        + "\n\nCandidate drills by phase:\n" + json.dumps(candidates, indent=1)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_ai_plan(text: str, req: SessionRequest, shortlist: dict[str, list[Drill]]) -> SessionPlan:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanError(f"Reply was not valid JSON: {e}") from e

    raw_blocks = data.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise PlanError("'blocks' must be a non-empty list")

    allowed = {p: {d.id: d for d in shortlist[p]} for p in PHASES}
    used, blocks = set(), []
    for i, b in enumerate(raw_blocks):
        phase, drill_id = b.get("phase"), b.get("drill_id")
        if phase not in allowed:
            raise PlanError(f"Block {i + 1}: unknown phase '{phase}'")
        if drill_id not in allowed[phase]:
            raise PlanError(f"Block {i + 1}: '{drill_id}' is not a {phase} candidate")
        if drill_id in used:
            raise PlanError(f"Block {i + 1}: '{drill_id}' used twice")
        used.add(drill_id)
        drill = allowed[phase][drill_id]
        minutes = b.get("minutes")
        blocks.append({
            "phase": phase,
            "drill": drill,
            "minutes": minutes if isinstance(minutes, int) and minutes > 0 else drill.duration.default,
            "area": clamp_area(drill, req.space, b.get("area_length_m"), b.get("area_width_m")),
            "work_rest": str(b.get("work_rest") or "")[:200],
            "adaptation_note": str(b.get("adaptation_note") or "")[:400],
        })

    counts = {p: sum(1 for b in blocks if b["phase"] == p) for p in PHASES}
    lo, hi = main_drill_count(req.session_length)
    hi = min(hi, len(shortlist["main"]))
    lo = min(lo, hi)
    if counts["warm_up"] != 1 or counts["game"] != 1 or counts["cool_down"] != 1:
        raise PlanError(f"Need exactly 1 warm_up, 1 game and 1 cool_down, got {counts}")
    if not lo <= counts["main"] <= hi:
        raise PlanError(f"Need {lo}-{hi} main drills, got {counts['main']}")

    title = str(data.get("title") or f"{pretty(req.focus).title()} session")[:100]
    summary = str(data.get("summary") or "")[:600]
    return finish_plan(blocks, req, title, summary, "ai")


def groq_chat(messages: list[dict]) -> str:
    """Call Groq. Needs GROQ_API_KEY in the environment."""
    from groq import Groq  # imported here so tests don't need the key

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=40)
    response = client.chat.completions.create(
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=1500,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_session(req: SessionRequest, lib: DrillLibrary, llm: Optional[LLM] = None) -> SessionPlan:
    shortlist = build_shortlist(req, lib)  # raises PlanError if impossible

    if llm is None:
        if not os.environ.get("GROQ_API_KEY"):
            log.warning("GROQ_API_KEY not set - using rule-based fallback")
            return fallback_plan(req, shortlist)
        llm = groq_chat

    messages = build_messages(req, shortlist)
    for attempt in (1, 2):
        try:
            reply = llm(messages)
            return parse_ai_plan(reply, req, shortlist)
        except PlanError as e:
            log.warning("AI plan rejected (attempt %s): %s", attempt, e)
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"That plan broke a rule: {e}. Return a corrected JSON plan."},
            ]
        except Exception as e:  # network error, rate limit, bad key...
            log.error("AI call failed (attempt %s): %s", attempt, e)
            break
    return fallback_plan(req, shortlist)
