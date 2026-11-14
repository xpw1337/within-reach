"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { FloorHeatmap } from "@/components/building/FloorHeatmap";
import { matterportAvailable } from "@/components/building/MatterportTwin";
import { EmptyState, Panel, Segmented } from "@/components/ui";
import { assetName } from "@/lib/copy";
import { boundsOf, floorOf, indexCoverage } from "@/lib/heatmap";
import { useBuilding } from "@/lib/hooks/useBuilding";
import { useThresholds } from "@/lib/hooks/useThresholds";
import type { Camera, CameraRoute } from "@/lib/rows";

const STEP_MS = 450;

const MatterportTwin = dynamic(
  () => import("@/components/building/MatterportTwin").then((m) => m.MatterportTwin),
  { ssr: false },
);

/** Advances along the path once per STEP_MS; restarts when `runKey` changes (a new speak event). */
function useStep(length: number, runKey: number | null): number {
  const [state, setState] = useState<{ key: number | null; step: number }>({ key: null, step: 0 });
  useEffect(() => {
    if (runKey === null || length < 2) return;
    let step = 0;
    const id = window.setInterval(() => {
      step += 1;
      setState({ key: runKey, step });
      if (step >= length - 1) window.clearInterval(id);
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [runKey, length]);
  if (runKey === null) return length - 1;
  return state.key === runKey ? state.step : 0;
}

/**
 * On a speak event with a target, walk the census route from the camera's
 * sweep along camera_routes.path on the SVG plan (spec section 9.12).
 */
export function RouteFlythrough({
  camera,
  routes,
  speak,
  buildingId,
}: {
  camera: Camera | null;
  routes: CameraRoute[];
  speak: { id: number; target: string } | null;
  buildingId: string | null;
}) {
  const data = useBuilding(buildingId ?? "");
  const [view, setView] = useState<"2d" | "3d">("2d");
  const has3d = matterportAvailable(data.building?.matterport_model_id);
  const th = useThresholds();
  const target = speak?.target ?? "aed";
  const route = routes.find((r) => r.camera_id === camera?.id && r.target === target) ?? null;
  const path = useMemo(() => route?.path ?? [], [route]);
  const step = useStep(path.length, speak?.id ?? null);

  const bounds = useMemo(() => boundsOf(data.nodes), [data.nodes]);
  const index = useMemo(() => indexCoverage(data.coverage), [data.coverage]);
  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.sweep_id, n])), [data.nodes]);
  const head = path.length ? byId.get(path[Math.min(step, path.length - 1)]) : undefined;
  const camNode = camera?.sweep_id ? byId.get(camera.sweep_id) : undefined;
  const floor = head ? floorOf(head) : camNode ? floorOf(camNode) : (camera?.floor ?? 0);
  const gap = target === "extinguisher" ? "extinguisher" : target === "exit" ? "exit" : "aed";

  return (
    <Panel
      title={`Route to the ${assetName(target)}${speak ? ", synced to the speaker" : ""}`}
      right={
        <div className="flex items-center gap-3">
          {has3d && (
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: "2d", label: "Plan" },
                { value: "3d", label: "3D twin" },
              ]}
            />
          )}
          <span className="text-xs text-muted">Floor {floor}</span>
        </div>
      }
      bodyClassName="p-3"
    >
      {!buildingId ? (
        <EmptyState title="--">No building for this camera.</EmptyState>
      ) : !bounds ? (
        <EmptyState title="--">{data.nodesLoaded ? "No scan graph for this building." : "Loading the plan"}</EmptyState>
      ) : (
        <>
          {has3d && view === "3d" ? (
            <MatterportTwin
              modelId={data.building?.matterport_model_id ?? null}
              assets={data.assets}
              nodes={data.nodes}
              flyPath={path}
              flyKey={speak?.id ?? null}
              height={520}
            />
          ) : (
          <FloorHeatmap
            nodes={data.nodes}
            assets={data.assets}
            index={index}
            thresholds={th.thresholds}
            bounds={bounds}
            floor={floor}
            type={gap}
            scenario="current"
            markSweep={camera?.sweep_id ?? null}
            route={path.length ? path : null}
            routeStep={step}
            maxHeight={520}
          />
          )}
          <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 px-1 text-sm">
            {route ? (
              <>
                <span className="num text-lg font-bold text-accent">
                  {route.distance_m !== null ? `${Math.round(route.distance_m)} m` : "--"}
                </span>
                <span className="text-text">{route.directions ?? "--"}</span>
              </>
            ) : (
              <span className="text-muted">No precomputed route to the {assetName(target)} for this camera.</span>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
