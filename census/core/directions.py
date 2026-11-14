"""Directions a stranger can follow, from a route over the sweep graph (spec sections 3, 9.4). Pure.

Landmark-based on purpose: we do not know which way the listener is facing, so there is no
"turn left". The phrase names floor changes, up to two labeled places passed on the way, and the
destination's label. It never contains the distance: the speaker template already says
"{aed_distance} meters, {aed_directions}" and the distance comes from ``Route.distance_m``
(docs/CONTRACTS.md section 4).
"""

from __future__ import annotations

import networkx as nx

from shared.types import Route

MAX_LANDMARKS = 2
_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
_PREPOSITIONS = ("by ", "left ", "right ", "next ", "near ", "at ", "in ", "on ", "behind ", "across ",
                 "opposite ", "beside ", "under ", "inside ", "outside ", "beneath ", "past ", "around ")


def _place(label: str) -> str:
    text = label.strip()
    if text.lower().startswith(_PREPOSITIONS):
        return text
    if text.lower().startswith("the "):
        return f"near {text}"
    return f"near the {text}"


def _floors(n: int) -> str:
    word = _COUNT_WORDS.get(abs(n), str(abs(n)))
    return f"{word} floor{'s' if abs(n) != 1 else ''}"


def route_directions(graph: nx.Graph, route: Route, dest_label: str | None = None) -> str:
    nodes = [graph.nodes[s] for s in route.path]
    dest = dest_label or nodes[-1].get("label") or nodes[-1].get("room_type")
    parts: list[str] = []
    landmarks: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(nodes) - 1:
        here, nxt = nodes[i], nodes[i + 1]
        if here.get("floor") is not None and nxt.get("floor") is not None and here["floor"] != nxt["floor"]:
            # Collapse a run of floor changes into one instruction.
            j = i + 1
            while (j < len(nodes) - 1 and nodes[j + 1].get("floor") is not None
                   and nodes[j + 1]["floor"] != nodes[j]["floor"]):
                j += 1
            change = nodes[j]["floor"] - here["floor"]
            way = "elevator" if (here.get("is_elevator") or nxt.get("is_elevator")) else "stairs"
            parts.append(f"take the {way} {'up' if change > 0 else 'down'} {_floors(change)}")
            i = j
            continue
        if 0 < i + 1 < len(nodes) - 1:
            label = nxt.get("label")
            if (label and label not in seen and label != dest and not nxt.get("is_stairs")
                    and not nxt.get("is_elevator") and len(landmarks) < MAX_LANDMARKS):
                landmarks.append(label)
                parts.append(f"past {label if label.lower().startswith('the ') else 'the ' + label}")
            if label:
                seen.add(label)
        i += 1
    if dest:
        parts.append(_place(dest))
    if not parts:
        return "right here" if len(route.path) == 1 else "follow the corridor"
    return ", ".join(parts)


def describe_route(graph: nx.Graph, route: Route, dest_label: str | None = None) -> str:
    """Directions without the distance, for example "left of the elevators" (CONTRACTS section 4)."""
    return route_directions(graph, route, dest_label)
