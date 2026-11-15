"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { env } from "@/lib/env";
import { assetDisplayLabel } from "@/lib/copy";
import { isSimulated, type Asset, type TwinNode } from "@/lib/rows";

// The subset of the Showcase SDK used here (types from api.matterport.com/sdk/types/sdk.d.ts).
// Kept local so the build never depends on the package's downloaded type file.
type Vec3 = { x: number; y: number; z: number };
type MpSdkLite = {
  Tag: {
    add(...tags: { label?: string; anchorPosition: Vec3; stemVector: Vec3; color?: { r: number; g: number; b: number } }[]): Promise<string[]>;
  };
  Sweep: {
    moveTo(sweep: string, options: { transition?: string; transitionTime?: number }): Promise<string>;
  };
  Camera?: { TransitionType?: { FLY?: string } };
  disconnect?: () => void;
};
type SetupSdk = (key: string, options: Record<string, unknown>) => Promise<MpSdkLite>;

const CONNECT_TIMEOUT_MS = 20000;

const TAG_COLOR: Record<string, { r: number; g: number; b: number }> = {
  aed: { r: 0.18, g: 0.76, b: 0.49 },
  extinguisher: { r: 1, g: 0.3, b: 0.31 },
  exit: { r: 0.96, g: 0.77, b: 0.26 },
  exit_sign: { r: 0.96, g: 0.77, b: 0.26 },
  proposed: { r: 0.36, g: 0.78, b: 1 },
  // Demo props placed by the team: the --warn orange, never the color of an AED from the scan.
  simulated: { r: 1, g: 0.54, b: 0.24 },
};
const TAG_LABEL: Record<string, string> = { aed: "AED", extinguisher: "Extinguisher", exit: "Exit", exit_sign: "Exit sign" };

/** Shown only when both the SDK key and the building's Matterport model id exist. */
export function matterportAvailable(modelId: string | null | undefined): boolean {
  return Boolean(env.matterportSdkKey && modelId);
}

/**
 * Matterport Showcase SDK embed with asset tags and a camera fly-through.
 * Loaded lazily; any failure (SDK blocked, bad key, offline) leaves a short
 * note and the rest of the page keeps working on the SVG plan (decision D11).
 */
