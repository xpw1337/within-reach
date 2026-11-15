import { requireSupabase } from './supabase';
import type { AssetRow, BuildingRow, CameraRouteRow, CameraRow, IncidentRow, TwinNodeRow } from './types';

export type AlertContext = {
  incident: IncidentRow | null;
  camera: CameraRow | null;
  routes: CameraRouteRow[];
  building: BuildingRow | null;
  /** Every scan position of the building. Empty when the building has no twin (outdoor map fallback). */
  nodes: TwinNodeRow[];
  /** The building's AED (never a proposed one), preferring the one the camera's AED route ends at. */
  aed: AssetRow | null;
};

/**
 * Reads the incident, its camera, the camera's precomputed routes, the building, its twin nodes and
 * its AED (anon select). The twin and the AED are optional extras: if they fail to load the alert
 * still works with the outdoor map.
 */
export async function loadAlertContext(incidentId: string): Promise<AlertContext> {
  const sb = requireSupabase();
  const { data: incidentData, error } = await sb
    .from('incidents')
    .select('id,type,status,camera_id,building_id,witnessed,modifiers,scene_safe,hazards')
    .eq('id', incidentId)
    .maybeSingle();
  if (error) throw error;
  const incident = incidentData as IncidentRow | null;

  let camera: CameraRow | null = null;
  let routes: CameraRouteRow[] = [];
  if (incident?.camera_id) {
    const [cameraRes, routesRes] = await Promise.all([
      sb.from('cameras').select('id,name,building_id,sweep_id,floor,landmark,lat,lng').eq('id', incident.camera_id).maybeSingle(),
      sb.from('camera_routes').select('camera_id,target,path,distance_m,directions,audio_url').eq('camera_id', incident.camera_id),
    ]);
    if (cameraRes.error) throw cameraRes.error;
    if (routesRes.error) throw routesRes.error;
    camera = cameraRes.data as CameraRow | null;
    routes = (routesRes.data ?? []) as CameraRouteRow[];
  }

  let building: BuildingRow | null = null;
  let nodes: TwinNodeRow[] = [];
  let aed: AssetRow | null = null;
  const buildingId = incident?.building_id ?? camera?.building_id ?? null;
  if (buildingId) {
    const [buildingRes, nodesRes, assetsRes] = await Promise.all([
      sb.from('buildings').select('id,costar_property_id,name,address,city,lat,lng').eq('id', buildingId).maybeSingle(),
      sb.from('twin_nodes').select('sweep_id,floor,x,y,z,neighbors').eq('building_id', buildingId).limit(5000),
      sb
        .from('assets')
        .select('id,type,sweep_id,floor,label,x,z,source,flags')
        .eq('building_id', buildingId)
        .eq('type', 'aed')
        .neq('source', 'proposed'),
    ]);
    if (buildingRes.error) throw buildingRes.error;
    building = buildingRes.data as BuildingRow | null;
    if (!nodesRes.error) nodes = (nodesRes.data ?? []) as TwinNodeRow[];
    if (!assetsRes.error) {
      const aeds = (assetsRes.data ?? []) as AssetRow[];
      const routePath = routes.find((r) => r.target === 'aed')?.path ?? [];
      const routeEnd = routePath.length > 0 ? routePath[routePath.length - 1] : null;
      aed = aeds.find((a) => routeEnd !== null && a.sweep_id === routeEnd) ?? aeds[0] ?? null;
    }
  }

  return { incident, camera, routes, building, nodes, aed };
}

/** Where the person is: the camera position if it has one, else the building. */
export function incidentPoint(ctx: AlertContext | null): { lat: number; lng: number } | null {
  if (ctx?.camera?.lat != null && ctx.camera.lng != null) return { lat: ctx.camera.lat, lng: ctx.camera.lng };
  if (ctx?.building?.lat != null && ctx.building.lng != null) return { lat: ctx.building.lat, lng: ctx.building.lng };
  return null;
}
