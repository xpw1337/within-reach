import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env, supabaseConfigured } from "./env";
import type { Database } from "./types";

export type DB = SupabaseClient<Database>;

let client: DB | null | undefined;

/**
 * Browser client with the anon key (demo policies allow reads). Returns null
 * when the env is missing so every caller can render an empty state instead
 * of throwing.
 */
export function getSupabase(): DB | null {
  if (client !== undefined) return client;
  if (!supabaseConfigured || typeof window === "undefined") {
    // Never cache the server-side null: the browser must still get a client.
    if (typeof window !== "undefined") client = null;
    return null;
  }
  client = createClient<Database>(env.supabaseUrl, env.supabaseAnonKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  return client;
}

/** PostgREST caps a response at its max-rows setting (1000 by default): page through. */
export async function selectAll<T>(
  page: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
  pageSize = 1000,
  maxRows = 50000,
): Promise<T[]> {
  const out: T[] = [];
  for (let from = 0; from < maxRows; from += pageSize) {
    const { data, error } = await page(from, from + pageSize - 1);
    if (error) throw new Error(error.message);
    const rows = data ?? [];
    out.push(...rows);
    if (rows.length < pageSize) break;
  }
  return out;
}