export function MatterportTwin({
  modelId,
  assets,
  nodes,
  showProposed = false,
  flyPath,
  flyKey,
  extraTags = [],
  height = 560,
}: {
  modelId: string | null;
  assets: Pick<Asset, "id" | "type" | "sweep_id" | "x" | "y" | "z" | "source" | "label" | "flags">[];
  nodes: Pick<TwinNode, "sweep_id" | "x" | "y" | "z">[];
  showProposed?: boolean;
  /** Sweep ids to fly along; a new flyKey restarts the flight. */
  flyPath?: string[] | null;
  flyKey?: number | null;
  /** Tags that are not assets (for example the person on a responder route), at a sweep's position. */
  extraTags?: { key: string; label: string; sweep_id: string; color: { r: number; g: number; b: number } }[];
  /** CSS height: pixels, or any CSS length such as "60dvh". */
  height?: number | string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const sdkRef = useRef<MpSdkLite | null>(null);
  const [status, setStatus] = useState<"connecting" | "ready" | "failed">("connecting");
  const [error, setError] = useState<string | null>(null);
  const [tagsFor, setTagsFor] = useState<string>("");

  const tagDescriptors = useEffectEvent(() => {
    const pos = new Map(nodes.map((n) => [n.sweep_id, n]));
    const extra = extraTags
      .map((t) => {
        const n = pos.get(t.sweep_id);
        if (!n || typeof n.x !== "number" || typeof n.y !== "number" || typeof n.z !== "number") return null;
        return { label: t.label, anchorPosition: { x: n.x, y: n.y, z: n.z }, stemVector: { x: 0, y: 0.3, z: 0 }, color: t.color };
      })
      .filter((t): t is NonNullable<typeof t> => t !== null);
    const assetTags = assets
      .filter((a) => (a.source === "proposed" ? showProposed : true) && TAG_COLOR[a.type])
      .map((a) => {
        const n = a.sweep_id ? pos.get(a.sweep_id) : undefined;
        const x = a.x ?? n?.x;
        const y = a.y ?? n?.y;
        const z = a.z ?? n?.z;
        if (typeof x !== "number" || typeof y !== "number" || typeof z !== "number") return null;
        const proposed = a.source === "proposed";
        const simulated = !proposed && isSimulated(a);
        return {
          label: proposed
            ? `Proposed ${TAG_LABEL[a.type] ?? a.type}`
            : simulated
              ? assetDisplayLabel(a)
              : `${TAG_LABEL[a.type] ?? a.type}${a.label ? `: ${a.label}` : ""}`,
          anchorPosition: { x, y, z },
          stemVector: { x: 0, y: 0.3, z: 0 },
          color: proposed ? TAG_COLOR.proposed : simulated ? TAG_COLOR.simulated : TAG_COLOR[a.type],
        };
      })
      .filter((t): t is NonNullable<typeof t> => t !== null);
    return [...assetTags, ...extra];
  });

  useEffect(() => {
    const node = el.current;
    if (!node || !modelId || !env.matterportSdkKey) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!sdkRef.current && !cancelled) {
        setStatus("failed");
        setError("The Matterport SDK did not connect in time.");
      }
    }, CONNECT_TIMEOUT_MS);
    void (async () => {
      try {
        const mod = (await import("@matterport/sdk")) as unknown as { setupSdk: SetupSdk };
        const sdk = await mod.setupSdk(env.matterportSdkKey, {
          space: modelId,
          container: node,
          iframeQueryParams: { qs: 1, help: 0, brand: 0 },
        });
        if (cancelled) {
          sdk.disconnect?.();
          return;
        }
        sdkRef.current = sdk;
        setStatus("ready");
      } catch (e) {
        if (cancelled) return;
        setStatus("failed");
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      sdkRef.current?.disconnect?.();
      sdkRef.current = null;
      node.replaceChildren();
    };
  }, [modelId]);

  // Tags, added once per connection and scenario.
  const tagKey = `${status}|${showProposed}|${assets.length}|${extraTags.map((t) => t.key).join(",")}`;
  useEffect(() => {
    const sdk = sdkRef.current;
    if (status !== "ready" || !sdk || tagsFor === tagKey) return;
    let cancelled = false;
    const tags = tagDescriptors();
    void sdk.Tag.add(...tags)
      .catch(() => undefined)
      .then(() => {
        if (!cancelled) setTagsFor(tagKey);
      });
    return () => {
      cancelled = true;
    };
  }, [status, tagKey, tagsFor]);

  // Fly along the route, one sweep at a time.
  const path = useEffectEvent(() => flyPath ?? []);
  useEffect(() => {
    const sdk = sdkRef.current;
    if (status !== "ready" || !sdk || flyKey === null || flyKey === undefined) return;
    let cancelled = false;
    void (async () => {
      const transition = sdk.Camera?.TransitionType?.FLY ?? "transition.fly";
      for (const sid of path()) {
        if (cancelled) return;
        try {
          await sdk.Sweep.moveTo(sid, { transition, transitionTime: 700 });
        } catch {
          // a sweep id the SDK does not know: skip it
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, flyKey]);

  if (!matterportAvailable(modelId)) return null;
  return (
    <div className="relative w-full overflow-hidden rounded-md border border-line bg-black" style={{ height }}>
      <div ref={el} className="absolute inset-0" />
      {status !== "ready" && (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-muted">
          {status === "connecting" ? "Loading the 3D twin" : `3D twin unavailable: ${error ?? "unknown error"}. The 2D plan still works.`}
        </div>
      )}
    </div>
  );
}
