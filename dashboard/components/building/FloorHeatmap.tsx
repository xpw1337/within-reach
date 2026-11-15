"use client";

import { useMemo } from "react";
import {
  edgesOf,
  floorOf,
  project,
  sweepZone,
  typicalSpacing,
  ZONE_COLORS,
  type Bounds,
  type SweepZone,
} from "@/lib/heatmap";
import { assetDisplayLabel, simulatedMarker } from "@/lib/copy";
import { isSimulated, type Asset, type GapType, type TwinNode } from "@/lib/rows";
import { formatMeasure, type Thresholds } from "@/lib/thresholds";

const W = 1000;
const PAD = 48;

export type PlanAsset = Pick<Asset, "id" | "type" | "sweep_id" | "floor" | "x" | "z" | "source" | "flags" | "label">;

const ASSET_LABEL: Record<string, string> = {
  aed: "AED",
  extinguisher: "EXT",
  exit: "EXIT",
  exit_sign: "EXIT",
  naloxone: "NLX",
  first_aid: "AID",
};

function assetGap(type: string): GapType | null {
  if (type === "aed") return "aed";
  if (type === "extinguisher") return "extinguisher";
  if (type === "exit" || type === "exit_sign") return "exit";
  return null;
}

export type HeatmapProps = {
  nodes: TwinNode[];
  assets: PlanAsset[];
  index: Map<string, number | null>;
  thresholds: Thresholds | null;
  bounds: Bounds;
  floor: number;
  type: GapType;
  scenario: "current" | "proposed";
  /** Where the proposed asset lands; zones recolor outward from here. */
  rippleFrom?: { x: number; z: number } | null;
  hovered?: string | null;
  onHover?: (sweepId: string | null) => void;
  /** Live page: the camera sweep (victim location) and a route along sweep ids. */
  markSweep?: string | null;
  route?: string[] | null;
  routeStep?: number;
  maxHeight?: number;
};

