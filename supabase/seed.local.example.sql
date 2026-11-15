-- Template for supabase/seed.local.sql, which is git-ignored. Copy it, fill in real numbers in
-- E.164 format (for example +1 then ten digits), and run it after seed.sql. Never commit real numbers.
-- Never put an emergency number here: the 911 briefing goes to DISPATCH_SIM_NUMBER (a teammate).

update public.responders set name = 'TEAMMATE_A_NAME', phone = 'TEAMMATE_A_PHONE'
 where id = 'a0000000-0000-4000-8000-000000000001';

update public.responders set name = 'TEAMMATE_B_NAME', phone = 'TEAMMATE_B_PHONE'
 where id = 'a0000000-0000-4000-8000-000000000002';

-- Caller of record for the 911 briefing (spec section 12: a teammate), on the fallback and the
-- demo building.
update public.buildings set monitoring_callback = 'MONITORING_CALLBACK_PHONE'
 where costar_property_id in ('FALLBACK-1', 'DEMO-RABINOWITZ');
