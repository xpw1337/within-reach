"""Structured facts and fixed wording for the three documents (spec section 9.6).

Pure: no LLM, no database. The tools layer builds the facts (with display numbers already
converted by shared.thresholds), calls the LLM for the owner-letter body, and runs the checker
here. The emergency card and the registry list are deterministic templates.

Rules carried into the wording:
- Missing equipment is "not visible in the scan", never "no AED" (spec section 16).
- The owner letter is a draft and is never sent automatically.
- Every number in an LLM-written body must appear in the facts; otherwise the body is
  regenerated once, then replaced by the plain template.
"""

from __future__ import annotations

import re
from typing import Any

DRAFT_NOTICE = "Draft for the building owner. Not sent automatically; review before use."
SCAN_DISCLAIMER = ("These findings come from a building scan. Equipment that is not visible in the "
                   "scan may still be on site; please confirm on site.")
REGISTRY_INSTRUCTIONS = ("Please confirm that every AED in the building is registered with your local "
                         "911 center and with a national AED registry, so dispatchers can send callers "
                         "to it.")
ESTIMATE_NOTE = "People counts are estimates from a building-code occupant load table, not a head count."
NAMES = {"aed": "AED", "extinguisher": "fire extinguisher", "exit": "exit"}
PLURALS = {"aed": "AEDs", "extinguisher": "fire extinguishers", "exit": "exits"}

# Numbers that fixed wording itself uses and that are therefore always allowed.
FIXED_NUMBERS = ("911",)

LETTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"body_md": {"type": "string"}},
    "required": ["body_md"],
    "additionalProperties": False,
}

LETTER_SYSTEM = (
    "You draft a short, plain-language letter body to a building owner about life-safety equipment "
    "access, from the JSON facts you are given. Use only the facts. Every number you write must "
    "appear exactly as written in the facts; do not compute, round, convert or invent any number, "
    "date, phone number or statistic. Never say a building has no AED, extinguisher or exit: say it is "
    "not visible in the scan. Cover, in order: what we measured, the gaps found, the recommended "
    "placement, and asking the owner to confirm and register their AEDs. Do not add a greeting "
    "header, signature, title or disclaimer; those are added separately. Markdown paragraphs only, "
    "under 250 words. Return JSON {\"body_md\": \"...\"}."
)


# ---------------------------------------------------------------------------
# Number checker
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


