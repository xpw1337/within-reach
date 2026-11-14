# dashboard

Next.js (App Router) + Tailwind + TypeScript. Design: `DESIGN.md`. Spec: `CLAUDE.md` section 9.12.

## Run

```bash
npm install
npm run dev          # http://localhost:3000
```

Env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_AGENT_URL`,
`NEXT_PUBLIC_MATTERPORT_SDK_KEY`. They are read from the repo-root `.env` (only the
`NEXT_PUBLIC_*` keys) or from `dashboard/.env.local`, which wins. They are inlined at
build time, so restart `npm run dev` after changing them.

Browser calls to the agent go to `/agent-api/*`, which Next rewrites to
`NEXT_PUBLIC_AGENT_URL`, so the agent needs no CORS setup.

With no env, no agent and empty tables every page still renders: numbers show `--`.

## Checks

```bash
npm run lint
npm run typecheck
npm test             # vitest, pure logic only
npm run build
```

## Schema types

`lib/types.ts` is generated, never hand-written:

```bash
npm run gen-types                                  # throwaway local Postgres from supabase/migrations
DB_URL='postgresql://...' npm run gen-types        # or straight from a real database
```

The script runs `@supabase/postgres-meta` (the generator inside `supabase gen types`) under Node,
so it needs no Docker. Local mode needs Postgres binaries (`initdb`, `pg_ctl`, `psql`).
