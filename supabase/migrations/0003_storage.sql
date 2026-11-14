-- Storage buckets (docs/CONTRACTS.md section 5).
--
-- All four buckets are public-read so the dashboard and phones can load objects by URL. Writes go
-- through the service-role key only (no insert policies on storage.objects for anon).
--
--   crops      equipment crops from the census Scanner. Never a full tile, panorama or face.
--   audio      pre-rendered speaker scripts per camera.
--   outside    Vexcel image per building, only if the license allows storing it.
--   snapshots  the one frame sent with person_down. Public-read for the DEMO ONLY so the dashboard
--              can show it; a real deployment would make this bucket private and use signed URLs.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('crops',     'crops',     true, 2097152,  array['image/jpeg']),
  ('audio',     'audio',     true, 10485760, array['audio/mpeg']),
  ('outside',   'outside',   true, 10485760, array['image/jpeg', 'image/png']),
  ('snapshots', 'snapshots', true, 5242880,  array['image/jpeg'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
