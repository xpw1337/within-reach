import { requireSupabase } from './supabase';
import type { BuildingRow } from './types';

const PAGE = 20;

/** Characters that would break a PostgREST `or=(...)` filter. */
function sanitize(query: string): string {
  return query.replace(/[,()%*\\]/g, ' ').trim();
}

/** Buildings matching the query by name or address, alphabetical, first page only. */
export async function searchBuildings(query: string): Promise<BuildingRow[]> {
  let request = requireSupabase().from('buildings').select('id,name,address,city,lat,lng').order('name').limit(PAGE);
  const q = sanitize(query);
  if (q) request = request.or(`name.ilike.%${q}%,address.ilike.%${q}%`);
  const { data, error } = await request;
  if (error) throw error;
  return (data ?? []) as BuildingRow[];
}

export function buildingLabel(b: Pick<BuildingRow, 'name' | 'address' | 'city'>): string {
  const parts = [b.name, b.address, b.city].filter((p): p is string => Boolean(p && p.trim()));
  return parts.length ? parts.join(', ') : 'Unnamed building';
}
