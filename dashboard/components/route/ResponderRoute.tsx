"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { FloorHeatmap } from "@/components/building/FloorHeatmap";
import { matterportAvailable } from "@/components/building/MatterportTwin";
import { Button, EmptyState, Segmented } from "@/components/ui";
import { assetDisplayLabel, copy } from "@/lib/copy";
import { distanceToPathPoint, latLngToPlan, nearestPathIndex, type GeorefTransform } from "@/lib/georef";
import { boundsOf, floorOf, indexCoverage } from "@/lib/heatmap";
import { UUID_RE, useBuilding } from "@/lib/hooks/useBuilding";
import { useRealtimeTable } from "@/lib/hooks/useRealtimeTable";
import { useThresholds } from "@/lib/hooks/useThresholds";
import { routeEndsAtSimulated } from "@/lib/incident";
import { planLeg, spokenMeters, type Leg } from "@/lib/routePlan";
import { isSimulated, type CameraRoute } from "@/lib/rows";
import { getSupabase } from "@/lib/supabase";

const MatterportTwin = dynamic(
  () => import("@/components/building/MatterportTwin").then((m) => m.MatterportTwin),
  { ssr: false },
);

const PERSON_TAG = { r: 0.94, g: 0.27, b: 0.27 };
const START_TAG = { r: 0.36, g: 0.78, b: 1 };

/** A stable small number for a path, so the first fly to a new leg has its own key. */
function hashKey(text: string): number {
  let h = 7;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(h) + 1;
}

/**
 * The responder's route in the 3D twin, opened from "View route in 3D" in the app
 * (mobile/app/alert/[dispatchId].tsx). One leg at a time: to the AED, then to the person.
 * The view moves one scan point at a time with Back / Next, or walks the whole leg. It follows the
 * helper as they walk: with `follow` (the dispatch id) the app sends its floor-plan dot over a Realtime
 * broadcast channel (step tracking), and the view moves to the route's scan point nearest the dot,
 * switching legs with the app. Until a dot arrives, and with the building's calibration in the link
 * (`geo`), the phone's GPS drives it instead (team lead, 2026-11-15: treat GPS as accurate).
 */
