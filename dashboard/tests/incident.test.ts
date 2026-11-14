// Live-page logic on synthetic rows (test fixtures only).
import { describe, expect, it } from "vitest";
import { confirmState, describeEvent, fall911Timer, latencies, latestRouteSpeak, originOf } from "@/lib/incident";
import type { Incident, IncidentEvent } from "@/lib/rows";

const base: Incident = {
  id: "i1",
  type: "cardiac",
  status: "awaiting_confirm",
  camera_id: "cam-lobby-1",
  building_id: null,
  witnessed: true,
  modifiers: [],
  scene_safe: null,
  hazards: [],
  verification: null,
  confirmed_by: null,
  snapshot_url: null,
  collapse_at: "2026-11-14T20:00:00.000Z",
  first_instruction_at: "2026-11-14T20:00:05.500Z",
  confirmed_at: null,
  ems_notified_at: null,
  first_accept_at: null,
  responder_arrived_at: null,
  cpr_started_at: null,
  aed_arrived_at: null,
  resolved_at: null,
  created_at: "2026-11-14T20:00:05.000Z",
};

let n = 0;
const ev = (kind: string, payload: Record<string, unknown> = {}, actor = "system"): IncidentEvent => ({
  id: ++n,
  incident_id: "i1",
  ts: "2026-11-14T20:00:06.000Z",
  actor,
  kind,
  payload: payload as IncidentEvent["payload"],
});

describe("latencies", () => {
  it("measures from collapse when known", () => {
    expect(latencies(base)[0]).toMatchObject({ label: "First instruction", seconds: 5.5 });
    expect(latencies(base)[1].seconds).toBeNull();
  });
  it("falls back to detection for found-down incidents", () => {
    const i = { ...base, collapse_at: null };
    expect(originOf(i).label).toBe("after detection");
    expect(latencies(i)[0].seconds).toBe(0.5);
  });
});

describe("confirmState", () => {
  it("counts down to auto-proceed for a witnessed collapse", () => {
    const s = confirmState(base, [ev("confirm_requested", { auto_proceed_at: "2026-11-14T20:00:16Z" })]);
    expect(s).toEqual({ pending: true, deadline: "2026-11-14T20:00:16Z", mode: "auto" });
  });
  it("uses the escalation time for found down", () => {
    const s = confirmState(base, [ev("confirm_requested", { escalate_at: "2026-11-14T20:01:05Z" })]);
    expect(s.mode).toBe("escalate");
  });
  it("stops after a confirm, a false alarm or the gate opening", () => {
    for (const k of ["confirmed", "false_alarm", "gate_opened"]) {
      expect(confirmState(base, [ev("confirm_requested", {}), ev(k)]).pending).toBe(false);
    }
    expect(confirmState({ ...base, confirmed_at: base.created_at }, [ev("confirm_requested")]).pending).toBe(false);
  });
});

describe("fall911Timer", () => {
  const fall = { ...base, type: "fall" as const };
  it("shows the cancellable 911 timer", () => {
    expect(fall911Timer(fall, [ev("timer_started", { timer: "fall_911", fires_at: "2026-11-14T20:01:00Z" })])).toEqual({
      firesAt: "2026-11-14T20:01:00Z",
    });
  });
  it("hides it once cancelled, fired or briefed", () => {
    const t = ev("timer_started", { timer: "fall_911", fires_at: "x" });
    expect(fall911Timer(fall, [t, ev("fall_911_cancelled")])).toBeNull();
    expect(fall911Timer(fall, [t, ev("timer_fired", { timer: "fall_911" })])).toBeNull();
    expect(fall911Timer({ ...fall, ems_notified_at: base.created_at }, [t])).toBeNull();
    expect(fall911Timer(base, [t])).toBeNull();
  });
});

describe("timeline wording", () => {
  it("describes known kinds and falls back for unknown ones", () => {
    const who = (a: string | null) => (a === "responder:r1" ? "Sam" : (a ?? "--"));
    expect(describeEvent(ev("classified", { type: "cardiac", modifiers: ["seizure"], scene_safe: true }), who)).toBe(
      "Classified cardiac + seizure",
    );
    expect(describeEvent(ev("dispatch_accepted", { responder_id: "r1", role: "aed_runner" }), who)).toBe(
      "alert accepted: Sam as aed runner",
    );
    expect(describeEvent(ev("voice_check_result", { responsive: false }), who)).toBe(
      "voice check result (responsive: false)",
    );
  });
  it("finds the latest speak event with a route target", () => {
    const evs = [ev("speak", { script_id: "voice_check" }), ev("speak", { script_id: "cardiac_main", target: "aed" })];
    expect(latestRouteSpeak(evs)?.target).toBe("aed");
  });
});
