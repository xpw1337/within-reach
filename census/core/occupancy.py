"""Occupancy estimate for a building: gross floor area / occupant load factor (spec sections 7, 9.5).

STATUS: UNVERIFIED. The factors below were read from secondary reproductions of the code table,
not from the ICC publication itself, and the property-type mapping is our own judgment. Until a
person checks them, every number derived here (``occupancy_est``, ``people_at_risk``) is labeled
an estimate (docs/LANES.md open question 2).

Source of the factors:
    International Building Code, 2021 edition, Table 1004.5 "Maximum Floor Area Allowances per
    Occupant" (floor area in square feet per occupant).
    Read from: City of Houston, Houston Public Works memo "IBC Occupant Load Factors",
    December 1, 2023, "2021 Houston Building Code Changes", which reproduces Table 1004.5:
    https://www.houstonpermittingcenter.org/media/9311/download
    Cross-checked against Washington WAC 51-54A-1004 (state adoption of the 2021 IFC, same table):
    https://lawfilesext.leg.wa.gov/Law/WACArchive/2024/htm/WAC%20%2051%20-%2054A%20CHAPTER/WAC%20%2051%20-%2054A-1004.htm

What the number means: Table 1004.5 sets the design occupant load used to size exits. It is a
code maximum, not a count of people normally present, so ``occupancy_est`` is an upper-bound
style estimate. Only "gross" factors are used, because the dataset gives gross building area;
"net" factors (assembly, classrooms, day care) would need net area and are not applied.
A property type we cannot map to one function of space returns None: no number is guessed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TABLE_STATUS = "unverified"
TABLE_SOURCE = "IBC 2021 Table 1004.5 (via Houston Public Works memo, 2023-12-01)"

# Function of space -> gross square feet per occupant, IBC 2021 Table 1004.5 (UNVERIFIED, see above).
OCCUPANT_LOAD_FACTORS_SQFT_GROSS: dict[str, int] = {
    "business_areas": 150,
    "exercise_rooms": 50,
    "mercantile": 60,
    "industrial_areas": 100,
    "warehouses": 500,
    "residential": 200,
    "institutional_outpatient_areas": 100,
    "dormitories": 50,
    "parking_garages": 200,
}

# Property-type keywords -> function of space. Our mapping, not part of the code table. Checked in
# order, so more specific phrases come first ("medical office" before "office"). Lowercase.
PROPERTY_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("medical office", "outpatient", "clinic"), "institutional_outpatient_areas"),
    (("gym", "fitness", "health club", "exercise"), "exercise_rooms"),
    (("office",), "business_areas"),
    (("retail", "store", "shopping center", "mercantile"), "mercantile"),
    (("warehouse", "distribution"), "warehouses"),
    (("industrial", "manufacturing"), "industrial_areas"),
    (("dormitory",), "dormitories"),
    (("multi-family", "multifamily", "apartment", "residential", "hotel", "motel", "hospitality"),
     "residential"),
    (("parking garage", "parking structure"), "parking_garages"),
]


@dataclass(frozen=True)
class OccupancyEstimate:
    people: int
    function_of_space: str
    sqft_per_occupant: int
    size_sqft: int
    basis: str  # one human-readable sentence for events and documents


def function_of_space(property_type: str | None) -> str | None:
    """Map a dataset property type to a Table 1004.5 function of space, or None if unclear."""
    if not property_type:
        return None
    text = property_type.strip().lower()
    for keywords, function in PROPERTY_TYPE_KEYWORDS:
        if any(k in text for k in keywords):
            return function
    return None


def estimate_occupancy(property_type: str | None, size_sqft: float | None) -> OccupancyEstimate | None:
    """Estimated occupant load, or None when the type has no factor or the area is unknown."""
    function = function_of_space(property_type)
    if function is None or size_sqft is None or size_sqft <= 0:
        return None
    factor = OCCUPANT_LOAD_FACTORS_SQFT_GROSS[function]
    people = math.ceil(size_sqft / factor)  # whole people, rounded up
    size = int(size_sqft)
    basis = (
        f"{size} gross sq ft / {factor} sq ft per occupant ({function.replace('_', ' ')}, "
        f"{TABLE_SOURCE}, {TABLE_STATUS})"
    )
    return OccupancyEstimate(people=people, function_of_space=function, sqft_per_occupant=factor,
                             size_sqft=size, basis=basis)
