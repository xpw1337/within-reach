"""The live SOS hub: one in-memory source of truth for cameras, responder phones and incidents.

Flow:
    vision person_down / fire_detected (or a manual fire report)
      -> incident opens at the camera's location
      -> at once, in parallel: alert the nearest available phone, start the simulated 911 agent,
         look up AEDs and extinguishers around the spot
      -> phone accepts: it gets a walking plan (extinguisher first if there is a fire, then the AED
         if it is a short detour, then the person), recomputed as the phone moves or the fire changes
      -> phone declines or lets the alert time out: the next nearest phone is alerted
      -> "I'm here", then resolve

Everything is pushed over websockets: consoles (dashboard) get the whole state, each phone gets its
own view. The hub never blocks on the network: lookups, routing and the 911 agent run as tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from agent.sos.call911 import Call911
from agent.sos.calls import Caller, normalize_phone
from agent.sos.geo import haversine_m
from agent.sos.places import Places, nearest
from agent.sos.routing import Router
from agent.sos.settings import SosSettings
from agent.sos.texts import Texter

log = logging.getLogger(__name__)

Send = Callable[[dict[str, Any]], Awaitable[None]]

OPEN = ("alerting", "en_route", "on_scene", "no_responders")
REPLAN_MOVE_M = 15
REPLAN_MIN_S = 6


def now_ms() -> int:
    return int(time.time() * 1000)


class Hub:
    def __init__(self, settings: SosSettings | None = None, *, places: Places | None = None,
                 router: Router | None = None, use_llm: bool = True, call_pace_s: float = 1.6,
                 caller: Caller | None = None, texter: Texter | None = None):
        self.s = settings or SosSettings()
        self.caller = caller or Caller()
        self.texter = texter or Texter()
        if self.s.offline:  # tests and offline demos never reach a real phone
            if caller is None:
                self.caller.enabled = False
            if texter is None:
                self.texter.enabled = False
        self.places = places or Places(self.s)
        self.router = router or Router(self.s)
        self.use_llm = use_llm
        self.call_pace_s = call_pace_s
        self.cameras: dict[str, dict[str, Any]] = {}
        self.responders: dict[str, dict[str, Any]] = {}
        self.manual_places: list[dict[str, Any]] = []
        self.incident: dict[str, Any] | None = None
        self.camera_places: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.snapshots: dict[str, bytes] = {}
        self.consoles: set[Send] = set()
        self.phone_sockets: dict[str, Send] = {}
        self._tasks: set[asyncio.Task] = set()
        self._offer_timer: asyncio.Task | None = None
        self._call: Call911 | None = None
        self._plan_lock = asyncio.Lock()
        self._last_plan: dict[str, Any] = {}
        self._dirty = False
        self._load()
        if self.s.camera_lat is not None and self.s.camera_lng is not None:
            self.set_camera("default", self.s.camera_lat, self.s.camera_lng, None,
                            self.s.camera_label or None, source="env", save=False)

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        try:
            data = json.loads(self.s.state_file.read_text())
        except (OSError, ValueError):
            return
        self.cameras = data.get("cameras") or {}
        self.manual_places = data.get("manual_places") or []
        if isinstance(getattr(self.places, "cache", None), dict):
            self.places.cache.update(data.get("osm_cache") or {})

    def _save(self) -> None:
        try:
            self.s.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.s.state_file.write_text(json.dumps({
                "cameras": self.cameras, "manual_places": self.manual_places,
                "osm_cache": getattr(self.places, "cache", {})}))
        except OSError as exc:
            log.warning("could not save %s: %s", self.s.state_file, exc)

    # ------------------------------------------------------------------ tasks and pushes

    def spawn(self, coro: Any, name: str = "sos") -> asyncio.Task | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # built outside an event loop (scripts, startup): skip background work
            coro.close()
            return None
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("%s task failed", name, exc_info=t.exception())

        task.add_done_callback(done)
        return task

    def changed(self) -> None:
        """Schedule one push of the new state to every socket (coalesced)."""
        if self._dirty:
            return
        self._dirty = True
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().call_soon(lambda: self.spawn(self._push(), "push"))

    async def _push(self) -> None:
        self._dirty = False
        state = self.console_state()
        for send in list(self.consoles):
            try:
                await send({"type": "state", "state": state})
            except Exception:  # noqa: BLE001 - a dead socket is removed by its handler
                self.consoles.discard(send)
        for rid, send in list(self.phone_sockets.items()):
            try:
                await send({"type": "state", **self.phone_state(rid)})
            except Exception:  # noqa: BLE001
                self.phone_sockets.pop(rid, None)

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._offer_timer:
            self._offer_timer.cancel()
        await self.places.aclose()
        await self.router.aclose()
        await self.caller.aclose()
        await self.texter.aclose()

    # ------------------------------------------------------------------ cameras and places

    def set_camera(self, camera_id: str, lat: float, lng: float, accuracy_m: float | None,
                   label: str | None, *, source: str = "dashboard", save: bool = True) -> dict[str, Any]:
        cam = {"id": camera_id, "lat": lat, "lng": lng, "accuracy_m": accuracy_m,
               "label": label or (self.cameras.get(camera_id) or {}).get("label") or "the camera area",
               "source": source, "updated_at": now_ms()}
        self.cameras[camera_id] = cam
        if save:
            self._save()
        self.spawn(self._prefetch(lat, lng), "prefetch")
        self.changed()
        return cam

    async def _prefetch(self, lat: float, lng: float) -> None:
        """Look up equipment around a camera ahead of time, so an incident has it at once."""
        try:
            items = await self.places.osm(lat, lng)
        except Exception as exc:  # noqa: BLE001
            log.warning("prefetch of AEDs/extinguishers failed: %s", exc)
            return
        self.camera_places = {"lat": lat, "lng": lng, "count": len(items), "at": now_ms()}
        self._save()
        self.changed()

    def camera_for(self, camera_id: str) -> dict[str, Any] | None:
        return self.cameras.get(camera_id) or self.cameras.get("default") or (
            next(iter(self.cameras.values())) if len(self.cameras) == 1 else None)

    def add_place(self, kind: str, lat: float, lng: float, label: str | None) -> dict[str, Any]:
        item = {"id": f"pin-{uuid.uuid4().hex[:8]}", "kind": kind, "lat": lat, "lng": lng,
                "label": label or ("AED" if kind == "aed" else "Fire extinguisher"), "source": "pinned"}
        self.manual_places.append(item)
        self._save()
        if self.incident:
            self._merge_places(self.incident.get("_osm") or [])
            self.spawn(self.replan(force=True), "replan")
        self.changed()
        return item

    def remove_place(self, place_id: str) -> bool:
        before = len(self.manual_places)
        self.manual_places = [p for p in self.manual_places if p["id"] != place_id]
        if len(self.manual_places) == before:
            return False
        self._save()
        if self.incident:
            self._merge_places(self.incident.get("_osm") or [])
            self.spawn(self.replan(force=True), "replan")
        self.changed()
        return True

    def _merge_places(self, osm: list[dict[str, Any]]) -> None:
        inc = self.incident
        if inc is None:
            return
        loc = inc["location"]
        everything = [*self.manual_places, *osm]
        inc["resources"]["aeds"] = nearest([p for p in everything if p["kind"] == "aed"], loc["lat"], loc["lng"])
        inc["resources"]["extinguishers"] = nearest(
            [p for p in everything if p["kind"] == "extinguisher"], loc["lat"], loc["lng"])

    async def _load_places(self, incident_id: str) -> None:
        inc = self.incident
        if inc is None:
            return
        loc = inc["location"]
        cached = getattr(self.places, "cached", lambda *a: None)(loc["lat"], loc["lng"])
        if cached is not None:  # show what we already know right away, then refresh
            inc["_osm"] = cached
            self._merge_places(cached)
            self.changed()
        try:
            osm = await self.places.osm(loc["lat"], loc["lng"])
            status, error = "ready", None
        except Exception as exc:  # noqa: BLE001
            osm, status, error = [], "error", str(exc)
        inc = self.incident
        if inc is None or inc["id"] != incident_id:
            return
        inc["_osm"] = osm
        self._merge_places(osm)
        inc["resources"]["status"] = status
        inc["resources"]["error"] = error
        n_aed, n_ext = len(inc["resources"]["aeds"]), len(inc["resources"]["extinguishers"])
        self._log(f"Found {n_aed} AED{'s' * (n_aed != 1)} and {n_ext} extinguisher{'s' * (n_ext != 1)} "
                  f"within {int(self.s.places_radius_m)} m" + (" (map lookup failed)" if error else ""), "places")
        self.changed()
        await self.replan(force=True)

    # ------------------------------------------------------------------ responders

    def responder_hello(self, rid: str, name: str | None, send: Send) -> None:
        r = self.responders.setdefault(rid, {"id": rid, "name": name or "Responder", "on_duty": True,
                                              "lat": None, "lng": None, "accuracy_m": None, "heading": None})
        if name:
            r["name"] = name
        r["connected"] = True
        r["last_seen"] = now_ms()
        self.phone_sockets[rid] = send
        self.changed()
        self._maybe_offer_again()

    def responder_gone(self, rid: str, send: Send) -> None:
        if self.phone_sockets.get(rid) is send:
            self.phone_sockets.pop(rid, None)
            r = self.responders.get(rid)
            if r:
                r["connected"] = False
            self.changed()

    def responder_update(self, rid: str, msg: dict[str, Any]) -> None:
        r = self.responders.get(rid)
        if r is None:
            return
        r["last_seen"] = now_ms()
        if msg.get("lat") is not None and msg.get("lng") is not None:
            r["lat"], r["lng"] = float(msg["lat"]), float(msg["lng"])
            r["accuracy_m"] = msg.get("accuracy_m")
            r["located_at"] = now_ms()
        if msg.get("heading") is not None:
            r["heading"] = msg["heading"]
        if "on_duty" in msg:
            r["on_duty"] = bool(msg["on_duty"])
            if r["on_duty"]:
                self._maybe_offer_again()
        if msg.get("name"):
            r["name"] = str(msg["name"])[:60]
        if "phone" in msg:
            phone = normalize_phone(str(msg.get("phone") or ""))
            if phone != r.get("phone") or "text_line" not in r:
                r["text_line"] = None
                if phone and self.texter.configured:
                    self.spawn(self._find_text_line(r["id"], phone), "text-line")
            r["phone"] = phone
        inc = self.incident
        if inc and inc.get("responder_id") == rid and inc["status"] == "en_route":
            self._refresh_responder_distance()
            self.spawn(self.replan(), "replan")
        self.changed()

    def _eligible(self, exclude: set[str]) -> list[dict[str, Any]]:
        now = now_ms()
        out = []
        for r in self.responders.values():
            if r["id"] in exclude or not r.get("on_duty"):
                continue
            live = r.get("connected") and now - (r.get("last_seen") or 0) <= self.s.responder_stale_s * 1000
            # With the app closed, a responder can still be reached by a call or a text, if we know
            # their number and roughly where they were recently.
            callable_ = ((self.caller.configured or self.texter.configured) and r.get("phone")
                         and now - (r.get("located_at") or 0) <= self.s.call_reach_s * 1000)
            if live or callable_:
                out.append(r)
        loc = self.incident["location"] if self.incident else None

        def key(r: dict[str, Any]) -> tuple[int, float]:
            if loc is None or r.get("lat") is None:
                return (1, 0.0)
            return (0, haversine_m(r["lat"], r["lng"], loc["lat"], loc["lng"]))

        return sorted(out, key=key)

    # ------------------------------------------------------------------ incidents

    def _log(self, text: str, kind: str = "info") -> None:
        if self.incident is not None:
            self.incident["timeline"].append({"at": now_ms(), "text": text, "kind": kind})

    async def open_incident(self, kind: str, camera_id: str, *, witnessed: bool | None = None,
                            snapshot: bytes | None = None, fire: dict[str, Any] | None = None,
                            location: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open an incident, or attach to the open one. Returns the incident."""
        inc = self.incident
        if inc and inc["status"] in OPEN:
            if kind == "fire" and fire:
                self.set_fire(fire)
            elif kind == "fall" and inc["kind"] == "fire":
                inc["kind"] = "fall"
                self._log("Camera: a person is down near the fire", "vision")
                if self._call:
                    self._call.update("Update: a person is now down at the scene.")
                self.spawn(self.replan(force=True), "replan")
                self.changed()
            return inc
        cam = self.camera_for(camera_id)
        loc = location or ({"lat": cam["lat"], "lng": cam["lng"], "accuracy_m": cam.get("accuracy_m"),
                            "label": cam.get("label")} if cam else None)
        if loc is None:
            raise LookupError("camera location unknown: open the dashboard on the camera laptop and allow "
                              "location, or set CAMERA_LAT and CAMERA_LNG")
        if inc:
            self._archive()
        iid = uuid.uuid4().hex[:12]
        inc = {
            "id": iid, "kind": kind, "camera_id": camera_id, "status": "alerting", "started_at": now_ms(),
            "witnessed": witnessed, "location": loc, "address": None, "has_snapshot": bool(snapshot),
            "fire": None, "offers": [], "responder_id": None, "accepted_at": None, "arrived_at": None,
            "resolved_at": None, "resources": {"aeds": [], "extinguishers": [], "status": "loading", "error": None},
            "plan": None, "collected": [], "call": {"status": "dialing", "lines": [], "simulated": True},
            "timeline": [], "vision": {},
        }
        self.incident = inc
        if snapshot:
            self.snapshots = {iid: snapshot}
        self._log("Camera: person fell" + (" (seen falling)" if witnessed else "") if kind == "fall"
                  else "Fire reported", "vision" if kind == "fall" or (fire or {}).get("source") == "camera" else "manual")
        if fire:
            self.set_fire(fire, announce=False)
        # All at once: alert, 911 agent, map lookups.
        self._offer_next()
        self._start_call()
        self.spawn(self._load_places(iid), "places")
        self.spawn(self._reverse_geocode(iid), "geocode")
        self.changed()
        return inc

    def _archive(self) -> None:
        inc = self.incident
        if inc is None:
            return
        self.history.insert(0, {k: inc[k] for k in ("id", "kind", "status", "started_at", "resolved_at")})
        del self.history[10:]
        self.incident = None

    def _offer_next(self) -> None:
        inc = self.incident
        if inc is None or inc.get("responder_id") or inc["status"] not in ("alerting", "no_responders"):
            return
        if any(o["status"] == "sent" for o in inc["offers"]):
            return
        tried = {o["responder_id"] for o in inc["offers"]}
        cands = self._eligible(tried)
        if not cands:
            if inc["status"] != "no_responders":
                inc["status"] = "no_responders"
                self._log("No available responder nearby: waiting for one to come on duty", "dispatch")
                if self._call:
                    self._call.update("Update: no volunteer responder is available nearby.")
            self.changed()
            return
        r = cands[0]
        loc = inc["location"]
        dist = None if r.get("lat") is None else round(haversine_m(r["lat"], r["lng"], loc["lat"], loc["lng"]))
        offer = {"id": uuid.uuid4().hex[:10], "responder_id": r["id"], "name": r["name"], "status": "sent",
                 "sent_at": now_ms(), "responded_at": None, "distance_m": dist,
                 "expires_at": now_ms() + int(self.s.accept_timeout_s * 1000)}
        will_call = bool(r.get("phone") and self.caller.configured)
        will_text = bool(r.get("phone") and self.texter.configured)
        # Reached by call or text with the app closed: give them time to open it.
        slow = will_call or (will_text and not r.get("connected"))
        timeout = self.s.accept_timeout_call_s if slow else self.s.accept_timeout_s
        offer["expires_at"] = now_ms() + int(timeout * 1000)
        offer["call"] = "calling" if will_call else ("no number" if not r.get("phone") else "off")
        inc["offers"].append(offer)
        inc["status"] = "alerting"
        self._log(f"Alert sent to {r['name']}" + (f" ({dist} m away)" if dist is not None else ""), "dispatch")
        if r.get("phone") and self.caller.configured:
            self.spawn(self._ring(offer, r, inc), "call")
        if r.get("phone") and self.texter.configured:
            self.spawn(self._text(offer, r, inc), "text")
        if self._offer_timer:
            self._offer_timer.cancel()
        self._offer_timer = self.spawn(self._expire(offer["id"], timeout), "offer-timer")
        self.changed()

    async def _find_text_line(self, rid: str, phone: str) -> None:
        """Read-only: does this phone already have a Photon iMessage line? (Shown on the dashboard.)"""
        try:
            line = await self.texter._line_for(phone)
        except Exception:  # noqa: BLE001 - no line yet, or Photon unreachable
            return
        r = self.responders.get(rid)
        if r is not None and r.get("phone") == phone:
            r["text_line"] = line
            self.changed()

    async def _text(self, offer: dict[str, Any], r: dict[str, Any], inc: dict[str, Any]) -> None:
        """Text the responder too, so the alert reaches a phone whose app is closed."""
        place = inc["location"].get("label") or "near you"
        what = "Someone has collapsed" if inc["kind"] == "fall" else "Fire reported"
        dist = f", about {offer['distance_m']} m from you" if offer.get("distance_m") is not None else ""
        secs = max(1, round((offer["expires_at"] - now_ms()) / 1000))
        text = (f"\U0001F6A8 Within Reach: {what} at {place}{dist}. Open the Within Reach app now to accept "
                f"(you have {secs} seconds).")
        res = await self.texter.send(r["phone"], text, key=f"wr-alert-{offer['id']}")
        offer["text"] = "sent" if res.sent else f"not sent: {res.reason}"
        self._log(f"Texted {r['name']}" if res.sent else f"Text to {r['name']} not sent ({res.reason})", "text")
        self.changed()

    async def _ring(self, offer: dict[str, Any], r: dict[str, Any], inc: dict[str, Any]) -> None:
        """Phone the responder so the alert reaches them with the app closed."""
        place = inc["location"].get("label") or "a spot near you"
        what = "Someone has collapsed" if inc["kind"] == "fall" else "A fire was detected"
        dist = f", about {offer['distance_m']} meters from you" if offer.get("distance_m") is not None else ""
        text = f"Within Reach emergency alert for {r['name']}. {what} at {place}{dist}."
        res = await self.caller.call(r["phone"], text, offer["id"])
        offer["call"] = "rang" if res.placed else f"not placed: {res.reason}"
        offer["call_sid"] = res.sid
        self._log(f"Calling {r['name']}" if res.placed else f"Call to {r['name']} not placed ({res.reason})", "call")
        self.changed()

    async def _expire(self, offer_id: str, timeout: float) -> None:
        await asyncio.sleep(timeout)
        self.respond(offer_id, None, "timeout")

    def _maybe_offer_again(self) -> None:
        inc = self.incident
        if inc and inc["status"] == "no_responders":
            # Someone new is available: everyone who never answered may be asked again.
            inc["offers"] = [o for o in inc["offers"] if o["status"] == "declined"]
            self._offer_next()

    def respond(self, offer_id: str, rid: str | None, answer: str) -> dict[str, Any]:
        """``answer`` is accepted, declined or timeout. Returns ``{ok, reason?}``."""
        inc = self.incident
        offer = next((o for o in (inc or {}).get("offers", []) if o["id"] == offer_id), None)
        if inc is None or offer is None:
            return {"ok": False, "reason": "This alert is no longer active."}
        if rid is not None and offer["responder_id"] != rid:
            return {"ok": False, "reason": "This alert was for someone else."}
        if offer["status"] != "sent":
            return {"ok": False, "reason": f"Already {offer['status']}."}
        offer["status"] = answer
        offer["responded_at"] = now_ms()
        if self._offer_timer and answer != "timeout":
            self._offer_timer.cancel()
        if answer == "accepted":
            inc["responder_id"] = offer["responder_id"]
            inc["accepted_at"] = now_ms()
            inc["status"] = "en_route"
            self._log(f"{offer['name']} accepted and is on the way", "dispatch")
            self._refresh_responder_distance()
            if self._call:
                self._call.update(self._responder_update_text("accepted"))
            self.spawn(self.replan(force=True), "replan")
        else:
            self._log(f"{offer['name']} {'declined' if answer == 'declined' else 'did not answer'}: "
                      "alerting the next nearest", "dispatch")
            self._offer_next()
        self.changed()
        return {"ok": True}

    def arrived(self, rid: str) -> dict[str, Any]:
        inc = self.incident
        if inc is None or inc.get("responder_id") != rid:
            return {"ok": False, "reason": "You are not assigned to an active emergency."}
        if inc["status"] != "on_scene":
            inc["status"] = "on_scene"
            inc["arrived_at"] = now_ms()
            name = self.responders.get(rid, {}).get("name", "The responder")
            self._log(f"{name} is with the person", "dispatch")
            if self._call:
                self._call.update(self._responder_update_text("arrived"))
            self.changed()
        return {"ok": True}

    def collected(self, rid: str, what: str) -> dict[str, Any]:
        """The responder has the AED or extinguisher: later plans skip that stop."""
        inc = self.incident
        if inc is None or inc.get("responder_id") != rid or what not in ("aed", "extinguisher"):
            return {"ok": False, "reason": "Nothing to pick up right now."}
        if what not in inc["collected"]:
            inc["collected"].append(what)
            name = self.responders.get(rid, {}).get("name", "The responder")
            self._log(f"{name} has the {'AED' if what == 'aed' else 'fire extinguisher'}", "dispatch")
            if self._call and what == "aed":
                self._call.update("Update: the volunteer has an AED and is heading to the person.")
            self.spawn(self.replan(force=True), "replan")
            self.changed()
        return {"ok": True}

    def resolve(self, reason: str = "resolved") -> bool:
        inc = self.incident
        if inc is None or inc["status"] not in OPEN:
            return False
        inc["status"] = "resolved"
        inc["resolved_at"] = now_ms()
        self._log(f"Incident closed ({reason})", "info")
        if self._offer_timer:
            self._offer_timer.cancel()
        for o in inc["offers"]:
            if o["status"] == "sent":
                o["status"] = "cancelled"
        if self._call:
            self.spawn(self._call.end(reason), "call-end")
        self.changed()
        return True

    def reset(self) -> None:
        self.resolve("reset")
        self._archive()
        self.snapshots.clear()
        self._last_plan.clear()
        self.changed()

    def _refresh_responder_distance(self) -> None:
        inc = self.incident
        if not inc or not inc.get("responder_id"):
            return
        r = self.responders.get(inc["responder_id"]) or {}
        if r.get("lat") is not None:
            inc["responder_distance_m"] = round(haversine_m(r["lat"], r["lng"], inc["location"]["lat"],
                                                            inc["location"]["lng"]))

    # ------------------------------------------------------------------ fire

    def set_fire(self, fire: dict[str, Any], *, announce: bool = True) -> None:
        inc = self.incident
        if inc is None:
            return
        loc = inc["location"]
        lat = float(fire.get("lat", loc["lat"]))
        lng = float(fire.get("lng", loc["lng"]))
        was = inc.get("fire")
        inc["fire"] = {"active": True, "lat": lat, "lng": lng,
                       "radius_m": float(fire.get("radius_m") or self.s.fire_radius_m),
                       "source": fire.get("source", "manual"), "label": fire.get("label") or "fire",
                       "conf": fire.get("conf"), "at": now_ms()}
        if announce and not (was and was.get("active")):
            where = "at the camera" if fire.get("source") == "camera" else "on the map"
            self._log(f"Fire reported {where}: routes now avoid it and include an extinguisher", "fire")
            if self._call:
                self._call.update("Update: there is also a fire at the scene.")
        self.spawn(self.replan(force=True), "replan")
        self.changed()

    def clear_fire(self, source: str) -> None:
        inc = self.incident
        if inc is None or not (inc.get("fire") or {}).get("active"):
            return
        if source == "camera" and inc["fire"].get("source") != "camera":
            return  # a manual report is only cleared by hand
        inc["fire"]["active"] = False
        self._log("Fire no longer seen" if source == "camera" else "Fire report cleared", "fire")
        self.spawn(self.replan(force=True), "replan")
        self.changed()

    # ------------------------------------------------------------------ vision follow-ups

    def vision_signal(self, kind: str) -> None:
        inc = self.incident
        if inc is None or inc["status"] not in OPEN:
            return
        inc["vision"][kind] = now_ms()
        text = {"responsive": "Camera: the person raised a hand (may be responsive)",
                "possible_seizure": "Camera: rhythmic movement, possible seizure",
                "responder_arrived": "Camera: someone is now beside the person"}.get(kind, kind)
        self._log(text, "vision")
        if self._call and kind in ("responsive", "possible_seizure"):
            self._call.update("Update: " + text.split(": ", 1)[1] + ".")
        self.changed()

    # ------------------------------------------------------------------ planning

    async def replan(self, force: bool = False) -> None:
        inc = self.incident
        if inc is None or not inc.get("responder_id") or inc["status"] not in ("en_route", "on_scene"):
            return
        r = self.responders.get(inc["responder_id"]) or {}
        if r.get("lat") is None:
            return
        start = (r["lat"], r["lng"])
        last = self._last_plan
        if not force and last.get("incident") == inc["id"]:
            moved = haversine_m(*start, *last["start"])
            if moved < REPLAN_MOVE_M or time.time() - last["t"] < REPLAN_MIN_S:
                return
        async with self._plan_lock:
            self._last_plan = {"incident": inc["id"], "start": start, "t": time.time()}
            plan = await self.build_plan(inc, start)
            if self.incident is inc:
                inc["plan"] = plan
                self.changed()

    async def build_plan(self, inc: dict[str, Any], start: tuple[float, float]) -> dict[str, Any]:
        loc = inc["location"]
        person = (loc["lat"], loc["lng"])
        fire = inc.get("fire") if (inc.get("fire") or {}).get("active") else None
        res = inc["resources"]
        stops: list[tuple[str, dict[str, Any]]] = []
        here = start

        def trip(a: tuple[float, float], p: dict[str, Any], b: tuple[float, float]) -> float:
            return haversine_m(*a, p["lat"], p["lng"]) + haversine_m(p["lat"], p["lng"], *b)

        got = set(inc.get("collected") or [])
        if fire and "extinguisher" not in got:
            fz = (fire["lat"], fire["lng"])
            usable = [e for e in res["extinguishers"]
                      if haversine_m(e["lat"], e["lng"], *fz) > fire["radius_m"]]
            if usable:
                ext = min(usable, key=lambda e: trip(here, e, person))
                stops.append(("extinguisher", ext))
                here = (ext["lat"], ext["lng"])
        if inc["kind"] == "fall" and res["aeds"] and "aed" not in got:
            aed = min(res["aeds"], key=lambda a: trip(here, a, person))
            detour = trip(here, aed, person) - haversine_m(*here, *person)
            if detour <= self.s.aed_max_detour_m:
                stops.append(("aed", aed))
        stops.append(("person", {"lat": loc["lat"], "lng": loc["lng"],
                                 "label": loc.get("label") or "the person"}))
        points = [start] + [(p["lat"], p["lng"]) for _, p in stops]
        legs_raw = await asyncio.gather(*(self.router.route(points[i], points[i + 1], fire)
                                          for i in range(len(stops))))
        legs = []
        for (kind, p), leg in zip(stops, legs_raw, strict=True):
            legs.append({"kind": kind, "to": {"lat": p["lat"], "lng": p["lng"], "label": p.get("label"),
                                              "id": p.get("id"), "source": p.get("source")}, **leg})
        skipped_aed = None
        if inc["kind"] == "fall" and res["aeds"] and "aed" not in got and not any(k == "aed" for k, _ in stops):
            skipped_aed = res["aeds"][0]
        return {"from": list(start), "legs": legs, "updated_at": now_ms(),
                "total_m": round(sum(leg["distance_m"] for leg in legs)),
                "total_s": round(sum(leg["duration_s"] for leg in legs)),
                "aed_too_far": skipped_aed, "no_extinguisher": bool(fire) and not any(
                    k == "extinguisher" for k, _ in stops) and "extinguisher" not in got,
                "collected": sorted(got)}

    # ------------------------------------------------------------------ 911 agent

    def _start_call(self) -> None:
        inc = self.incident
        if inc is None:
            return
        iid = inc["id"]

        async def emit(who: str, text: str) -> None:
            cur = self.incident
            if cur is None or cur["id"] != iid:
                return
            cur["call"]["lines"].append({"who": who, "text": text, "at": now_ms()})
            if who == "dispatcher" and cur["call"]["status"] == "dialing":
                cur["call"]["status"] = "connected"
            if text.startswith("Call ended"):
                cur["call"]["status"] = "ended"
            self.changed()

        self._call = Call911(self._facts, emit, use_llm=self.use_llm, pace_s=self.call_pace_s)
        self._log("911 agent calling (simulated)", "911")
        self.spawn(self._call.run(), "call911")

    def _responder_update_text(self, what: str) -> str:
        inc = self.incident or {}
        r = self.responders.get(inc.get("responder_id") or "", {})
        if what == "arrived":
            return f"Update: volunteer {r.get('name', '')} is now with the person."
        d = inc.get("responder_distance_m")
        return f"Update: volunteer {r.get('name', '')} accepted and is on the way" + (
            f", about {d} meters away." if d is not None else ".")

    def _facts(self) -> dict[str, Any]:
        inc = self.incident or {}
        loc = inc.get("location") or {}
        r = self.responders.get(inc.get("responder_id") or "")
        pending = next((o for o in inc.get("offers", []) if o["status"] == "sent"), None)
        fire = inc.get("fire") or {}
        aeds = (inc.get("resources") or {}).get("aeds") or []
        return {
            "kind": inc.get("kind"),
            "time": datetime.fromtimestamp((inc.get("started_at") or now_ms()) / 1000).strftime("%I:%M %p").lstrip("0"),
            "address": inc.get("address"),
            "coords": f"{loc.get('lat', 0):.5f}, {loc.get('lng', 0):.5f}" if loc else None,
            "place": loc.get("label"),
            "witnessed": inc.get("witnessed"),
            "responsive": bool((inc.get("vision") or {}).get("responsive")),
            "fire": bool(fire.get("active")),
            "fire_label": fire.get("label"),
            "responder": None if r is None else {
                "name": r["name"], "status": inc.get("status"), "distance_m": inc.get("responder_distance_m")},
            "alerting": pending["name"] if pending else None,
            "aed": None if not aeds else {"distance_m": round(aeds[0]["distance_m"]), "label": aeds[0]["label"]},
        }

    async def _reverse_geocode(self, iid: str) -> None:
        inc = self.incident
        if inc is None or self.s.offline:
            return
        loc = inc["location"]
        try:
            http = await self.places._http()
            r = await http.get(f"{self.s.nominatim_url}/reverse", params={
                "lat": loc["lat"], "lon": loc["lng"], "format": "jsonv2", "zoom": 18}, timeout=5)
            r.raise_for_status()
            addr = r.json().get("display_name")
        except Exception as exc:  # noqa: BLE001
            log.info("reverse geocode failed: %s", exc)
            return
        if self.incident is not None and self.incident["id"] == iid and addr:
            self.incident["address"] = ", ".join(addr.split(", ")[:4])
            self.changed()

    # ------------------------------------------------------------------ views

    def _public_incident(self) -> dict[str, Any] | None:
        inc = self.incident
        if inc is None:
            return None
        return {k: v for k, v in inc.items() if not k.startswith("_")}

    def console_state(self) -> dict[str, Any]:
        now = now_ms()
        responders = []
        for r in self.responders.values():
            stale = now - (r.get("last_seen") or 0) > self.s.responder_stale_s * 1000
            phone = r.get("phone")
            responders.append({**r, "phone": f"•••{phone[-4:]}" if phone else None,
                               "available": bool(r.get("connected") and r.get("on_duty") and not stale),
                               "callable": bool(phone and (self.caller.configured or self.texter.configured))})
        return {
            "server_time": now,
            "cameras": list(self.cameras.values()),
            "responders": responders,
            "incident": self._public_incident(),
            "history": self.history,
            "pinned_places": self.manual_places,
            "camera_places": self.camera_places,
            "settings": {"accept_timeout_s": self.s.accept_timeout_s, "fire_radius_m": self.s.fire_radius_m,
                         "calls": self.caller.configured, "texts": self.texter.configured},
        }

    def phone_state(self, rid: str) -> dict[str, Any]:
        r = self.responders.get(rid) or {}
        inc = self.incident
        offer = None
        mission = None
        if inc and inc["status"] in OPEN:
            o = next((o for o in inc["offers"] if o["responder_id"] == rid and o["status"] == "sent"), None)
            if o:
                loc = inc["location"]
                offer = {**o, "kind": inc["kind"], "place": loc.get("label"), "address": inc.get("address"),
                         "fire": bool((inc.get("fire") or {}).get("active")), "witnessed": inc.get("witnessed"),
                         "location": {"lat": loc["lat"], "lng": loc["lng"]}, "incident_id": inc["id"]}
            if inc.get("responder_id") == rid:
                mission = {k: inc[k] for k in ("id", "kind", "status", "location", "address", "fire", "plan",
                                               "resources", "witnessed", "vision", "accepted_at", "arrived_at",
                                               "collected")}
                mission["timeline"] = inc["timeline"][-8:]
        elif inc and inc.get("responder_id") == rid and inc["status"] == "resolved":
            mission = {"id": inc["id"], "status": "resolved", "kind": inc["kind"]}
        return {"me": {k: r.get(k) for k in ("id", "name", "on_duty", "lat", "lng", "accuracy_m")}
                | {"has_phone": bool(r.get("phone")), "calls": self.caller.configured},
                "offer": offer, "mission": mission, "server_time": now_ms(),
                "accept_timeout_s": self.s.accept_timeout_s}
