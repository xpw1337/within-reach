"""``FallbackAdapter``: one building from a file in the CONTRACTS section 7 format.

Default file: the hand-built fixture ``demo/fallback/building.json`` (``FALLBACK-1``). The same
reader loads the live demo venue ``demo/rabinowitz/building.json`` (``DEMO-RABINOWITZ``, exported
by data/matterport.py). Both are fixtures by prefix (data.adapter.FIXTURE_PREFIXES) and never count
in a census number. The adapter only answers for the building in its file.
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
        if not self.path.is_absolute():
            self.path = REPO_ROOT / self.path
        self.doc: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def costar_property_id(self) -> str | None:
        return self.doc["building"].get("costar_property_id")

    def _mine(self, building: BuildingRecord) -> bool:
        """The file describes one building; never hand its data to another one (for example the
        census asking the default adapter for a demo building's outside data)."""
        return not building.costar_property_id or building.costar_property_id == self.costar_property_id

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
        if not self._mine(building):
            return []
        return [TwinNode(**{k: n[k] for k in _NODE_FIELDS if k in n}) for n in self.doc.get("twin_nodes", [])]

    def list_panos(self, building: BuildingRecord) -> list[PanoRef]:
        if not self._mine(building):
            return []
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
        if not v or not self._mine(building):
            return None
        return VexcelInfo(
            entrances=list(v.get("entrances", [])),
            ambulance_parking=list(v.get("ambulance_parking", [])),
            hydrants=list(v.get("hydrants", [])),
            image_url=v.get("image_url"),
        )

    # --- fallback extras ---
    def get_assets(self, building: BuildingRecord) -> list[dict[str, Any]]:
        if not self._mine(building):
            return []
        return [dict(a) for a in self.doc.get("assets", [])]

    def get_camera(self, building: BuildingRecord) -> dict[str, Any] | None:
        cam = self.doc.get("camera")
        return dict(cam) if cam and self._mine(building) else None
