-- DEMO ONLY. NOT PRODUCTION SECURITY.
--
-- Demo auth bypass (spec section 6, docs/ARCHITECTURE.md decision D10). The dashboard and the
-- mobile app use the anon key. Row level security is on for every table, and the anon role may:
--   - read every table (also what Supabase Realtime needs to deliver changes to anon clients);
--   - insert and update rows in responders (the mobile app manages its own row).
-- Every other write goes through the service-role key, which only Python holds and which bypasses
-- row level security. A real deployment needs authenticated users and per-row policies instead.

do $$
declare
  t text;
begin
  foreach t in array array[
    'buildings', 'twin_nodes', 'panos', 'detections', 'assets', 'coverage', 'building_scores',
    'fixes', 'documents', 'runs', 'agent_events', 'cameras', 'camera_routes', 'responders',
    'incidents', 'incident_events', 'dispatches'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists demo_read on public.%I', t);
    execute format(
      'create policy demo_read on public.%I for select to anon, authenticated using (true)', t
    );
    execute format('grant select on public.%I to anon, authenticated', t);
  end loop;
end
$$;

drop policy if exists demo_responder_insert on public.responders;
create policy demo_responder_insert on public.responders
  for insert to anon, authenticated with check (true);

drop policy if exists demo_responder_update on public.responders;
create policy demo_responder_update on public.responders
  for update to anon, authenticated using (true) with check (true);

grant insert, update on public.responders to anon, authenticated;
