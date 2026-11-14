"""Red fractions, worst case, people at risk, gap score and ranking (spec sections 9.4, 9.5).

Pure functions. Red limits come in as arguments (one-way seconds per gap type, from
``shared.thresholds.limit_seconds`` in the tools layer). All times are one-way walking seconds.

Rules:
- ``red_frac`` is the fraction of scanned positions (sweeps) in the red zone. Sweep count stands
  in for floor area: the UI says "of scanned positions".
- A sweep is red when its time is strictly greater than the limit, or when it cannot reach any
  asset of that type on the scan graph (no measured route means we cannot show it is within
  reach). A type with no asset visible in the scan is therefore 100% red with worst case None,
  and the UI wording is "no <type> visible in the scan".
- ``worst_s`` is the largest measured time; unreachable sweeps are counted in ``red_frac`` and in
  ``unreachable`` instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from shared.types import GAP_TYPES, BuildingScore, CoverageByType, Flags, TimeMap

# PRODUCT CHOICE, not a guideline or a measured statistic: how much each gap type counts toward
# gap_score. The spec (section 9.5) only says the AED gap is weighted highest. They sum to 1, so
# gap_score is in [0, 1].
GAP_WEIGHTS: dict[str, float] = {"aed": 0.5, "extinguisher": 0.25, "exit": 0.25}

# Tie-break order when two gaps have the same red fraction: higher weight first.
_GAP_ORDER = sorted(GAP_TYPES, key=lambda t: -GAP_WEIGHTS[t])


@dataclass(frozen=True)
class TypeStats:
    worst_s: float | None  # largest measured one-way time; None when nothing was measured
    red_frac: float | None  # None only when the building has no sweeps
    red_sweeps: int
    unreachable: int  # sweeps with no route to any asset of this type
    measured: int  # sweeps with a time

    def as_dict(self) -> dict:
        return {"worst_s": self.worst_s, "red_frac": self.red_frac, "red_sweeps": self.red_sweeps,
                "unreachable": self.unreachable, "measured": self.measured}


def type_stats(times: TimeMap, sweeps_total: int, limit_s: float) -> TypeStats:
    """Worst case and red fraction for one equipment type over ``sweeps_total`` sweeps."""
    measured = len(times)
    total = max(sweeps_total, measured)
    unreachable = total - measured
    over = sum(1 for t in times.values() if t > limit_s)
    red = over + unreachable
    worst = max(times.values()) if times else None
    red_frac = (red / total) if total > 0 else None
    return TypeStats(worst_s=worst, red_frac=red_frac, red_sweeps=red, unreachable=unreachable,
                     measured=measured)


def red_sweeps(times: TimeMap, all_sweeps: list[str], limit_s: float) -> list[str]:
    """The sweep ids counted as red by ``type_stats`` (over the limit or unreachable)."""
    return [s for s in all_sweeps if s not in times or times[s] > limit_s]


def worst_gap(red_fracs: Mapping[str, float | None]) -> str:
    """The gap type with the largest red fraction; 'none' when nothing is red.

    Ties go to the higher-weighted type (AED first)."""
    best, best_frac = "none", 0.0
    for gap in _GAP_ORDER:
        frac = red_fracs.get(gap)
        if frac is not None and frac > best_frac:
            best, best_frac = gap, frac
    return best


def gap_score(red_fracs: Mapping[str, float | None]) -> float:
    """Weighted sum of red fractions (weights are a product choice, see GAP_WEIGHTS)."""
    return sum(GAP_WEIGHTS[g] * (red_fracs.get(g) or 0.0) for g in GAP_TYPES)


def people_at_risk(occupancy_est: int | None, worst_gap_red_frac: float | None) -> int | None:
    """occupancy_est x red fraction of the worst gap (spec section 9.5). None when occupancy is unknown."""
    if occupancy_est is None:
        return None
    return round(occupancy_est * (worst_gap_red_frac or 0.0))


def score_building(
    coverage: CoverageByType,
    occupancy_est: int | None,
    flags: Flags,
    *,
    limits_s: Mapping[str, float],
) -> BuildingScore:
    """One ``building_scores`` row (rank is filled later by ``rank_buildings``).

    ``coverage`` maps each gap type to its one-way time map (empty when no asset of that type is
    visible in the scan). ``limits_s`` maps each gap type to its red limit in one-way seconds.
    ``flags.sweeps_total`` is the denominator for every red fraction.
    """
    stats = {g: type_stats(coverage.get(g, {}), flags.sweeps_total, limits_s[g]) for g in GAP_TYPES}
    fracs = {g: s.red_frac for g, s in stats.items()}
    gap = worst_gap(fracs)
    return BuildingScore(
        aed_worst_s=stats["aed"].worst_s,
        aed_red_frac=stats["aed"].red_frac,
        ext_worst_s=stats["extinguisher"].worst_s,
        ext_red_frac=stats["extinguisher"].red_frac,
        exit_worst_s=stats["exit"].worst_s,
        exit_red_frac=stats["exit"].red_frac,
        stairs_only=flags.stairs_only,
        blocked_exits=flags.blocked_exits,
        worst_gap=gap,  # type: ignore[arg-type]
        people_at_risk=people_at_risk(occupancy_est, fracs.get(gap) if gap != "none" else 0.0),
        gap_score=gap_score(fracs),
    )


def rank_buildings(scores: Mapping[str, BuildingScore]) -> dict[str, int]:
    """Rank 1 = biggest gap. Order: gap_score desc, then people_at_risk desc (unknown last), then id."""
    def key(item):
        building_id, s = item
        par = s.people_at_risk if s.people_at_risk is not None else -1
        return (-s.gap_score, -par, building_id)

    return {bid: i + 1 for i, (bid, _) in enumerate(sorted(scores.items(), key=key))}


def scan_priority(occupancy_est: int | None) -> float | None:
    """Records' prior for the scan order: more people first. A product choice; None sorts last."""
    return float(occupancy_est) if occupancy_est is not None else None
