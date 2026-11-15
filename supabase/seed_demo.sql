-- Live demo rows for the demo building, Rabinowitz Hall (docs/NEXT.md section 2a). Run after the
-- migrations and after `python -m data.load --file demo/rabinowitz/building.json`, then run
-- seed.local.sql. Safe to run more than once: every statement upserts.
--
-- It places the same eight responders as seed.sql around this building instead of the fallback
-- building (each responder has one position, so the last seed file run decides where they are).
-- The laptop webcam plays the building's camera: set CAMERA_ID=cam-atrium-1 in .env for both the
-- agent and vision/. To test on the fallback building again, run seed.sql and set cam-lobby-1.
--
-- Phone numbers here are fictional placeholders in the reserved 555-01xx range. Real numbers for
-- teammates go in supabase/seed.local.sql (git-ignored).

do $$
begin
  if not exists (select 1 from public.buildings where costar_property_id = 'DEMO-RABINOWITZ') then
    raise exception 'Demo building missing: run `python -m data.load --file demo/rabinowitz/building.json` before seed_demo.sql';
  end if;
  if not exists (select 1 from public.cameras c join public.buildings b on b.id = c.building_id
                 where c.id = 'cam-atrium-1' and b.costar_property_id = 'DEMO-RABINOWITZ') then
    raise exception 'Camera cam-atrium-1 missing: the demo building loader writes it';
  end if;
end
$$;

-- Caller of record for the 911 briefing: a teammate. Placeholder here, real number in seed.local.sql.
update public.buildings
   set monitoring_callback = '+17135550199'
 where costar_property_id = 'DEMO-RABINOWITZ';

-- Responders. Offsets from the building as in seed.sql (0.0001 degrees of latitude is about 11 m).
-- This building's geofence is wider than the schema default, so the two outdoor responders also
-- fall inside it and can be reached by a later wave.
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
where b.costar_property_id = 'DEMO-RABINOWITZ'
on conflict (id) do update
  set name = excluded.name, phone = excluded.phone, callable = excluded.callable,
      cpr_trained = excluded.cpr_trained, role = excluded.role, building_id = excluded.building_id,
      last_lat = excluded.last_lat, last_lng = excluded.last_lng, last_seen_at = excluded.last_seen_at,
      consent_location = excluded.consent_location, consent_calls = excluded.consent_calls,
      on_duty = excluded.on_duty;
