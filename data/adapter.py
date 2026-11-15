"""Dataset access behind one protocol (docs/ARCHITECTURE.md decision D5, docs/CONTRACTS.md section 4).

Everything downstream codes against ``DatasetAdapter``. ``get_adapter()`` returns the real CoStar
adapter when ``COSTAR_DATA_PATH`` is set, otherwise the ``FallbackAdapter`` that reads
``demo/fallback/building.json``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from shared.config import get_settings
from shared.types import BuildingRecord, PanoRef, TwinNode, VexcelInfo

# The one list of costar_property_id prefixes that mark non-census buildings: the hand-built
# fallback fixture (FALLBACK-) and live demo venues such as Rabinowitz (DEMO-). They never count in
# a census number, ranking, report or automatic candidate list.
FIXTURE_PREFIXES: tuple[str, ...] = ("FALLBACK-", "DEMO-")
FIXTURE_PREFIX = FIXTURE_PREFIXES[0]  # kept for older imports


def is_fixture(costar_property_id: str | None) -> bool:
    """True for fixture and demo buildings, which never count in census numbers."""
    return bool(costar_property_id) and str(costar_property_id).startswith(FIXTURE_PREFIXES)


@runtime_checkable
class DatasetAdapter(Protocol):
    def list_buildings(
        self, city: str | None = None, types: list[str] | None = None
    ) -> Iterable[BuildingRecord]: ...

    def get_twin(self, building: BuildingRecord) -> list[TwinNode]: ...

    def list_panos(self, building: BuildingRecord) -> list[PanoRef]: ...

    def fetch_pano(self, pano: PanoRef) -> Path:
        """Local cached equirectangular image for the pano (downloads lazily into .cache/panos/)."""
        ...

    def get_vexcel(self, building: BuildingRecord) -> VexcelInfo | None: ...


def get_adapter() -> DatasetAdapter:
    """The real adapter, or ``FallbackAdapter`` if ``COSTAR_DATA_PATH`` is unset."""
    path = get_settings().costar_data_path
    if not path:
        from data.fallback import FallbackAdapter

        return FallbackAdapter()
    try:
        from data.costar import CoStarAdapter  # type: ignore[import-not-found]
    except ImportError as exc:
        raise NotImplementedError(
            "COSTAR_DATA_PATH is set but the CoStar adapter (data/costar.py, subtask 1.5) is not built "
            "yet. Unset COSTAR_DATA_PATH to use the fallback building."
        ) from exc
    return CoStarAdapter(path)