export function ResponderRoute({
  buildingId,
  cameraId,
  leg: legParam,
  from,
  role,
  geo,
  followId,
}: {
  buildingId: string;
  cameraId: string | null;
  leg: Leg | null;
  from: string | null;
  role: string | null;
  geo: GeorefTransform | null;
  followId: string | null;
}) {
  const valid = UUID_RE.test(buildingId);
  const data = useBuilding(valid ? buildingId : "");
  const th = useThresholds();
  const routes = useRealtimeTable<CameraRoute>({
    key: `responder-routes:${buildingId}`,
    table: "camera_routes",
    realtime: false,
    enabled: valid,
    load: async (db) => {
      const { data: rows, error } = await db.from("camera_routes").select("*").eq("target", "aed");
      if (error) throw new Error(error.message);
      return rows ?? [];
    },
    rowKey: (r) => `${r.camera_id}|${r.target}`,
  });

  const camera = data.cameras.find((c) => c.id === cameraId) ?? data.cameras[0] ?? null;
  const aedRoute = routes.rows.find((r) => r.camera_id === camera?.id && r.target === "aed") ?? null;
  const ownAeds = data.assets.filter((a) => a.type === "aed" && a.source !== "proposed" && a.sweep_id);
  const aedSweep = aedRoute?.path?.length ? aedRoute.path[aedRoute.path.length - 1] : (ownAeds[0]?.sweep_id ?? null);
  const aedAsset = ownAeds.find((a) => a.sweep_id === aedSweep) ?? ownAeds[0] ?? null;
  const personSweep = camera?.sweep_id ?? null;
  const runner = role !== "patient";

  // The leg from the link; with none, the AED first for a runner when an AED is mapped.
  const [legOverride, setLegOverride] = useState<Leg | null>(null);
  const leg: Leg = legOverride ?? legParam ?? (runner && aedSweep ? "to_aed" : "to_person");
  // The start from the app applies to the first leg only; the second leg starts at the AED.
  const start = legOverride ? null : from;

  // Small graphs (tens to a few thousand sweeps); the React Compiler memoizes this render.
  const plan = planLeg({
    nodes: data.nodes,
    leg,
    personSweep,
    aedSweep,
    aedPath: aedRoute?.path ?? null,
    from: start,
  });

  // Position on the leg. A new leg (another path) starts again at its first scan point.
  const planKey = plan.path.join(">");
  type Nav = { plan: string; step: number; fly: { path: string[]; key: number } | null; seq: number };
  const [nav, setNav] = useState<Nav>({ plan: "", step: 0, fly: null, seq: 0 });
  const current =
    nav.plan === planKey
      ? nav
      : { plan: planKey, step: 0, fly: plan.path.length ? { path: [plan.path[0]], key: hashKey(planKey) } : null, seq: nav.seq };
  const step = current.step;
  const fly = current.fly;

  // Follow the phone: on by default when the link carries the calibration; Back / Next pause it.
  const [following, setFollowing] = useState(true);
  const [gps, setGps] = useState<"on" | "denied" | "error" | null>(null);
  // True once the app's dot arrives; then it drives the view and GPS is not used.
  const [streaming, setStreaming] = useState(false);
  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.sweep_id, n])), [data.nodes]);
  const geoKey = geo ? `${geo.originLat},${geo.originLng},${geo.rotationDeg},${geo.tx},${geo.tz}` : "";
  useEffect(() => {
    if (!geo || !following || streaming || !planKey || typeof navigator === "undefined" || !navigator.geolocation) return;
    const path = planKey.split(">");
    const watch = navigator.geolocation.watchPosition(
      (pos) => {
        setGps("on");
        const p = latLngToPlan(geo, { lat: pos.coords.latitude, lng: pos.coords.longitude });
        setNav((n) => {
          const cur = n.plan === planKey ? n.step : 0;
          const i = nearestPathIndex(path, byId, p);
          // Move only to a point at least 1 m closer than the current one, so jitter does not flip the view.
          if (i < 0 || i === cur || distanceToPathPoint(path, byId, i, p) + 1 > distanceToPathPoint(path, byId, cur, p)) return n;
          return { plan: planKey, step: i, fly: { path: [path[i]], key: -(n.seq + 1) }, seq: n.seq + 1 };
        });
      },
      (err) => setGps(err.code === err.PERMISSION_DENIED ? "denied" : "error"),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(watch);
    // geoKey stands for geo; planKey for the path.
  }, [geoKey, following, streaming, planKey, byId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The app's dot. The channel stays open for the whole page; the handler reads the current leg and
  // path from refs so a leg change does not resubscribe.
  const live = useRef({ planKey, leg, following });
  useEffect(() => {
    live.current = { planKey, leg, following };
  }, [planKey, leg, following]);
  useEffect(() => {
    const db = getSupabase();
    if (!db || !followId) return;
    const channel = db
      .channel(`follow:${followId}`)
      .on("broadcast", { event: "pos" }, ({ payload }) => {
        const msg = payload as { x?: unknown; z?: unknown; leg?: unknown };
        if (typeof msg.x !== "number" || typeof msg.z !== "number") return;
        setStreaming(true);
        const cur = live.current;
        if ((msg.leg === "to_aed" || msg.leg === "to_person") && msg.leg !== cur.leg) {
          setLegOverride(msg.leg); // the app moved on (for example "I have the AED"); the next dot moves the view
          return;
        }
        if (!cur.following || !cur.planKey) return;
        const path = cur.planKey.split(">");
        const p = { x: msg.x, z: msg.z };
        const key = cur.planKey;
        setNav((n) => {
          const at = n.plan === key ? n.step : 0;
          const i = nearestPathIndex(path, byId, p);
          if (i < 0 || i === at || distanceToPathPoint(path, byId, i, p) + 1 > distanceToPathPoint(path, byId, at, p)) return n;
          return { plan: key, step: i, fly: { path: [path[i]], key: -(n.seq + 1) }, seq: n.seq + 1 };
        });
      })
      .subscribe();
    return () => {
      void db.removeChannel(channel);
    };
  }, [followId, byId]);

  const goTo = (i: number) => {
    setFollowing(false);
    const j = Math.max(0, Math.min(plan.path.length - 1, i));
    setNav((n) => ({ plan: planKey, step: j, fly: { path: [plan.path[j]], key: -(n.seq + 1) }, seq: n.seq + 1 }));
  };
  const walkAll = () => {
    if (plan.path.length < 2) return;
    setFollowing(false);
    const from0 = step >= plan.path.length - 1 ? 0 : step;
    const last = plan.path.length - 1;
    setNav((n) => ({ plan: planKey, step: last, fly: { path: plan.path.slice(from0), key: -(n.seq + 1) }, seq: n.seq + 1 }));
  };

  const has3d = matterportAvailable(data.building?.matterport_model_id);
  const [view, setView] = useState<"3d" | "2d">("3d");
  const show3d = has3d && view === "3d";

  const bounds = useMemo(() => boundsOf(data.nodes), [data.nodes]);
  const index = useMemo(() => indexCoverage(data.coverage), [data.coverage]);
  const here = plan.path.length ? byId.get(plan.path[Math.min(step, plan.path.length - 1)]) : undefined;
  const floor = here ? floorOf(here) : (camera?.floor ?? 0);

  const simulated = aedAsset ? isSimulated(aedAsset) : routeEndsAtSimulated(aedRoute?.path ?? [], "aed", data.assets);
  const aedName = aedAsset ? assetDisplayLabel(aedAsset) : "AED";
  const landmark = camera?.landmark ?? "the person";
  const title =
    leg === "to_aed" ? "Get the AED" : runner && aedSweep ? "Bring the AED to the person" : "Go to the person";
  const where =
    leg === "to_aed"
      ? plan.censusRoute && aedRoute?.directions
        ? aedRoute.directions
        : aedName
      : `by ${landmark}${camera?.floor != null ? `, floor ${camera.floor}` : ""}`;
  // The census route has the distance the speaker reads out; use it so both say the same number.
  const meters = plan.censusRoute && aedRoute?.distance_m != null ? aedRoute.distance_m : plan.meters;
  const atEnd = plan.path.length > 0 && step >= plan.path.length - 1;

  const extraTags: { key: string; label: string; sweep_id: string; color: { r: number; g: number; b: number } }[] = [];
  if (personSweep) extraTags.push({ key: `person:${personSweep}`, label: `Person down: ${landmark}`, sweep_id: personSweep, color: PERSON_TAG });
  if (start && start !== personSweep && start !== aedSweep)
    extraTags.push({ key: `start:${start}`, label: "Your start", sweep_id: start, color: START_TAG });

  if (!valid) {
    return (
      <div className="p-4">
        <EmptyState title="No such building">This link does not name a building.</EmptyState>
      </div>
    );
  }
  if (!data.nodesLoaded || !routes.loaded) {
    return (
      <div className="p-4">
        <EmptyState title="Loading the route" />
      </div>
    );
  }

  return (
    <div data-responder-page className="mx-auto flex w-full max-w-3xl flex-col gap-3 p-3 sm:p-4">
      <header className="flex flex-col gap-1">
        <div className="label">{data.building?.name ?? "Building"}</div>
        <h1 className="text-xl font-bold text-text">{title}</h1>
        <div className="flex flex-wrap items-baseline gap-x-3 text-sm">
          {meters !== null && <span className="num text-lg font-bold text-accent">{spokenMeters(meters)} m</span>}
          <span className="text-text">{where}</span>
        </div>
      </header>

      {plan.path.length === 0 ? (
        <EmptyState title="No route">
          {leg === "to_aed" ? "No AED is mapped for this camera." : "The person's spot is not on the scan."} Follow the
          directions in the app.
        </EmptyState>
      ) : (
        <>
          {has3d && (
            <div className="flex items-center justify-between gap-2">
              <Segmented
                size="sm"
                value={view}
                onChange={setView}
                options={[
                  { value: "3d", label: "3D" },
                  { value: "2d", label: "Plan" },
                ]}
              />
              <span className="text-xs text-muted">Floor {floor}</span>
            </div>
          )}
          {show3d ? (
            <MatterportTwin
              modelId={data.building?.matterport_model_id ?? null}
              assets={data.assets}
              nodes={data.nodes}
              flyPath={fly?.path ?? null}
              flyKey={fly?.key ?? null}
              extraTags={extraTags}
              height="min(55dvh, 640px)"
            />
          ) : bounds ? (
            <FloorHeatmap
              nodes={data.nodes}
              assets={data.assets}
              index={index}
              thresholds={th.thresholds}
              bounds={bounds}
              floor={floor}
              type="aed"
              scenario="current"
              markSweep={personSweep}
              route={plan.path}
              routeStep={step}
              maxHeight={520}
            />
          ) : (
            <EmptyState title="--">No scan graph for this building.</EmptyState>
          )}

          {(geo || followId) && (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className={gps === "denied" || gps === "error" ? "text-warn" : "text-muted"}>
                {!following
                  ? "Not following your location."
                  : streaming
                    ? "Following your walk in the app: the view moves as you walk."
                    : !geo
                      ? "Waiting for your walk in the app."
                      : gps === "on"
                    ? "Following your location: the view moves as you walk."
                    : gps === "denied"
                      ? "Location is off for this page. Allow it to follow you, or use Back and Next."
                      : gps === "error"
                        ? "No location yet. Use Back and Next, or wait for GPS."
                        : "Waiting for your location."}
              </span>
              {!following && (
                <Button size="sm" onClick={() => setFollowing(true)}>
                  Follow me
                </Button>
              )}
            </div>
          )}
          <div className="flex items-center justify-between text-sm text-muted">
            <span>
              Point {Math.min(step + 1, plan.path.length)} of {plan.path.length}
            </span>
            {atEnd && <span className="font-semibold text-ok">{leg === "to_aed" ? "The AED is here" : "The person is here"}</span>}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Button size="lg" onClick={() => goTo(step - 1)} disabled={step === 0}>
              Back
            </Button>
            <Button size="lg" tone="primary" onClick={() => goTo(step + 1)} disabled={atEnd}>
              Next
            </Button>
            <Button size="lg" onClick={walkAll} disabled={plan.path.length < 2}>
              {atEnd ? "Replay" : "Walk it"}
            </Button>
          </div>
          {leg === "to_aed" && runner && personSweep && (
            <Button size="lg" tone="ok" onClick={() => setLegOverride("to_person")}>
              I have the AED: show the way to the person
            </Button>
          )}
          {leg === "to_person" && legOverride && (
            <Button size="md" tone="ghost" onClick={() => setLegOverride("to_aed")}>
              Back to the way to the AED
            </Button>
          )}
          {simulated && (leg === "to_aed" || runner) && (
            <div className="flex items-start gap-2 text-xs text-warn">
              <span className="mt-0.5 inline-block h-3 w-4 shrink-0 rounded-sm border-2 border-dashed border-warn" aria-hidden />
              {copy.simulatedRoute}
            </div>
          )}
          {!has3d && (
            <p className="text-xs text-muted">
              The 3D view needs the Matterport key and a model for this building; the plan shows the same route.
            </p>
          )}
        </>
      )}
    </div>
  );
}
