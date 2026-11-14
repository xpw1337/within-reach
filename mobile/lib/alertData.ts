import { requireSupabase } from './supabase';
import type { BuildingRow, CameraRouteRow, CameraRow, IncidentRow } from './types';

export type AlertContext = {
  incident: IncidentRow | null;
  camera: CameraRow | null;
  routes: CameraRouteRow[];
  building: BuildingRow | null;
};

/** Reads the incident, its camera, the camera's precomputed routes and the building (anon select). */
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
  const buildingId = incident?.building_id ?? camera?.building_id ?? null;
  if (buildingId) {
    const { data, error: bError } = await sb.from('buildings').select('id,name,address,city,lat,lng').eq('id', buildingId).maybeSingle();
    if (bError) throw bError;
    building = data as BuildingRow | null;
  }

  return { incident, camera, routes, building };
}

/** Where the person is: the camera position if it has one, else the building. */
export function incidentPoint(ctx: AlertContext | null): { lat: number; lng: number } | null {
  if (ctx?.camera?.lat != null && ctx.camera.lng != null) return { lat: ctx.camera.lat, lng: ctx.camera.lng };
  if (ctx?.building?.lat != null && ctx.building.lng != null) return { lat: ctx.building.lat, lng: ctx.building.lng };
  return null;
}
