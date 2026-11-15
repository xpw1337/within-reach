import type { NextConfig } from "next";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

// The team keeps one .env at the repo root (see .env.example). Next only reads
// .env files in this folder, so copy the NEXT_PUBLIC_* keys from the root file
// too. Values already set (shell, dashboard/.env.local) win. Only NEXT_PUBLIC_*
// keys are read: server secrets in the root file never enter this process.
function loadRootPublicEnv() {
  const root = path.resolve(__dirname, "..");
  for (const name of [".env.local", ".env"]) {
    const file = path.join(root, name);
    if (!existsSync(file)) continue;
    for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
      const m = /^\s*(NEXT_PUBLIC_[A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
      if (!m) continue;
      const [, key, raw] = m;
      const value = raw.replace(/^(['"])(.*)\1$/, "$2");
      if (process.env[key] === undefined || process.env[key] === "") {
        process.env[key] = value;
      }
    }
  }
}
loadRootPublicEnv();

// Unset: the agent runs on the same machine as the dashboard server (the proxy below runs server-side).
const agentUrl = (process.env.NEXT_PUBLIC_AGENT_URL ?? "").replace(/\/+$/, "") || "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Do not let `next dev` write AGENTS.md into the repo.
  agentRules: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // The browser calls the agent API through this same-origin path, so the
  // agent needs no CORS setup and a second machine can open the dashboard.
  async rewrites() {
    if (!agentUrl) return [];
    return [{ source: "/agent-api/:path*", destination: `${agentUrl}/:path*` }];
  },
};

export default nextConfig;
