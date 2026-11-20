"""Loads, validates and filters the drill library (data/drills.json).

The AI never sees the whole library. The backend first uses
DrillLibrary.candidates_by_phase() to keep only drills that fit the
user's inputs, then sends that shortlist to the AI.
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.models import AGE_GROUPS, MODES, PHASES, SPACE_OPTIONS, Drill

DATA_PATH = Path(__file__).parent / "data" / "drills.json"

SCALE_FACTOR = 0.7  # a "scalable" drill can shrink to 70% of its listed size


class LibraryError(Exception):
    """Raised when drills.json is broken. The message says exactly what is wrong."""


class DrillLibrary:
    def __init__(self, drills: list[Drill]):
        self.drills = drills
        self.by_id = {d.id: d for d in drills}

    # ---------- loading ----------

    @classmethod
    def load(cls, path: Path = DATA_PATH) -> "DrillLibrary":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise LibraryError(
                f"drills.json is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"
            ) from e

        errors, drills, seen = [], [], set()
        for i, item in enumerate(raw.get("drills", [])):
            label = item.get("id", f"drill #{i + 1}")
            try:
                drill = Drill(**item)
            except ValidationError as e:
                for err in e.errors():
                    where = ".".join(str(p) for p in err["loc"])
                    errors.append(f"[{label}] {where}: {err['msg']}")
                continue
            if drill.id in seen:
                errors.append(f"[{label}] duplicate id")
            seen.add(drill.id)
            drills.append(drill)

        if errors:
            raise LibraryError("drills.json has problems:\n" + "\n".join(errors))
        if not drills:
            raise LibraryError("drills.json contains no drills")
        return cls(drills)

    # ---------- filtering ----------

    def filter(
        self,
        mode: str,
        age_group: str,
        equipment: list[str],
        space: str,
        players: int = 1,
        has_partner: bool = False,
        phase: Optional[str] = None,
    ) -> list[Drill]:
        """Return drills that are physically possible with the user's setup."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if age_group not in AGE_GROUPS:
            raise ValueError(f"age_group must be one of {AGE_GROUPS}")
        if space not in SPACE_OPTIONS:
            raise ValueError(f"space must be one of {list(SPACE_OPTIONS)}")

        age_idx = AGE_GROUPS.index(age_group)
        avail_len, avail_wid = SPACE_OPTIONS[space]
        available = set(equipment)
        result = []

        for d in self.drills:
            if mode not in d.modes:
                continue
            if phase and phase not in d.phases:
                continue
            # Age
            if age_idx < AGE_GROUPS.index(d.age_min):
                continue
            if d.age_max and age_idx > AGE_GROUPS.index(d.age_max):
                continue
            # Players / partner
            if mode == "team":
                if players < d.players.min:
                    continue
                if players > d.players.max and not d.players.parallel_groups:
                    continue
            elif d.needs_partner and not has_partner:
                continue
            # Equipment (only required items must be available)
            if not set(d.equipment) <= available:
                continue
            # Space
            factor = SCALE_FACTOR if d.space.scalable else 1.0
            if d.space.length_m * factor > avail_len or d.space.width_m * factor > avail_wid:
                continue
            result.append(d)
        return result

    def candidates_by_phase(
        self,
        mode: str,
        age_group: str,
        equipment: list[str],
        space: str,
        focus: list[str],
        players: int = 1,
        has_partner: bool = False,
        position: Optional[str] = None,
    ) -> dict[str, list[Drill]]:
        """Group fitting drills by session phase, best focus match first."""
        wanted = set(focus)
        if position:
            wanted.add(position)

        fitting = self.filter(mode, age_group, equipment, space, players, has_partner)
        grouped: dict[str, list[Drill]] = {p: [] for p in PHASES}
        for d in fitting:
            for p in d.phases:
                grouped[p].append(d)
        for p in PHASES:
            grouped[p].sort(key=lambda d: len(wanted & set(d.focus)), reverse=True)
        return grouped

    def focus_options(self, mode: str) -> list[str]:
        """Focus areas that at least one drill for this mode covers (for dropdowns)."""
        found = {f for d in self.drills if mode in d.modes for f in d.focus}
        return sorted(found - {"recovery", "injury_prevention"})
