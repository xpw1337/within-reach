create extension if not exists pgcrypto;

create type asset_type as enum ('aed','naloxone','extinguisher','exit','exit_sign','sprinkler','smoke_detector','first_aid','stairs','elevator');
create type incident_type    as enum ('cardiac','fall','fire','unknown');
create type incident_status  as enum ('detected','awaiting_confirm','voice_check','confirmed','responding','resolved','false_alarm');
create type dispatch_channel as enum ('app','call','speaker','broadcast');
create type dispatch_status  as enum ('sent','accepted','declined','timeout','released','arrived');
create type dispatch_role    as enum ('patient','aed_runner','staff','broadcast');
create type responder_role   as enum ('public','staff','security','tenant');

-- ===== Census =====
create table buildings (
  id uuid primary key default gen_random_uuid(),
  costar_property_id text unique, matterport_model_id text,
  name text, address text, city text,              -- 'Houston' | 'Los Angeles'
  lat double precision, lng double precision, geofence_m int default 60,
  property_type text, floors int, size_sqft int, tenants_count int,
  occupancy_est int,                                -- derived: tenants/size × type factor
  manager jsonb, contacts jsonb default '[]', monitoring_callback text,
  vexcel jsonb,                                     -- {entrances:[], ambulance_parking:[], hydrants:[], image_url}
  ems_door jsonb,                                   -- chosen entrance {lat,lng,desc,reason}
  census_status text default 'pending',             -- pending|scanning|mapped|fixed|error
  priority_score real, created_at timestamptz default now()
);

create table twin_nodes (
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, floor int, x double precision, y double precision, z double precision,
  neighbors text[] not null default '{}', room_type text, label text,
  is_elevator boolean default false, is_stairs boolean default false,
  primary key (building_id, sweep_id)
);

create table panos (
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, image_uri text, tiles_done boolean default false,
  primary key (building_id, sweep_id)
);

create table detections (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, asset_type asset_type, tile_heading real, tile_pitch real,
  bbox real[], crop_uri text, confidence real,
  verified_by text,                                 -- 'first_pass'|'claude'|'second_pano'|'human'
  status text default 'candidate',                  -- candidate|confirmed|rejected
  human_label text,                                 -- for the ~30 hand-checks
  notes text, created_at timestamptz default now()
);

create table assets (                               -- confirmed equipment pinned to the twin
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  type asset_type not null, sweep_id text, floor int, label text,
  x double precision, y double precision, z double precision,   -- triangulated if seen from 2 panos
  source text check (source in ('detected','tag','manual','proposed')) default 'detected',
  detection_ids uuid[] default '{}', verified boolean default false,
  flags text[] default '{}'                          -- e.g. 'blocked_exit'
);

create table coverage (                             -- walking-time map
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, asset_type asset_type, time_s real,
  scenario text default 'current',                  -- 'current'|'proposed'
  primary key (building_id, sweep_id, asset_type, scenario)
);

create table building_scores (
  building_id uuid primary key references buildings(id) on delete cascade,
  aed_worst_s real, aed_red_frac real,
  ext_worst_s real, ext_red_frac real,
  exit_worst_s real, exit_red_frac real,
  stairs_only boolean, blocked_exits int,
  worst_gap text,                                   -- 'aed'|'extinguisher'|'exit'|'none'
  people_at_risk int, gap_score real, rank int, updated_at timestamptz default now()
);

create table fixes (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  asset_type asset_type, sweep_id text,
  before_worst_s real, after_worst_s real, before_red_frac real, after_red_frac real,
  rationale text
);

create table documents (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  kind text check (kind in ('owner_letter','emergency_card','registry_list')),
  content_md text, created_at timestamptz default now()
);

create table runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz default now(), finished_at timestamptz,
  buildings_target int, buildings_done int default 0, panos_done int default 0,
  est_cost_usd real default 0, status text default 'running', notes text
);

create table agent_events (                         -- powers the on-screen agent console
  id bigserial primary key, run_id uuid references runs(id) on delete cascade,
  ts timestamptz default now(),
  agent text,                                       -- planner|records|scanner|mapper|outside|fixer
  kind text,                                        -- todo|decision|tool_call|result|warning
  building_id uuid, message text, payload jsonb default '{}'
);

-- ===== Live =====
create table cameras (
  id text primary key, name text, building_id uuid references buildings(id),
  sweep_id text, floor int, landmark text, lat double precision, lng double precision,
  has_speaker boolean default true
);

create table camera_routes (
  camera_id text references cameras(id) on delete cascade,
  target text check (target in ('aed','naloxone','exit','extinguisher')),
  path text[], distance_m real, directions text, audio_url text,
  primary key (camera_id, target)
);

create table responders (
  id uuid primary key default gen_random_uuid(),
  name text not null, phone text not null, callable boolean default false,
  cpr_trained boolean default false, role responder_role default 'public',
  building_id uuid references buildings(id),
  last_lat double precision, last_lng double precision, last_seen_at timestamptz,
  consent_location boolean default false, consent_calls boolean default false, on_duty boolean default true
);

create table incidents (
  id uuid primary key default gen_random_uuid(),
  type incident_type default 'unknown', status incident_status default 'detected',
  camera_id text references cameras(id), building_id uuid references buildings(id),
  witnessed boolean, modifiers text[] default '{}', scene_safe boolean, hazards text[] default '{}',
  verification jsonb, confirmed_by text, snapshot_url text,
  collapse_at timestamptz, first_instruction_at timestamptz, confirmed_at timestamptz,
  ems_notified_at timestamptz, first_accept_at timestamptz, responder_arrived_at timestamptz,
  cpr_started_at timestamptz, aed_arrived_at timestamptz, resolved_at timestamptz,
  created_at timestamptz default now()
);

create table incident_events (
  id bigserial primary key, incident_id uuid references incidents(id) on delete cascade,
  ts timestamptz default now(), actor text, kind text, payload jsonb default '{}'
);

create table dispatches (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid references incidents(id) on delete cascade, responder_id uuid references responders(id),
  channel dispatch_channel, role dispatch_role, wave int default 1,
  status dispatch_status default 'sent', call_sid text,
  sent_at timestamptz default now(), responded_at timestamptz
);

alter publication supabase_realtime add table agent_events, runs, building_scores, incidents, incident_events, dispatches, responders;
