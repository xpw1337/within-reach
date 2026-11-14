"""Small synthetic buildings with hand-checkable answers, shared by the census tests."""

from __future__ import annotations

from shared.types import TwinNode


def line(n: int, spacing: float = 10.0, floor: int = 0, prefix: str = "s") -> list[TwinNode]:
    """n sweeps in a straight line along x, ``spacing`` meters apart, each linked to the next."""
    nodes = []
    for i in range(n):
        neighbors = []
        if i > 0:
            neighbors.append(f"{prefix}{i - 1}")
        if i < n - 1:
            neighbors.append(f"{prefix}{i + 1}")
        nodes.append(TwinNode(sweep_id=f"{prefix}{i}", floor=floor, x=i * spacing, y=0.0, z=0.0,
                              neighbors=neighbors))
    return nodes


def two_floor(with_elevator: bool = True) -> list[TwinNode]:
    """Two floors, 3 m apart, 4 sweeps each along x (0, 10, 20, 30 m).

    Floor 0: a0 a1 a2 a3. Exit at a0. Stairs: a3 (floor 0) <-> b3 (floor 1), both tagged stairs.
    Elevator (optional): a1 <-> e0 / e1 <-> b1 with e0, e1 tagged elevator.
    Floor 1: b0 b1 b2 b3.
    """
    def node(sid, floor, x, nbrs, **kw):
        return TwinNode(sweep_id=sid, floor=floor, x=x, y=3.0 * floor, z=0.0, neighbors=nbrs, **kw)

    nodes = [
        node("a0", 0, 0, ["a1"], label="main entrance"),
        node("a1", 0, 10, ["a0", "a2"], label="front desk"),
        node("a2", 0, 20, ["a1", "a3"]),
        node("a3", 0, 30, ["a2", "b3"], is_stairs=True, label="stairwell"),
        node("b3", 1, 30, ["a3", "b2"], is_stairs=True, label="stairwell"),
        node("b2", 1, 20, ["b3", "b1"]),
        node("b1", 1, 10, ["b2", "b0"]),
        node("b0", 1, 0, ["b1"], label="yoga studio"),
    ]
    if with_elevator:
        by = {n.sweep_id: n for n in nodes}
        by["a1"].neighbors.append("e0")
        by["b1"].neighbors.append("e1")
        nodes += [
            TwinNode(sweep_id="e0", floor=0, x=10, y=0.0, z=2.0, neighbors=["a1", "e1"], is_elevator=True,
                     label="east elevators"),
            TwinNode(sweep_id="e1", floor=1, x=10, y=3.0, z=2.0, neighbors=["e0", "b1"], is_elevator=True,
                     label="east elevators"),
        ]
    return nodes
