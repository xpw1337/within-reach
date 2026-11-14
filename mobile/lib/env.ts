// Expo inlines EXPO_PUBLIC_* variables at bundle time, but only for direct
// `process.env.EXPO_PUBLIC_NAME` reads, so keep each access spelled out.
// Values come from mobile/.env (see mobile/README.md).

function trimSlash(value: string | undefined): string {
  return (value ?? '').trim().replace(/\/+$/, '');
}

export const env = {
  supabaseUrl: trimSlash(process.env.EXPO_PUBLIC_SUPABASE_URL),
  supabaseAnonKey: (process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? '').trim(),
  agentUrl: trimSlash(process.env.EXPO_PUBLIC_AGENT_URL),
  dashboardUrl: trimSlash(process.env.EXPO_PUBLIC_DASHBOARD_URL),
};

/** Names of required variables that are empty in this build. */
export function missingEnv(): string[] {
  const missing: string[] = [];
  if (!env.supabaseUrl) missing.push('EXPO_PUBLIC_SUPABASE_URL');
  if (!env.supabaseAnonKey) missing.push('EXPO_PUBLIC_SUPABASE_ANON_KEY');
  if (!env.agentUrl) missing.push('EXPO_PUBLIC_AGENT_URL');
  if (!env.dashboardUrl) missing.push('EXPO_PUBLIC_DASHBOARD_URL');
  return missing;
}
