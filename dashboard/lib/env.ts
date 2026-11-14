// Public settings, inlined at build time. Each process.env reference must stay
// literal so Next can replace it.
export const env = {
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
  agentUrl: (process.env.NEXT_PUBLIC_AGENT_URL ?? "").replace(/\/+$/, ""),
  matterportSdkKey: process.env.NEXT_PUBLIC_MATTERPORT_SDK_KEY ?? "",
};

export const supabaseConfigured = Boolean(env.supabaseUrl && env.supabaseAnonKey);
export const agentConfigured = Boolean(env.agentUrl);
