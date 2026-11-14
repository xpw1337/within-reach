"""Dataclasses shared by data/, census/ and agent/.

These are the plain-Python shapes that cross package boundaries (docs/CONTRACTS.md section 4).
Field names follow the database columns in supabase/migrations/0001_init.sql wherever a column
exists, so a row can be built with ``Cls(**row)`` after dropping unknown keys (see ``from_row``).

Units: distances in meters, times in seconds. Walking times are one-way unless a field name says
otherwise (docs/ARCHITECTURE.md decision D4).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal, TypeVar

# ---------------------------------------------------------------------------
# Enums (mirror the Postgres enums in 0001_init.sql)
# ---------------------------------------------------------------------------

AssetType = Literal[
    "aed",
    "naloxone",
    "extinguisher",
    "exit",
    "exit_sign",
    "sprinkler",
    "smoke_detector",
    "first_aid",
    "stairs",
    "elevator",
]
ASSET_TYPES: tuple[str, ...] = (
    "aed",
    "naloxone",
    "extinguisher",
    "exit",
    "exit_sign",
    "sprinkler",
    "smoke_detector",
    "first_aid",
    "stairs",
    "elevator",
)

# Equipment types that get a walking-time map, a red zone and a score (spec section 9.4).
GapType = Literal["aed", "extinguisher", "exit"]
GAP_TYPES: tuple[str, ...] = ("aed", "extinguisher", "exit")

Zone = Literal["green", "yellow", "red", "unknown"]
Scenario = Literal["current", "proposed"]
AssetSource = Literal["detected", "tag", "manual", "proposed"]

T = TypeVar("T")


def from_row(cls: type[T], row: dict[str, Any]) -> T:
    """Build a dataclass from a dict, ignoring keys the dataclass does not declare."""
    names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: v for k, v in row.items() if k in names})


# ---------------------------------------------------------------------------
# Dataset (data/ adapters produce these; data/load.py writes them)
# ---------------------------------------------------------------------------


@dataclass
class BuildingRecord:
    """One building as the dataset adapter sees it. Maps onto the ``buildings`` table."""

    costar_property_id: str
    name: str | None = None
    address: str | None = None
    city: str | None = None  # 'Houston' | 'Los Angeles'
    lat: float | None = None
    lng: float | None = None
    property_type: str | None = None
    floors: int | None = None
    size_sqft: int | None = None
    tenants_count: int | None = None
    matterport_model_id: str | None = None
    manager: dict[str, Any] | None = None
    contacts: list[dict[str, Any]] = field(default_factory=list)
    id: str | None = None  # buildings.id once loaded into the database
    raw: dict[str, Any] = field(default_factory=dict)  # adapter-specific fields, never written as-is


@dataclass
class TwinNode:
    """One sweep (scan position) in the building's twin. Maps onto ``twin_nodes``.

    Coordinates are model-space meters with y up; floor plans are drawn from x and z.
    """

    sweep_id: str
    floor: int
    x: float
    y: float
    z: float
    neighbors: list[str] = field(default_factory=list)
    room_type: str | None = None
    label: str | None = None
    is_elevator: bool = False
    is_stairs: bool = False


@dataclass
class PanoRef:
    """Where a sweep's panorama can be fetched. Maps onto ``panos``.

    ``rotation`` is the sweep's orientation in model space if the dataset provides it, as a
    quaternion (x, y, z, w). It is needed to turn a tile heading into a world-space ray. It is not
    a database column; the adapter supplies it at scan time (open question in data/DESIGN.md).
    """

    sweep_id: str
    image_uri: str
    building_id: str | None = None
    rotation: tuple[float, float, float, float] | None = None


@dataclass
class VexcelInfo:
    """Outside context for a building. Stored as ``buildings.vexcel`` jsonb.

    Each point is a dict ``{"lat": float, "lng": float, "desc": str | None, ...}``. Entrances may
    also carry ``"ambulance_access": bool``.
    """

    entrances: list[dict[str, Any]] = field(default_factory=list)
    ambulance_parking: list[dict[str, Any]] = field(default_factory=list)
    hydrants: list[dict[str, Any]] = field(default_factory=list)
    image_url: str | None = None


# ---------------------------------------------------------------------------
# Census math (census/core produces these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ray:
    """A viewing ray in model space (meters, y up). ``direction`` is a unit vector."""

    origin: tuple[float, float, float]
    direction: tuple[float, float, float]


@dataclass
class Route:
    """A walking route over the sweep graph."""

    path: list[str]  # sweep ids, source first, destination last
    distance_m: float


# Walking-time maps: sweep_id -> one-way seconds. Unreachable sweeps are absent (stored as NULL).
TimeMap = dict[str, float]
# Per gap type: {"aed": TimeMap, "extinguisher": TimeMap, "exit": TimeMap}. A type with no asset
# visible in the scan maps to an empty dict.
CoverageByType = dict[str, TimeMap]


@dataclass
class Flags:
    """Route and equipment flags for one building (spec section 9.4)."""

    stairs_only_sweeps: list[str] = field(default_factory=list)  # upper-floor sweeps whose exit routes need stairs
    blocked_exits: int = 0
    no_aed_visible: bool = False  # UI wording: "no AED visible in the scan", never "no AED"
    no_extinguisher_visible: bool = False
    no_exit_visible: bool = False
    graph_components: int = 1  # disconnected scans are common; reported, not fatal
    sweeps_total: int = 0

    @property
    def stairs_only(self) -> bool:
        return bool(self.stairs_only_sweeps)


@dataclass
class Placement:
    """Result of a greedy ``place_one`` search. Feeds ``fixes``, ``assets(source='proposed')`` and
    ``coverage(scenario='proposed')``. ``sweep_id`` is None when no candidate improves anything."""

    sweep_id: str | None
    before_worst_s: float | None
    after_worst_s: float | None
    before_red_frac: float
    after_red_frac: float
    proposed_times: TimeMap = field(default_factory=dict)
    candidates_considered: int = 0
    subsampled: bool = False


@dataclass
class BuildingScore:
    """One ``building_scores`` row (without ``rank`` and ``updated_at``, which are set by ranking)."""

    aed_worst_s: float | None
    aed_red_frac: float | None
    ext_worst_s: float | None
    ext_red_frac: float | None
    exit_worst_s: float | None
    exit_red_frac: float | None
    stairs_only: bool
    blocked_exits: int
    worst_gap: Literal["aed", "extinguisher", "exit", "none"]
    people_at_risk: int | None  # an estimate: occupancy factors are unverified
    gap_score: float
    rank: int | None = None