export function FloorHeatmap(props: HeatmapProps) {
  const { nodes, assets, index, thresholds, bounds, floor, type, scenario, hovered, onHover } = props;
  const maxHeight = props.maxHeight ?? 640;

  const proj = useMemo(() => project(bounds, W, PAD, maxHeight), [bounds, maxHeight]);
  const byId = useMemo(() => {
    const m = new Map<string, TwinNode>();
    for (const n of nodes) if (n.sweep_id) m.set(n.sweep_id, n);
    return m;
  }, [nodes]);
  const floorNodes = useMemo(
    () => nodes.filter((n) => floorOf(n) === floor && typeof n.x === "number" && typeof n.z === "number" && n.sweep_id),
    [nodes, floor],
  );
  const edges = useMemo(() => edgesOf(nodes, floor), [nodes, floor]);
  const r = useMemo(() => {
    const s = typicalSpacing(nodes);
    const px = s ? s * proj.scale * 0.42 : 9;
    return Math.max(4, Math.min(15, px));
  }, [nodes, proj.scale]);

  const ripple = props.rippleFrom ?? null;
  const maxRippleDist = useMemo(() => {
    if (!ripple) return 1;
    let m = 1;
    for (const n of floorNodes) m = Math.max(m, Math.hypot((n.x as number) - ripple.x, (n.z as number) - ripple.z));
    return m;
  }, [floorNodes, ripple]);

  const px = (x: number, z: number) => proj.toPx(x, z);

  const assetPos = (a: PlanAsset): [number, number] | null => {
    if (typeof a.x === "number" && typeof a.z === "number") return px(a.x, a.z);
    const n = a.sweep_id ? byId.get(a.sweep_id) : undefined;
    if (n && typeof n.x === "number" && typeof n.z === "number") return px(n.x, n.z);
    return null;
  };
  const assetFloor = (a: PlanAsset) => {
    if (typeof a.floor === "number") return a.floor;
    const n = a.sweep_id ? byId.get(a.sweep_id) : undefined;
    return n ? floorOf(n) : null;
  };

  const visibleAssets = assets.filter((a) => {
    if (assetFloor(a) !== floor) return false;
    if (a.source === "proposed") return scenario === "proposed";
    return true;
  });

  const routePts = useMemo(() => {
    if (!props.route) return [];
    return props.route
      .map((id) => byId.get(id))
      .filter((n): n is TwinNode => Boolean(n && typeof n.x === "number" && typeof n.z === "number"));
  }, [props.route, byId]);
  const routeOnFloor = routePts.filter((n) => floorOf(n) === floor);
  const step = props.routeStep ?? routePts.length;
  const walked = routePts.slice(0, Math.max(1, step + 1)).filter((n) => floorOf(n) === floor);
  const head = routePts[Math.min(step, routePts.length - 1)];
  const mark = props.markSweep ? byId.get(props.markSweep) : undefined;

  return (
    <svg
      viewBox={`0 0 ${W} ${proj.height}`}
      className="block h-auto w-full select-none"
      role="img"
      aria-label={`Floor ${floor} plan`}
      onMouseLeave={() => onHover?.(null)}
    >
      <g stroke="var(--line-strong)" strokeWidth={1.5} opacity={0.55}>
        {edges.map(([a, b]) => {
          const na = byId.get(a);
          const nb = byId.get(b);
          if (!na || !nb) return null;
          const [x1, y1] = px(na.x as number, na.z as number);
          const [x2, y2] = px(nb.x as number, nb.z as number);
          return <line key={`${a}|${b}`} x1={x1} y1={y1} x2={x2} y2={y2} />;
        })}
      </g>

      {routeOnFloor.length > 1 && (
        <polyline
          points={routeOnFloor.map((n) => px(n.x as number, n.z as number).join(",")).join(" ")}
          fill="none"
          stroke="var(--accent)"
          strokeOpacity={0.25}
          strokeWidth={r * 1.1}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}

      <g>
        {floorNodes.map((n) => {
          const id = n.sweep_id as string;
          const [cx, cy] = px(n.x as number, n.z as number);
          const z: SweepZone = sweepZone(index, thresholds, scenario, type, id);
          const delay =
            ripple && scenario === "proposed"
              ? Math.round((Math.hypot((n.x as number) - ripple.x, (n.z as number) - ripple.z) / maxRippleDist) * 1100)
              : 0;
          const style = {
            fill: ZONE_COLORS[z],
            transitionDelay: `${delay}ms`,
            stroke: z === "unmapped" ? "var(--faint)" : hovered === id ? "#fff" : "rgba(9,12,17,0.85)",
            strokeDasharray: z === "unmapped" ? "2 2" : undefined,
          };
          const t = index.get(`${scenario}|${type}|${id}`);
          const title = `${n.label || n.room_type || id}: ${z === "unmapped" ? "not mapped" : formatMeasure(type, t ?? null, thresholds)}`;
          const common = {
            className: "sweep",
            style,
            strokeWidth: hovered === id ? 2.5 : 1.5,
            onMouseEnter: () => onHover?.(id),
          };
          return n.is_stairs || n.is_elevator ? (
            <rect key={id} x={cx - r} y={cy - r} width={2 * r} height={2 * r} rx={2} {...common}>
              <title>{`${title} (${n.is_stairs ? "stairs" : "elevator"})`}</title>
            </rect>
          ) : (
            <circle key={id} cx={cx} cy={cy} r={r} {...common}>
              <title>{title}</title>
            </circle>
          );
        })}
      </g>

      {walked.length > 1 && (
        <polyline
          key={`walk-${step}`}
          points={walked.map((n) => px(n.x as number, n.z as number).join(",")).join(" ")}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={4}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      {head && floorOf(head) === floor && (
        <circle
          cx={px(head.x as number, head.z as number)[0]}
          cy={px(head.x as number, head.z as number)[1]}
          r={r * 0.8}
          fill="var(--accent)"
          stroke="#fff"
          strokeWidth={2}
          style={{ transition: "cx 450ms linear, cy 450ms linear" }}
        />
      )}

      {mark && floorOf(mark) === floor && typeof mark.x === "number" && typeof mark.z === "number" && (
        <g transform={`translate(${px(mark.x, mark.z).join(",")})`}>
          <circle r={r * 2} fill="none" stroke="var(--danger)" strokeWidth={3} className="pulse-ring" />
          <circle r={r * 0.9} fill="var(--danger)" stroke="#fff" strokeWidth={2} />
        </g>
      )}

      <g>
        {visibleAssets.map((a) => {
          const pos = assetPos(a);
          if (!pos) return null;
          const gap = assetGap(a.type);
          const emphasized = gap === type;
          const proposed = a.source === "proposed";
          const blocked = (a.flags ?? []).includes("blocked_exit");
          // A demo prop placed by the team: dashed outline and its own label, never shown as a scan finding.
          const simulated = !proposed && isSimulated(a);
          const short = ASSET_LABEL[a.type] ?? a.type.slice(0, 4).toUpperCase();
          const text = proposed
            ? `NEW ${ASSET_LABEL[a.type] ?? a.type.toUpperCase()}`
            : simulated
              ? simulatedMarker(short)
              : short;
          const w = Math.max(34, text.length * 9 + 12);
          const h = 22;
          const stroke = blocked ? "var(--danger)" : proposed ? "var(--accent)" : simulated ? "var(--warn)" : "#ffffff";
          return (
            <g
              key={a.id}
              transform={`translate(${pos[0]},${pos[1] - r - h / 2 - 4})`}
              opacity={emphasized || proposed ? 1 : 0.5}
            >
              {proposed && <circle r={Math.max(60, r * 8)} fill="var(--accent)" fillOpacity={0.35} className="ripple" />}
              <g className={proposed ? "drop-in" : undefined}>
                <rect
                  x={-w / 2}
                  y={-h / 2}
                  width={w}
                  height={h}
                  rx={5}
                  fill={proposed ? "var(--accent)" : "#0b0f14"}
                  stroke={stroke}
                  strokeWidth={blocked || simulated ? 2.5 : 1.5}
                  strokeDasharray={simulated ? "5 3" : undefined}
                  data-simulated={simulated ? "true" : undefined}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={12}
                  fontWeight={800}
                  letterSpacing={0.5}
                  fill={proposed ? "#06121b" : blocked ? "var(--danger)" : simulated ? "var(--warn)" : "#fff"}
                  style={{ fontFamily: "var(--font-sans)" }}
                >
                  {text}
                </text>
                <path d={`M -5 ${h / 2} L 0 ${h / 2 + 6} L 5 ${h / 2}`} fill={proposed ? "var(--accent)" : stroke} />
              </g>
              <title>
                {`${simulated ? assetDisplayLabel(a) : (a.label ?? a.type)}${proposed ? " (proposed by the Fixer)" : ""}${blocked ? " (looks blocked)" : ""}`}
              </title>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
