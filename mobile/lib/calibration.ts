// Data for the hidden georeference calibration screen (app/calibrate.tsx): the building, its scan
// positions and the reference spots to stand on. Read only (anon select); nothing is written to the
// database.

import type { PlanPoint } from './floorPlan';
import { requireSupabase } from './supabase';
import type { BuildingRow, TwinNodeRow } from './types';

export type LabeledNode = TwinNodeRow & { label: string | null };

export type CalibrationData = {
  building: BuildingRow | null;
  nodes: LabeledNode[];
  cameras: { id: string; name: string | null; sweep_id: string | null; floor: number | null; landmark: string | null }[];
  aeds: { sweep_id: string | null; label: string | null; flags: string[] | null }[];
};

export type RefSpot = {
  /** The sweep to stand on. */
  id: string;
  kind: 'patient' | 'aed' | 'label';
  title: string;
  floor: number;
  plan: PlanPoint;
};

export async function loadCalibrationData(buildingId: string): Promise<CalibrationData> {
  const sb = requireSupabase();
  const [buildingRes, nodesRes, camerasRes, assetsRes] = await Promise.all([
    sb.from('buildings').select('id,costar_property_id,name,address,city,lat,lng').eq('id', buildingId).maybeSingle(),
    sb.from('twin_nodes').select('sweep_id,floor,x,y,z,neighbors,label').eq('building_id', buildingId).limit(5000),
    sb.from('cameras').select('id,name,sweep_id,floor,landmark').eq('building_id', buildingId),
    sb.from('assets').select('sweep_id,label,flags').eq('building_id', buildingId).eq('type', 'aed').neq('source', 'proposed'),
  ]);
  if (buildingRes.error) throw buildingRes.error;
  if (nodesRes.error) throw nodesRes.error;
  return {
    building: buildingRes.data as BuildingRow | null,
    nodes: (nodesRes.data ?? []) as LabeledNode[],
    cameras: camerasRes.error ? [] : ((camerasRes.data ?? []) as CalibrationData['cameras']),
    aeds: assetsRes.error ? [] : ((assetsRes.data ?? []) as CalibrationData['aeds']),
  };
}

/**
 * The spots to record, in this order: each camera's sweep (where the person would be), each AED's
 * sweep, then every other sweep that has a label. A sweep is listed once.
 */
export function referenceSpots(data: CalibrationData): RefSpot[] {
  const byId = new Map(data.nodes.map((n) => [n.sweep_id, n]));
  const out: RefSpot[] = [];
  const seen = new Set<string>();
  const add = (id: string | null, kind: RefSpot['kind'], title: string) => {
    if (!id || seen.has(id)) return;
    const n = byId.get(id);
    if (!n || typeof n.x !== 'number' || typeof n.z !== 'number') return;
    seen.add(id);
    out.push({ id, kind, title, floor: n.floor ?? 0, plan: { x: n.x, z: n.z } });
  };
  for (const c of data.cameras) {
    const where = c.landmark ?? byId.get(c.sweep_id ?? '')?.label ?? null;
    add(c.sweep_id, 'patient', `Patient spot: ${c.name ?? c.id}${where ? `, ${where}` : ''}`);
  }
  for (const a of data.aeds) {
    const where = a.label ?? byId.get(a.sweep_id ?? '')?.label ?? null;
    add(a.sweep_id, 'aed', `AED spot${where ? `: ${where}` : ''}`);
  }
  const labeled = data.nodes.filter((n) => n.label).sort((a, b) => (a.label ?? '').localeCompare(b.label ?? ''));
  for (const n of labeled) add(n.sweep_id, 'label', `Labeled spot: ${n.label}`);
  return out;
}
