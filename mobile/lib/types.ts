// Row shapes for the tables the app touches, copied from supabase/migrations/0001_init.sql.
// Only the columns the app reads or writes are listed for the larger tables.
// These are `type` aliases (not interfaces) so they satisfy supabase-js generic constraints.

export type ResponderRole = 'public' | 'staff' | 'security' | 'tenant';
export type DispatchChannel = 'app' | 'call' | 'speaker' | 'broadcast';
export type DispatchStatus = 'sent' | 'accepted' | 'declined' | 'timeout' | 'released' | 'arrived';
export type DispatchRole = 'patient' | 'aed_runner' | 'staff' | 'broadcast';
export type IncidentType = 'cardiac' | 'fall' | 'fire' | 'unknown';
export type IncidentStatus =
  | 'detected'
  | 'awaiting_confirm'
  | 'voice_check'
  | 'confirmed'
  | 'responding'
  | 'resolved'
  | 'false_alarm';

export type ResponderRow = {
  id: string;
  name: string;
  phone: string;
  callable: boolean;
  cpr_trained: boolean;
  role: ResponderRole;
  building_id: string | null;
  last_lat: number | null;
  last_lng: number | null;
  last_seen_at: string | null;
  consent_location: boolean;
  consent_calls: boolean;
  on_duty: boolean;
};

export type DispatchRow = {
  id: string;
  incident_id: string | null;
  responder_id: string | null;
  channel: DispatchChannel | null;
  role: DispatchRole | null;
  wave: number | null;
  status: DispatchStatus;
  call_sid: string | null;
  sent_at: string;
  responded_at: string | null;
};

export type IncidentRow = {
  id: string;
  type: IncidentType;
  status: IncidentStatus;
  camera_id: string | null;
  building_id: string | null;
  witnessed: boolean | null;
  modifiers: string[] | null;
  scene_safe: boolean | null;
  hazards: string[] | null;
};

export type CameraRow = {
  id: string;
  name: string | null;
  building_id: string | null;
  sweep_id: string | null;
  floor: number | null;
  landmark: string | null;
  lat: number | null;
  lng: number | null;
};

export type RouteTarget = 'aed' | 'naloxone' | 'exit' | 'extinguisher';

export type CameraRouteRow = {
  camera_id: string;
  target: RouteTarget;
  path: string[] | null;
  distance_m: number | null;
  directions: string | null;
  audio_url: string | null;
};

/** One scan position. Model space in meters, y up; floor plans are drawn from x and z. */
export type TwinNodeRow = {
  sweep_id: string;
  floor: number | null;
  x: number | null;
  y: number | null;
  z: number | null;
  neighbors: string[] | null;
};

export type AssetSource = 'detected' | 'tag' | 'manual' | 'proposed';

export type AssetRow = {
  id: string;
  type: string;
  sweep_id: string | null;
  floor: number | null;
  label: string | null;
  x: number | null;
  z: number | null;
  source: AssetSource | null;
  flags: string[] | null;
};

export type BuildingRow = {
  id: string;
  /** Selected where the georeference defaults are looked up (lib/georefStore.ts); absent elsewhere. */
  costar_property_id?: string | null;
  name: string | null;
  address: string | null;
  city: string | null;
  lat: number | null;
  lng: number | null;
};
