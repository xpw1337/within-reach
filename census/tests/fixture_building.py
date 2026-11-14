"""A test building in the docs/CONTRACTS.md section 7 fallback format, and a seeder that loads
any such dict into a FakeSupabase the way ``data/load.py --fallback`` loads the real database.

Geometry (meters): two floors 4 m apart, eight sweeps per floor along x every 20 m.
Floor 0: f0s0..f0s7 at x = 0..140. Floor 1: f1s0..f1s7 at the same x, y = 4.
Elevator: e0 (floor 0) and e1 (floor 1) at x = 20, z = 4, linked to f0s1 / f1s1.
Stairs: st0 (floor 0) and st1 (floor 1) at x = 140, z = 4, linked to f0s7 / f1s7.
One AED at f0s1 ("by the front desk"), so the far end of floor 1 is about 132 m away (red at
1.4 m/s with a 90 s one-way limit). Exits at f0s0 and f0s7. Two entrances in the Vexcel block.
Every value is a fixture; ids start with FALLBACK- so reports exclude it.
"""

from __future__ import annotations

import copy
import uuid

from census.tests.fakes import FakeSupabase


def fixture_building() -> dict:
    nodes = []

    def add(sid, floor, x, y, z, nbrs, **kw):
        nodes.append({"sweep_id": sid, "floor": floor, "x": x, "y": y, "z": z, "neighbors": nbrs,
                      "room_type": kw.get("room_type"), "label": kw.get("label"),
                      "is_elevator": kw.get("is_elevator", False), "is_stairs": kw.get("is_stairs", False)})

    labels0 = {0: "main entrance", 1: "front desk", 3: "weights area", 7: "rear exit"}
    labels1 = {0: "yoga studio", 1: "east elevators landing", 4: "spin room", 7: "far stretching area"}
    for floor, labels in ((0, labels0), (1, labels1)):
        for i in range(8):
            sid = f"f{floor}s{i}"
            nbrs = [f"f{floor}s{j}" for j in (i - 1, i + 1) if 0 <= j < 8]
            if i == 1:
                nbrs.append(f"e{floor}")
            if i == 7:
                nbrs.append(f"st{floor}")
            add(sid, floor, 20.0 * i, 4.0 * floor, 0.0, nbrs, label=labels.get(i),
                room_type="bathroom" if (floor, i) == (1, 6) else "gym")
    add("e0", 0, 20.0, 0.0, 4.0, ["f0s1", "e1"], is_elevator=True, label="east elevators")
    add("e1", 1, 20.0, 4.0, 4.0, ["f1s1", "e0"], is_elevator=True, label="east elevators")
    add("st0", 0, 140.0, 0.0, 4.0, ["f0s7", "st1"], is_stairs=True, label="rear stairs")
    add("st1", 1, 140.0, 4.0, 4.0, ["f1s7", "st0"], is_stairs=True, label="rear stairs")

    return {
        "building": {"costar_property_id": "FALLBACK-TEST", "name": "Fixture Gym", "address": "1 Test Way",
                     "city": "Houston", "lat": 29.75, "lng": -95.36, "property_type": "Gym",
                     "floors": 2, "size_sqft": 20000, "tenants_count": 1},
        "twin_nodes": nodes,
        "panos": [{"sweep_id": n["sweep_id"], "image_uri": f"fixture/{n['sweep_id']}.jpg"} for n in nodes],
        "assets": [
            {"type": "aed", "sweep_id": "f0s1", "floor": 0, "label": "by the front desk", "source": "manual"},
            {"type": "extinguisher", "sweep_id": "f0s3", "floor": 0, "label": "by the weights", "source": "manual"},
            {"type": "extinguisher", "sweep_id": "f1s4", "floor": 1, "label": "spin room door", "source": "manual"},
            {"type": "extinguisher", "sweep_id": "f0s7", "floor": 0, "label": "rear exit", "source": "manual"},
            {"type": "exit", "sweep_id": "f0s0", "floor": 0, "label": "main entrance", "source": "manual"},
            {"type": "exit", "sweep_id": "f0s7", "floor": 0, "label": "rear exit", "source": "manual",
             "flags": ["blocked_exit"]},
        ],
        "vexcel": {
            "entrances": [
                {"lat": 29.7500, "lng": -95.3600, "desc": "Main entrance on Test Way", "sweep_id": "f0s0",
                 "ambulance_access": True},
                {"lat": 29.7503, "lng": -95.3586, "desc": "Rear loading door", "sweep_id": "f0s7",
                 "ambulance_access": True},
            ],
            "ambulance_parking": [{"lat": 29.7504, "lng": -95.3585, "desc": "Rear lot"}],
            "hydrants": [{"lat": 29.7499, "lng": -95.3601, "desc": "Corner of Test Way"}],
            "image_url": None,
        },
        "camera": {"id": "cam-lobby-1", "sweep_id": "f0s1", "floor": 0, "landmark": "east elevators"},
    }


def seed(db: FakeSupabase, data: dict | None = None) -> str:
    """Load a fallback-format dict into the fake tables. Returns the new building id."""
    data = copy.deepcopy(data or fixture_building())
    building_id = str(uuid.uuid4())
    row = dict(data["building"], id=building_id, vexcel=data.get("vexcel"))
    db.table("buildings").insert(row).execute()
    db.table("twin_nodes").insert([dict(n, building_id=building_id) for n in data["twin_nodes"]]).execute()
    db.table("panos").insert([dict(p, building_id=building_id) for p in data.get("panos", [])]).execute()
    by_sweep = {n["sweep_id"]: n for n in data["twin_nodes"]}
    assets = []
    for a in data.get("assets", []):
        n = by_sweep.get(a.get("sweep_id"), {})
        assets.append({"building_id": building_id, "x": n.get("x"), "y": n.get("y"), "z": n.get("z"),
                       "flags": [], "detection_ids": [], "verified": True, **a})
    if assets:
        db.table("assets").insert(assets).execute()
    cam = data.get("camera")
    if cam:
        db.table("cameras").upsert({"name": cam["id"], "building_id": building_id, **cam}, on_conflict="id").execute()
    return building_id