def _normalize(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def numbers_in(text: str) -> list[str]:
    """Normalized numeric tokens in ``text`` (markdown list markers at line starts are ignored)."""
    return [_normalize(m) for m in _NUMBER.findall(_LIST_MARKER.sub(" ", text))]


def _collect_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _collect_strings(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_strings(v, out)
    elif isinstance(value, bool) or value is None:
        return
    else:
        out.append(str(value))


def allowed_numbers(facts: dict) -> set[str]:
    strings: list[str] = list(FIXED_NUMBERS)
    _collect_strings(facts, strings)
    allowed: set[str] = set()
    for s in strings:
        allowed.update(numbers_in(s))
    return allowed


def unexpected_numbers(text: str, facts: dict) -> list[str]:
    """Numbers in ``text`` that do not appear in the facts. Empty means the text passes."""
    allowed = allowed_numbers(facts)
    return sorted({n for n in numbers_in(text) if n not in allowed})


_BANNED_ABSENCE = re.compile(r"\b(?:no|without an?|lacks? an?|does not have an?)\s+"
                             r"(?:AEDs?|defibrillators?|(?:fire )?extinguishers?|exits?)\b(?![^.]*visible)",
                             re.IGNORECASE)


def wording_problems(text: str) -> list[str]:
    """Absence claims that do not say "visible in the scan"."""
    return [m.group(0) for m in _BANNED_ABSENCE.finditer(text)]


def check_letter_body(text: str, facts: dict) -> list[str]:
    problems = [f"number not in facts: {n}" for n in unexpected_numbers(text, facts)]
    problems += [f"absence claim without 'visible in the scan': {w!r}" for w in wording_problems(text)]
    return problems


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _round(x: float | None) -> str | None:
    return None if x is None else str(round(x))


def _pct(frac: float | None) -> str | None:
    return None if frac is None else f"{round(frac * 100)}%"


def _unit(asset_type: str) -> str:
    return "s round trip" if asset_type == "aed" else "s one-way walk"


def _time(asset_type: str, shown_s: float | None) -> str | None:
    return None if shown_s is None else f"{round(shown_s)} {_unit(asset_type)}"


def _place(item: dict) -> dict:
    floor = item.get("floor")
    return {"where": item.get("label") or item.get("room_type") or "location unlabeled",
            "level": None if floor is None else str(floor)}


def build_facts(
    *,
    building: dict,
    score: dict | None,
    sweeps_scanned: int,
    assets: dict[str, list[dict]],
    fix: dict | None,
    fix_where: dict | None,
    ems_door: dict | None,
    occupancy_basis: str | None,
    show_s: Any,
) -> dict:
    """Display-ready facts. ``show_s(asset_type, one_way_s)`` is shared.thresholds.display_seconds,
    so AED times are round trip here and nowhere is the conversion done inline.

    ``score`` is a building_scores row (one-way seconds), ``assets`` maps a type to its current
    asset rows, ``fix`` is a fixes row and ``fix_where`` the proposed sweep's node data.
    """
    measured: dict[str, Any] = {}
    if score:
        for gap, prefix in (("aed", "aed"), ("extinguisher", "ext"), ("exit", "exit")):
            worst = score.get(f"{prefix}_worst_s")
            measured[gap] = {
                "visible_in_scan": len(assets.get(gap, [])),
                "worst_case": _time(gap, show_s(gap, worst)),
                "red_area": _pct(score.get(f"{prefix}_red_frac")),
            }
    facts: dict[str, Any] = {
        "building": {k: building.get(k) for k in ("name", "address", "city", "property_type")},
        "scan_positions": str(sweeps_scanned),
        "measured": measured,
        "worst_gap": NAMES.get((score or {}).get("worst_gap") or "", None),
        "people_at_risk_estimate": None if not score or score.get("people_at_risk") is None
        else str(score["people_at_risk"]),
        "occupancy_estimate": None if building.get("occupancy_est") is None else str(building["occupancy_est"]),
        "occupancy_basis": occupancy_basis,
        "stairs_only": bool(score and score.get("stairs_only")),
        "blocked_exits": None if not score else str(score.get("blocked_exits") or 0),
        "aeds": [_place(a) for a in assets.get("aed", [])],
        "extinguishers": [_place(a) for a in assets.get("extinguisher", [])],
        "exits": [_place(a) for a in assets.get("exit", [])],
        "ems_door": None if not ems_door else {
            "door": ems_door.get("desc"),
            "staging": (ems_door.get("staging") or {}).get("desc"),
            "hydrant": (ems_door.get("hydrant") or {}).get("desc"),
        },
        "targets": {
            "aed": "round trip on foot from any scanned position, under the configured target",
            "extinguisher": "one-way walk within the configured travel distance",
            "exit": "one-way walk within the configured travel distance",
        },
        "recommendation": None,
    }
    if fix and fix.get("sweep_id"):
        gap = fix["asset_type"]
        where = _place(fix_where or {})
        facts["recommendation"] = {
            "add_one": NAMES[gap],
            "where": where["where"],
            "level": where["level"],
            "worst_case_before": _time(gap, show_s(gap, fix.get("before_worst_s"))),
            "worst_case_after": _time(gap, show_s(gap, fix.get("after_worst_s"))),
            "red_area_before": _pct(fix.get("before_red_frac")),
            "red_area_after": _pct(fix.get("after_red_frac")),
        }
    return facts


def letter_user_text(facts: dict, problems: list[str] | None = None) -> str:
    import json

    text = "Facts (JSON):\n" + json.dumps(facts, indent=2, sort_keys=True)
    if problems:
        text += ("\n\nYour previous draft was rejected for: " + "; ".join(problems) +
                 ". Write it again using only the facts.")
    return text


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _title(facts: dict) -> str:
    return facts["building"].get("name") or facts["building"].get("address") or "Building"


def _address(facts: dict) -> str:
    b = facts["building"]
    return ", ".join(x for x in (b.get("address"), b.get("city")) if x) or "--"


def _level(place: dict) -> str:
    return f" (level {place['level']})" if place.get("level") is not None else ""


def wrap_letter(facts: dict, body_md: str) -> str:
    """Fixed header and footer around a letter body (LLM-written or template)."""
    return "\n\n".join([
        f"# Life-safety access findings: {_title(facts)}",
        f"_{DRAFT_NOTICE}_",
        f"{_address(facts)}",
        body_md.strip(),
        "## Registering your AEDs",
        REGISTRY_INSTRUCTIONS,
        f"_{SCAN_DISCLAIMER} {ESTIMATE_NOTE}_",
    ]) + "\n"


def owner_letter_template(facts: dict) -> str:
    """Plain body used when the LLM is unavailable or its drafts fail the checker."""
    lines = [(f"We measured walking access to life-safety equipment from {facts['scan_positions']} "
              "scanned positions in your building.")]
    for gap in ("aed", "extinguisher", "exit"):
        m = facts["measured"].get(gap)
        if not m:
            continue
        if not m["visible_in_scan"]:
            lines.append(f"- {PLURALS[gap].capitalize()}: none visible in the scan, so every scanned "
                         f"position counts as outside the target.")
        else:
            lines.append(f"- {PLURALS[gap].capitalize()}: worst case {m['worst_case'] or '--'}; "
                         f"{m['red_area'] or '--'} of scanned positions are outside the target.")
    if facts.get("stairs_only"):
        lines.append("- Some upper-floor positions reach an exit only by stairs.")
    if facts.get("blocked_exits") not in (None, "0"):
        lines.append(f"- Exits that look blocked in the scan: {facts['blocked_exits']}.")
    if facts.get("people_at_risk_estimate") is not None:
        lines.append(f"\nAbout {facts['people_at_risk_estimate']} people may be in the largest gap "
                     "(estimate).")
    rec = facts.get("recommendation")
    if rec:
        lines.append(
            f"\n**Recommendation:** add one {rec['add_one']} at {rec['where']}{_level(rec)}. In our model "
            f"this changes the worst case from {rec['worst_case_before'] or '--'} to "
            f"{rec['worst_case_after'] or '--'}, and the area outside the target from "
            f"{rec['red_area_before'] or '--'} to {rec['red_area_after'] or '--'}.")
    else:
        lines.append("\nWe did not find a single placement that improves these numbers.")
    return "\n".join(lines)


def emergency_card(facts: dict) -> str:
    """One printable page. Deterministic: no LLM."""
    def items(places: list[dict], plural: str) -> list[str]:
        if not places:
            return [f"- No {plural} visible in the scan. Ask staff where the nearest one is."]
        return [f"- {p['where']}{_level(p)}" for p in places]

    door = facts.get("ems_door") or {}
    out = [
        f"# Emergency card: {_title(facts)}",
        f"**Address:** {_address(facts)}",
        "**In an emergency, call 911 first.**",
        "## AEDs",
        *items(facts["aeds"], "AED"),
        "## Fire extinguishers",
        *items(facts["extinguishers"], "fire extinguisher"),
        "## Exits",
        *items(facts["exits"], "exit"),
        "## For EMS",
        f"- Best ambulance entrance: {door.get('door') or '--'}",
        f"- Staging spot: {door.get('staging') or '--'}",
        f"- Nearest hydrant: {door.get('hydrant') or '--'}",
        f"_{SCAN_DISCLAIMER}_",
    ]
    return "\n\n".join(out[:3]) + "\n\n" + "\n".join(out[3:]) + "\n"


def registry_list(facts: dict) -> str:
    """AEDs visible in the scan, for confirming registration. Deterministic: no LLM."""
    out = [f"# AED registry list: {_title(facts)}", f"**Address:** {_address(facts)}", REGISTRY_INSTRUCTIONS]
    if facts["aeds"]:
        out.append("| # | Location | Level |\n|---|---|---|\n" + "\n".join(
            f"| {i} | {p['where']} | {p['level'] if p['level'] is not None else '--'} |"
            for i, p in enumerate(facts["aeds"], start=1)))
    else:
        out.append("No AED visible in the scan. If the building has one, please register it.")
    out.append(f"_{SCAN_DISCLAIMER}_")
    return "\n\n".join(out) + "\n"
