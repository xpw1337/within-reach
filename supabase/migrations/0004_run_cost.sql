-- Atomic cost metering for the census budget guard (spec section 9.2).
--
-- shared/llm.py adds the cost of every LLM call to runs.est_cost_usd. Many workers can finish calls
-- at the same moment, so the increment happens in one UPDATE instead of read-modify-write.
-- A function only: no table or column changes. Callable by the service role only.

create or replace function public.add_run_cost(p_run_id uuid, p_delta real)
returns real
language sql
as $$
  update public.runs
     set est_cost_usd = coalesce(est_cost_usd, 0) + p_delta
   where id = p_run_id
  returning est_cost_usd;
$$;

revoke execute on function public.add_run_cost(uuid, real) from public, anon, authenticated;
grant execute on function public.add_run_cost(uuid, real) to service_role;
