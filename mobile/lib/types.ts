// Shapes sent by the agent over /sos/ws/phone (agent/sos/hub.py, phone_state).

export type LatLng = { lat: number; lng: number };

export type Step = { text: string; distance_m: number };

export type LegKind = 'extinguisher' | 'aed' | 'person';

export type Leg = {
  kind: LegKind;
  to: LatLng & { label?: string | null; id?: string | null; source?: string | null };
  geometry: [number, number][];
  distance_m: number;
  duration_s: number;
  steps: Step[];
  bearing_deg: number;
  source: 'valhalla' | 'direct';
  avoids_fire?: boolean;
  fire_on_route?: boolean;
};

export type Place = LatLng & {
  id: string;
  kind: 'aed' | 'extinguisher';
  label: string;
  source: string;
  distance_m?: number;
};

export type Plan = {
  from: [number, number];
  legs: Leg[];
  total_m: number;
  total_s: number;
  updated_at: number;
  aed_too_far: Place | null;
  no_extinguisher: boolean;
};

export type Fire = LatLng & { active: boolean; radius_m: number; source: string; label: string };

export type IncidentKind = 'fall' | 'fire';

export type Offer = {
  id: string;
  incident_id: string;
  kind: IncidentKind;
  status: string;
  sent_at: number;
  expires_at: number;
  distance_m: number | null;
  place: string | null;
  address: string | null;
  fire: boolean;
  witnessed: boolean | null;
  location: LatLng;
};

export type Mission = {
  id: string;
  kind: IncidentKind;
  status: 'alerting' | 'en_route' | 'on_scene' | 'no_responders' | 'resolved';
  location?: LatLng & { label?: string | null; accuracy_m?: number | null };
  address?: string | null;
  fire?: Fire | null;
  plan?: Plan | null;
  resources?: { aeds: Place[]; extinguishers: Place[]; status: string; error: string | null };
  witnessed?: boolean | null;
  vision?: Record<string, number>;
  timeline?: { at: number; text: string; kind: string }[];
  collected?: string[];
};

export type PhoneState = {
  me: { id: string; name: string; on_duty: boolean; lat: number | null; lng: number | null; has_phone?: boolean; calls?: boolean } | null;
  offer: Offer | null;
  mission: Mission | null;
  server_time: number;
  accept_timeout_s: number;
};
