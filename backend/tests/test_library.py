"""Checks that drills.json loads and that every common setup gets a full session.

Run from the backend folder with:  pytest
"""

import pytest

from app.library import DrillLibrary
from app.models import AGE_GROUPS, PHASES


@pytest.fixture(scope="module")
def lib():
    return DrillLibrary.load()


def test_library_loads(lib):
    assert len(lib.drills) >= 25


def test_ids_unique(lib):
    ids = [d.id for d in lib.drills]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("age", AGE_GROUPS)
def test_team_minimal_setup_has_every_phase(lib, age):
    """Team, 8 players, only balls + cones, small area -> every phase has a drill."""
    groups = lib.candidates_by_phase(
        mode="team", age_group=age, equipment=["balls", "cones"],
        space="small_area", focus=["possession"], players=8,
    )
    for phase in PHASES:
        assert groups[phase], f"No {phase} drill for team {age} minimal setup"


@pytest.mark.parametrize("age", AGE_GROUPS)
def test_individual_alone_minimal_setup_has_every_phase(lib, age):
    """One player, no partner, only balls + cones, small area -> every phase has a drill."""
    groups = lib.candidates_by_phase(
        mode="individual", age_group=age, equipment=["balls", "cones"],
        space="small_area", focus=["dribbling"], has_partner=False,
    )
    for phase in PHASES:
        assert groups[phase], f"No {phase} drill for individual {age} minimal setup"


def test_focus_ranking(lib):
    groups = lib.candidates_by_phase(
        mode="team", age_group="U19", equipment=["balls", "cones", "bibs", "mini_goals"],
        space="half_pitch", focus=["counter_pressing"], players=12,
    )
    assert groups["main"][0].id == "counterpress_transition_game"


def test_partner_filter(lib):
    alone = lib.filter("individual", "U19", ["balls", "cones"], "half_pitch", has_partner=False)
    assert all(not d.needs_partner for d in alone)


def test_age_filter(lib):
    u10 = lib.filter("team", "U10", ["balls", "cones", "full_goals"], "full_pitch", players=12)
    assert all(d.id != "positional_game_4v4_3" for d in u10)
    adults = lib.filter("team", "adult_amateur", ["balls", "cones"], "full_pitch", players=12)
    assert all(d.id != "funino_3v3" for d in adults)
