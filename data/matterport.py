"""Export a Matterport model through the Model API into the fallback building format.

    python -m data.matterport --demo rabinowitz          # writes demo/rabinowitz/building.json
    python -m data.load --file demo/rabinowitz/building.json

Used for the live demo building only (demo/PLANTED_AED.md, Option B). The output follows
docs/CONTRACTS.md section 7, so ``FallbackAdapter`` and ``data.load --file`` read it unchanged, and
it is a reviewable committed file. Panoramas are not downloaded or stored: ``panos`` is empty.

Auth: Basic ``MATTERPORT_API_KEY:MATTERPORT_API_TOKEN`` from ``shared.config``. Neither value is
ever printed, logged or written.

Coordinates: the Model API is z-up; ``twin_nodes`` are y-up (CONTRACTS section 1). Matterport's
documented API-to-SDK conversion is ``sdk = (x, z, -y)``, so the stored positions match the
Showcase SDK and floor plans drawn from x and z.

Walkable edges (the Model API ``neighbors`` are line-of-sight links, not walkable edges):
- Same floor: a line-of-sight neighbor on the same Matterport floor within ``WALK_EDGE_MAX_M``.
- Between floors: only through stair sweeps. A stair sweep is one whose height is more than
  ``STAIR_MIN_OFFSET_M`` away from its own floor's level and lies between two floor levels (a
  landing). It links only to its nearest line-of-sight neighbor at each of the two levels, within
  ``WALK_EDGE_MAX_M``. This is a geometric inference, not a label from the scan.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import networkx as nx

from shared.config import REPO_ROOT, MissingSettingError, get_settings

log = logging.getLogger("data.matterport")

API_URL = "https://api.matterport.com/api/models/graph"

# Same-floor walkable edge cutoff in meters. Chosen from the Rabinowitz scan (2026-11-14): the
# median distance from a sweep to its nearest same-floor sweep is 2.96 m and the largest is 5.28 m,
# so any cutoff under 5.28 m strands a sweep. 6.0 m is the smallest value in the brief's 5 to 6 m
# range that leaves no sweep isolated and joins the upper floor into one part; longer links are
# the ones that can cross the open atrium.
WALK_EDGE_MAX_M = 6.0
# A sweep this far (m) above or below its floor's level is not standing on that floor.
STAIR_MIN_OFFSET_M = 1.0

MODEL_QUERY = """
query Model($id: ID!) {
  model(id: $id) {
    id
    name
    floors { id sequence label }
    geocoordinates { latitude longitude }
    address { locality administrativeArea postalCode }
    locations {
      id
      floor { id sequence label }
      position { x y z }
      neighbors
    }
  }
}
"""


class MatterportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_model(model_id: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """The ``model`` object from the Model API. Raises ``MissingSettingError`` without credentials."""
    s = get_settings()
    if not s.matterport_api_key or not s.matterport_api_token:
        raise MissingSettingError(["MATTERPORT_API_KEY", "MATTERPORT_API_TOKEN"])
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.post(
            API_URL,
            json={"query": MODEL_QUERY, "variables": {"id": model_id}},
            auth=(s.matterport_api_key, s.matterport_api_token),
        )
    finally:
        if own:
            client.close()
    if resp.status_code != 200:
        raise MatterportError(f"Model API returned HTTP {resp.status_code}")
    body = resp.json()
    if body.get("errors"):
        messages = "; ".join(str(e.get("message")) for e in body["errors"])
        raise MatterportError(f"Model API errors: {messages}")
    model = (body.get("data") or {}).get("model")
    if not model:
        raise MatterportError(f"model {model_id} not found or not accessible")
    return model


# ---------------------------------------------------------------------------
# Geometry (pure)
# ---------------------------------------------------------------------------


def to_y_up(p: dict[str, float]) -> tuple[float, float, float]:
    """Model API (z-up) position to the y-up frame of twin_nodes and the Showcase SDK."""
    return (float(p["x"]), float(p["z"]), -float(p["y"]))


def floor_number(floor: dict[str, Any] | None) -> int | None:
    """The number in a Matterport floor label ("Floor 2" -> 2), else its sequence."""
    if not floor:
        return None
    m = re.search(r"(-?\d+)\s*$", str(floor.get("label") or ""))
    if m:
        return int(m.group(1))
    seq = floor.get("sequence")
    return int(seq) if seq is not None else None


def _height(loc: dict[str, Any]) -> float:
    return float(loc["position"]["z"])


def _xyz(loc: dict[str, Any]) -> tuple[float, float, float]:
    p = loc["position"]
    return (float(p["x"]), float(p["y"]), float(p["z"]))


def _floor_id(loc: dict[str, Any]) -> str | None:
    return (loc.get("floor") or {}).get("id")


def floor_levels(locations: list[dict[str, Any]]) -> dict[str, float]:
    """Median sweep height per Matterport floor id."""
    by_floor: dict[str, list[float]] = {}
    for loc in locations:
        by_floor.setdefault(_floor_id(loc) or "", []).append(_height(loc))
    return {fid: statistics.median(hs) for fid, hs in by_floor.items()}


def stair_sweeps(locations: list[dict[str, Any]], min_offset_m: float = STAIR_MIN_OFFSET_M) -> set[str]:
    """Sweeps standing between two floor levels: off their own floor's level by more than
    ``min_offset_m`` and strictly between the lowest and highest floor level."""
    levels = floor_levels(locations)
    if len(levels) < 2:
        return set()
    lo, hi = min(levels.values()), max(levels.values())
    out = set()
    for loc in locations:
        h = _height(loc)
        if abs(h - levels[_floor_id(loc) or ""]) > min_offset_m and lo + min_offset_m < h < hi - min_offset_m:
            out.add(loc["id"])
    return out


@dataclass
class EdgeReport:
    line_of_sight_pairs: int = 0
    cross_floor_pairs: int = 0
    same_floor_kept: int = 0
    stair_edges: int = 0
    stairs: list[str] = field(default_factory=list)
    max_edge_m: float = WALK_EDGE_MAX_M

    @property
    def kept(self) -> int:
        return self.same_floor_kept + self.stair_edges


def walkable_edges(
    locations: list[dict[str, Any]], max_edge_m: float = WALK_EDGE_MAX_M,
    min_offset_m: float = STAIR_MIN_OFFSET_M,
) -> tuple[set[tuple[str, str]], EdgeReport]:
    """Walkable edges (sorted id pairs) from line-of-sight neighbors. See the module docstring."""
    by_id = {loc["id"]: loc for loc in locations}
    stairs = stair_sweeps(locations, min_offset_m)
    rep = EdgeReport(stairs=sorted(stairs), max_edge_m=max_edge_m)
    pairs = {tuple(sorted((a["id"], b))) for a in locations for b in a.get("neighbors") or []
             if b in by_id and b != a["id"]}
    rep.line_of_sight_pairs = len(pairs)
    rep.cross_floor_pairs = sum(1 for a, b in pairs if _floor_id(by_id[a]) != _floor_id(by_id[b]))

    edges: set[tuple[str, str]] = set()
    for a, b in pairs:
        if a in stairs or b in stairs or _floor_id(by_id[a]) != _floor_id(by_id[b]):
            continue
        if math.dist(_xyz(by_id[a]), _xyz(by_id[b])) <= max_edge_m:
            edges.add((a, b))
    rep.same_floor_kept = len(edges)

    levels = sorted(set(floor_levels(locations).values()))
    for s in sorted(stairs):
        h = _height(by_id[s])
        below = max((lv for lv in levels if lv < h), default=None)
        above = min((lv for lv in levels if lv > h), default=None)
        for level in (below, above):
            if level is None:
                continue
            options = [
                (math.dist(_xyz(by_id[s]), _xyz(by_id[n])), n)
                for n in by_id[s].get("neighbors") or []
                if n in by_id and n not in stairs and abs(_height(by_id[n]) - level) <= min_offset_m
            ]
            options = [o for o in options if o[0] <= max_edge_m]
            if options:
                _, nearest = min(options)
                edges.add(tuple(sorted((s, nearest))))
                rep.stair_edges += 1
    return edges, rep


# ---------------------------------------------------------------------------
# Document (pure)
# ---------------------------------------------------------------------------


@dataclass
class DemoSpec:
    """Everything about a demo building that does not come from the Model API."""

    model_id: str
    building: dict[str, Any]
    camera: dict[str, Any]
    assets: list[dict[str, Any]]
    labels: dict[str, str]  # sweep id -> short place label, from team observations
    note: str
    out: Path


RABINOWITZ = DemoSpec(
    model_id="P3S6VUTP3qB",
    building={
        "costar_property_id": "DEMO-RABINOWITZ",
        "name": "Julis Romo Rabinowitz Building",
        "city": "Princeton",
        "matterport_model_id": "P3S6VUTP3qB",
    },
    camera={"id": "cam-atrium-1", "name": "Atrium camera 1",
            "sweep_id": "1k478kza39tbfu1uhbttg5ybb", "landmark": "the central atrium"},
    assets=[{
        "type": "aed", "sweep_id": "0f2a2fyf5iibscursb5gkyu9a", "label": "Demo AED (placed by team)",
        "source": "manual", "verified": False, "flags": ["simulated"],
    }],
    # Place names from the team's visual check of the scan (demo/PLANTED_AED.md).
    labels={
        "1k478kza39tbfu1uhbttg5ybb": "central atrium",
        "az0h181td1h01x8x9gxhnp47a": "atrium edge near the main corridor",
        "0f2a2fyf5iibscursb5gkyu9a": "Gothic arcade gate",
        "w5kacr4ci0d92c5wkzrfs4erd": "corridor wing",
    },
    note=("Live demo building, exported from the Matterport Model API by data/matterport.py. Not a "
          "CoStar building and never part of a census number (costar_property_id starts with DEMO-). "
          "The AED is a disclosed demo prop placed by the team (flag 'simulated'), not found in the "
          "scan. Address and lat/lng come from the Model API; size, type and tenants are unknown. "
          "Positions are y-up (Model API z-up converted as (x, z, -y)). Edges are walkable links "
          "derived from line-of-sight neighbors: same floor within the cutoff, floors joined only "
          "through stair sweeps. Panoramas are not stored."),
    out=REPO_ROOT / "demo" / "rabinowitz" / "building.json",
)

DEMOS = {"rabinowitz": RABINOWITZ}


def _address(model: dict[str, Any]) -> str | None:
    a = model.get("address") or {}
    region = " ".join(x for x in (a.get("administrativeArea"), a.get("postalCode")) if x)
    parts = [x for x in (a.get("locality"), region) if x]
    return ", ".join(parts) or None


def build_document(model: dict[str, Any], spec: DemoSpec, max_edge_m: float = WALK_EDGE_MAX_M) -> dict[str, Any]:
    """The CONTRACTS section 7 document for ``model``. Raises ``ValueError`` when a demo spot is not a sweep."""
    locations = list(model.get("locations") or [])
    edges, rep = walkable_edges(locations, max_edge_m)
    stairs = set(rep.stairs)
    neighbors: dict[str, list[str]] = {loc["id"]: [] for loc in locations}
    for a, b in sorted(edges):
        neighbors[a].append(b)
        neighbors[b].append(a)

    nodes = []
    for loc in locations:
        x, y, z = to_y_up(loc["position"])
        nodes.append({
            "sweep_id": loc["id"], "floor": floor_number(loc.get("floor")),
            "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
            "neighbors": sorted(neighbors[loc["id"]]), "room_type": None,
            "label": spec.labels.get(loc["id"]), "is_elevator": False, "is_stairs": loc["id"] in stairs,
        })
    by_id = {n["sweep_id"]: n for n in nodes}
    for sweep in [spec.camera["sweep_id"], *(a["sweep_id"] for a in spec.assets), *spec.labels]:
        if sweep not in by_id:
            raise ValueError(f"sweep {sweep} is not in model {model.get('id')}")

    geo = model.get("geocoordinates") or {}
    building = {
        **spec.building,
        "address": _address(model),
        "lat": geo.get("latitude"), "lng": geo.get("longitude"),
        "property_type": None, "floors": None, "size_sqft": None, "tenants_count": None,
    }
    assets = []
    for a in spec.assets:
        n = by_id[a["sweep_id"]]
        assets.append({**a, "floor": n["floor"], "x": n["x"], "y": n["y"], "z": n["z"]})
    cam = dict(spec.camera)
    cam["floor"] = by_id[cam["sweep_id"]]["floor"]
    return {
        "_note": spec.note,
        "_edges": {"max_edge_m": rep.max_edge_m, "line_of_sight_pairs": rep.line_of_sight_pairs,
                   "cross_floor_line_of_sight_pairs": rep.cross_floor_pairs,
                   "same_floor_edges": rep.same_floor_kept, "stair_edges": rep.stair_edges,
                   "stair_sweeps": rep.stairs},
        "building": building,
        "twin_nodes": nodes,
        "panos": [],
        "assets": assets,
        "camera": cam,
    }


def graph_of(nodes: Iterable[dict[str, Any]]) -> nx.Graph:
    g = nx.Graph()
    nodes = list(nodes)
    by_id = {n["sweep_id"]: n for n in nodes}
    for n in nodes:
        g.add_node(n["sweep_id"], floor=n["floor"])
        for m in n["neighbors"]:
            o = by_id[m]
            g.add_edge(n["sweep_id"], m, weight=math.dist((n["x"], n["y"], n["z"]), (o["x"], o["y"], o["z"])))
    return g


def summarize(doc: dict[str, Any]) -> dict[str, Any]:
    """Graph stats and the camera-to-AED route, for the CLI output and review."""
    g = graph_of(doc["twin_nodes"])
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    out: dict[str, Any] = {"sweeps": g.number_of_nodes(), "edges": g.number_of_edges(), "components": comps}
    cam = doc["camera"]["sweep_id"]
    for a in doc["assets"]:
        try:
            meters, path = nx.single_source_dijkstra(g, cam, a["sweep_id"], weight="weight")
            out.setdefault("routes", []).append({"to": a["label"], "distance_m": round(meters, 1), "path": path})
        except nx.NetworkXNoPath:
            out.setdefault("routes", []).append({"to": a["label"], "distance_m": None, "path": []})
    return out


def write_document(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m data.matterport", description=__doc__.split("\n")[0])
    ap.add_argument("--demo", choices=sorted(DEMOS), default="rabinowitz")
    ap.add_argument("--out", type=Path, help="output path (default: the demo's building.json)")
    ap.add_argument("--max-edge-m", type=float, default=WALK_EDGE_MAX_M)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    spec = DEMOS[args.demo]
    doc = build_document(fetch_model(spec.model_id), spec, args.max_edge_m)
    out = args.out or spec.out
    write_document(doc, out)
    stats = summarize(doc)
    print(f"wrote {out}: {stats['sweeps']} sweeps, {stats['edges']} walkable edges, "
          f"components {stats['components']}, stair sweeps {doc['_edges']['stair_sweeps']}")
    for r in stats.get("routes", []):
        print(f"camera -> {r['to']}: {r['distance_m']} m over {len(r['path'])} sweeps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
