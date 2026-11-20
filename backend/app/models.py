"""Data models and fixed vocabularies for the drill library.

Every drill in data/drills.json must match the Drill model below.
If you add a new focus area or piece of equipment, add it to the
lists here first, otherwise the library will refuse to load.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Ordered from youngest to oldest / lowest to highest level.
AGE_GROUPS = ["U10", "U12", "U14", "U16", "U19", "adult_amateur", "semi_pro"]

PHASES = ["warm_up", "main", "game", "cool_down"]

MODES = ["individual", "team"]

EQUIPMENT = [
    "balls",
    "cones",
    "bibs",
    "mini_goals",
    "full_goals",
    "mannequins",
    "poles",
    "ladder",
    "hurdles",
    "rebound_wall",
]

FOCUS_AREAS = [
    # Team / tactical
    "pressing",
    "counter_pressing",
    "build_up",
    "transitions",
    "positional_play",
    "possession",
    "passing_under_pressure",
    "switching_play",
    "set_pieces",
    "defending",
    "crossing",
    # Individual / technical
    "technique",
    "first_touch",
    "passing",
    "long_passing",
    "finishing",
    "ball_mastery",
    "dribbling",
    "1v1",
    "agility",
    "coordination",
    "scanning",
    "receiving_half_turn",
    # Position-specific (individual mode)
    "position_cm_cdm",
    "position_winger",
    "position_striker",
    "position_fullback",
    "position_cb",
    # General
    "injury_prevention",
    "recovery",
]

# Available space options shown to the user -> (length_m, width_m)
SPACE_OPTIONS = {
    "small_area": (30, 20),
    "half_pitch": (60, 45),
    "full_pitch": (100, 64),
}

TRAINS = ["technical", "tactical", "physical", "cognitive", "recovery"]


class Players(BaseModel):
    min: int = Field(ge=1)
    ideal: int = Field(ge=1)
    max: int = Field(ge=1)
    parallel_groups: bool = False  # True = bigger groups can run several copies side by side
    note: Optional[str] = None

    @model_validator(mode="after")
    def check_order(self):
        if not (self.min <= self.ideal <= self.max):
            raise ValueError("players must satisfy min <= ideal <= max")
        return self


class Space(BaseModel):
    length_m: int = Field(ge=1)
    width_m: int = Field(ge=1)
    scalable: bool = True  # True = can shrink to ~70% if space is tight


class Duration(BaseModel):
    min: int = Field(ge=1)
    default: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def check_order(self):
        if not (self.min <= self.default <= self.max):
            raise ValueError("duration must satisfy min <= default <= max")
        return self


class Attribution(BaseModel):
    inspired_by: str = Field(min_length=10)
    level: Literal["general", "documented"]
    reference: Optional[str] = None

    @model_validator(mode="after")
    def documented_needs_reference(self):
        if self.level == "documented" and not self.reference:
            raise ValueError("attribution level 'documented' needs a reference")
        return self


class Drill(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    modes: list[Literal["individual", "team"]] = Field(min_length=1)
    phases: list[Literal["warm_up", "main", "game", "cool_down"]] = Field(min_length=1)
    focus: list[str] = Field(min_length=1)
    trains: list[str] = Field(min_length=1)
    age_min: str
    age_max: Optional[str] = None
    intensity: Literal["low", "medium", "high"]
    players: Players
    needs_partner: bool = False  # individual mode: needs a coach/partner to pass or call
    equipment: list[str] = Field(default_factory=list)
    equipment_optional: list[str] = Field(default_factory=list)
    space: Space
    duration: Duration
    work_rest: str
    description: str = Field(min_length=20)
    coaching_points: list[str] = Field(min_length=2)
    progressions: list[str] = Field(min_length=1)
    regressions: list[str] = Field(min_length=1)
    attribution: Attribution

    @field_validator("focus")
    @classmethod
    def check_focus(cls, v):
        bad = [f for f in v if f not in FOCUS_AREAS]
        if bad:
            raise ValueError(f"unknown focus area(s): {bad}")
        return v

    @field_validator("trains")
    @classmethod
    def check_trains(cls, v):
        bad = [t for t in v if t not in TRAINS]
        if bad:
            raise ValueError(f"unknown 'trains' value(s): {bad}")
        return v

    @field_validator("equipment", "equipment_optional")
    @classmethod
    def check_equipment(cls, v):
        bad = [e for e in v if e not in EQUIPMENT]
        if bad:
            raise ValueError(f"unknown equipment: {bad}")
        return v

    @field_validator("age_min", "age_max")
    @classmethod
    def check_age(cls, v):
        if v is not None and v not in AGE_GROUPS:
            raise ValueError(f"unknown age group: {v}")
        return v
