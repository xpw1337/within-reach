"use client";

import dynamic from "next/dynamic";
import { Panel } from "@/components/ui";
import { readEmsDoor, readVexcel, type GeoPoint } from "@/lib/contracts";
import type { Building } from "@/lib/rows";
import type { MapPoint } from "@/components/map/MiniMap";

const MiniMap = dynamic(() => import("@/components/map/MiniMap").then((m) => m.MiniMap), { ssr: false });

const COLORS = { ems: "#5cc8ff", entrance: "#e9eef5", parking: "#b18cff", hydrant: "#ff4d4f" };

function toPoints(list: GeoPoint[], color: string, kind: string): MapPoint[] {
  return list
    .filter((p): p is GeoPoint & { lat: number; lng: number } => p.lat !== null && p.lng !== null)
    .map((p) => ({ lat: p.lat, lng: p.lng, color, label: p.desc ? `${kind}: ${p.desc}` : kind }));
}

function List({ title, items, color }: { title: string; items: GeoPoint[]; color: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className="size-2.5 rounded-full" style={{ background: color }} />
        <span className="label">{title}</span>
        <span className="num text-xs text-muted">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="text-sm text-faint">--</div>
      ) : (
        <ul className="space-y-0.5 text-sm text-muted">
          {items.slice(0, 6).map((p, i) => (
            <li key={i}>{p.desc ?? (p.lat !== null && p.lng !== null ? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}` : "--")}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Vexcel outside data and the EMS door chosen by the Outside subagent (spec section 9.7). */
export function OutsidePanel({ building }: { building: Building | null }) {
  const v = readVexcel(building?.vexcel ?? null);
  const door = readEmsDoor(building?.ems_door ?? null);
  const points: MapPoint[] = [
    ...toPoints(v.entrances, COLORS.entrance, "Entrance"),
    ...toPoints(v.ambulanceParking, COLORS.parking, "Ambulance parking"),
    ...toPoints(v.hydrants, COLORS.hydrant, "Hydrant"),
    ...(door ? toPoints([door], COLORS.ems, "EMS door").map((p) => ({ ...p, size: 20 })) : []),
  ];
  const hasAny = Boolean(building?.vexcel || door);

  return (
    <Panel title="Outside (Vexcel)">
      {!hasAny ? (
        <p className="text-sm text-muted">No Vexcel data or EMS door for this building yet.</p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-md border border-accent/40 bg-accent/[0.07] p-3">
            <div className="label text-accent">EMS door</div>
            <div className="mt-1 text-base font-semibold">{door?.desc ?? "--"}</div>
            {door?.reason && <div className="mt-1 text-sm text-muted">{door.reason}</div>}
            {(door?.staging || door?.hydrant) && (
              <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="label">Staging</span>
                  <div>{door?.staging ?? "--"}</div>
                </div>
                <div>
                  <span className="label">Nearest hydrant</span>
                  <div>{door?.hydrant ?? "--"}</div>
                </div>
              </div>
            )}
          </div>
          {v.imageUrl && (
            // Vexcel imagery, stored only if the license allows (CONTRACTS section 5).
            // eslint-disable-next-line @next/next/no-img-element
            <img src={v.imageUrl} alt="Vexcel aerial view of the building" className="w-full rounded-md border border-line" />
          )}
          <MiniMap points={points} />
          <div className="grid grid-cols-3 gap-3">
            <List title="Entrances" items={v.entrances} color={COLORS.entrance} />
            <List title="Ambulance parking" items={v.ambulanceParking} color={COLORS.parking} />
            <List title="Hydrants" items={v.hydrants} color={COLORS.hydrant} />
          </div>
        </div>
      )}
    </Panel>
  );
}
