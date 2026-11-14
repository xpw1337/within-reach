"""``FallbackAdapter``: the hand-built demo building in ``demo/fallback/building.json``.

Format: docs/CONTRACTS.md section 7. It is a fixture: its ``costar_property_id`` starts with
``FALLBACK-`` and it never counts in a census headline number.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shared.config import REPO_ROOT
from shared.types import BuildingRecord, PanoRef, TwinNode, VexcelInfo

FALLBACK_PATH = REPO_ROOT / "demo" / "fallback" / "building.json"
FALLBACK_ID = "FALLBACK-1"

_BUILDING_FIELDS = (
    "costar_property_id",
    "name",
    "address",
    "city",
    "lat",
    "lng",
    "property_type",
    "floors",
    "size_sqft",
    "tenants_count",
    "matterport_model_id",
    "manager",
    "contacts",
)
_NODE_FIELDS = (
    "sweep_id",
    "floor",
    "x",
    "y",
    "z",
    "neighbors",
    "room_type",
    "label",
    "is_elevator",
    "is_stairs",
)


class FallbackAdapter:
    """Reads exactly one JSON file. Extra methods ``get_assets`` and ``get_camera`` feed the loader."""

    def __init__(self, path: Path | str = FALLBACK_PATH) -> None:
        self.path = Path(path)
        self.doc: dict[str, Any] = json.loads(self.path.read_text())

    # --- DatasetAdapter ---
    def list_buildings(
        self, city: str | None = None, types: list[str] | None = None
    ) -> Iterable[BuildingRecord]:
        b = self.doc["building"]
        if city and (b.get("city") or "").lower() != city.lower():
            return []
        if types and (b.get("property_type") or "").lower() not in {t.lower() for t in types}:
            return []
        rec = BuildingRecord(**{k: b[k] for k in _BUILDING_FIELDS if k in b})
        rec.raw = {"source": "fallback", "path": str(self.path)}
        return [rec]

    def get_twin(self, building: BuildingRecord) -> list[TwinNode]:
        return [TwinNode(**{k: n[k] for k in _NODE_FIELDS if k in n}) for n in self.doc.get("twin_nodes", [])]

    def list_panos(self, building: BuildingRecord) -> list[PanoRef]:
        return [
            PanoRef(sweep_id=p["sweep_id"], image_uri=p["image_uri"], building_id=building.id)
            for p in self.doc.get("panos", [])
        ]

    def fetch_pano(self, pano: PanoRef) -> Path:
        path = Path(pano.image_uri)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"fallback panorama not found: {path}")
        return path

    def get_vexcel(self, building: BuildingRecord) -> VexcelInfo | None:
        v = self.doc.get("vexcel")
        if not v:
            return None
        return VexcelInfo(
            entrances=list(v.get("entrances", [])),
            ambulance_parking=list(v.get("ambulance_parking", [])),
            hydrants=list(v.get("hydrants", [])),
            image_url=v.get("image_url"),
        )

    # --- fallback extras ---
    def get_assets(self, building: BuildingRecord) -> list[dict[str, Any]]:
        return [dict(a) for a in self.doc.get("assets", [])]

    def get_camera(self, building: BuildingRecord) -> dict[str, Any] | None:
        cam = self.doc.get("camera")
        return dict(cam) if cam else None
