-- Demo rows (spec section 12). Run after the migrations and after `python -m data.load --fallback`.
-- Safe to run more than once: every statement upserts.
--
-- Phone numbers here are fictional placeholders in the reserved 555-01xx range. Real numbers for
-- teammates go in supabase/seed.local.sql (git-ignored), run after this file; see
-- supabase/seed.local.example.sql.
--
-- No census results are seeded: coverage, scores, fixes and documents come from running the
-- pipeline on the fallback building, so the demo never shows hand-typed numbers.

do $$
begin
  if not exists (select 1 from public.buildings where costar_property_id = 'FALLBACK-1') then
    raise exception 'Fallback building missing: run `python -m data.load --fallback` before seed.sql';
  end if;
end
$$;

-- Camera cam-lobby-1 watches the sweep labeled "east elevators" in the demo building (the fallback
-- building until a real one is chosen). data.load --fallback writes the same row; this keeps it
-- correct if the loader changed it.
insert into public.cameras (id, name, building_id, sweep_id, floor, landmark, lat, lng, has_speaker)
select 'cam-lobby-1', 'Lobby camera 1', b.id, n.sweep_id, n.floor, 'east elevators', b.lat, b.lng, true
from public.buildings b
join public.twin_nodes n on n.building_id = b.id and n.label = 'east elevators'
where b.costar_property_id = 'FALLBACK-1'
on conflict (id) do update
  set name = excluded.name, building_id = excluded.building_id, sweep_id = excluded.sweep_id,
      floor = excluded.floor, landmark = excluded.landmark, lat = excluded.lat, lng = excluded.lng,
      has_speaker = excluded.has_speaker;

-- Caller of record for the 911 briefing: a teammate. Placeholder here, real number in seed.local.sql.
update public.buildings
   set monitoring_callback = '+17135550199'
 where costar_property_id = 'FALLBACK-1';

-- Responders. Positions are offsets from the building: 0.0001 degrees of latitude is about 11 m,
-- so the six building responders sit inside the 60 m geofence and the two outdoor ones about 150 m out.
-- last_seen_at is set to now(); the live path only alerts responders seen in the last 10 minutes.
insert into public.responders (
  id, name, phone, callable, cpr_trained, role, building_id,
  last_lat, last_lng, last_seen_at, consent_location, consent_calls, on_duty
)
select r.id::uuid, r.name, r.phone, r.callable, r.cpr_trained, r.role::responder_role,
       case when r.outdoor then null else b.id end,
       b.lat + r.dlat, b.lng + r.dlng, now(), true, r.callable, true
from public.buildings b
cross join (values
  -- id                                     name                      phone           callable cpr   role      outdoor dlat     dlng
  ('a0000000-0000-4000-8000-000000000001', 'Teammate A (staff)',      '+17135550101', true,    true,  'staff',  false,  0.0001,  0.0001),
  ('a0000000-0000-4000-8000-000000000002', 'Teammate B (public)',     '+17135550102', true,    false, 'public', false, -0.0001,  0.0002),
  ('a0000000-0000-4000-8000-000000000003', 'Seeded security',         '+17135550103', false,   true,  'security', false, 0.0002, -0.0001),
  ('a0000000-0000-4000-8000-000000000004', 'Seeded tenant',           '+17135550104', false,   true,  'tenant', false, -0.0002, -0.0002),
  ('a0000000-0000-4000-8000-000000000005', 'Seeded public 1',         '+17135550105', false,   true,  'public', false,  0.0003,  0.0000),
  ('a0000000-0000-4000-8000-000000000006', 'Seeded public 2',         '+17135550106', false,   false, 'public', false,  0.0000,  0.0003),
  ('a0000000-0000-4000-8000-000000000007', 'Outdoor responder 1',     '+17135550107', false,   true,  'public', true,   0.0014,  0.0000),
  ('a0000000-0000-4000-8000-000000000008', 'Outdoor responder 2',     '+17135550108', false,   false, 'public', true,   0.0000, -0.0016)
) as r(id, name, phone, callable, cpr_trained, role, outdoor, dlat, dlng)
where b.costar_property_id = 'FALLBACK-1'
on conflict (id) do update
  set name = excluded.name, phone = excluded.phone, callable = excluded.callable,
      cpr_trained = excluded.cpr_trained, role = excluded.role, building_id = excluded.building_id,
      last_lat = excluded.last_lat, last_lng = excluded.last_lng, last_seen_at = excluded.last_seen_at,
      consent_location = excluded.consent_location, consent_calls = excluded.consent_calls,
      on_duty = excluded.on_duty;
