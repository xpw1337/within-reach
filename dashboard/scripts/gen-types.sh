#!/usr/bin/env bash
# Generate dashboard/lib/types.ts from the Supabase schema. No Docker needed.
#
# `supabase gen types --local` and `--db-url` both start the postgres-meta
# Docker image. This script runs the same generator (the
# @supabase/postgres-meta npm package, pinned below) directly under Node.
#
# Default mode: build a throwaway Postgres cluster in dashboard/.cache-pg
# (TCP 127.0.0.1:54333), apply supabase/migrations/*.sql in order on top of
# minimal stand-ins for the Supabase-only objects they reference, generate,
# then stop the cluster.
#
#   scripts/gen-types.sh
#
# Against a real database (for example the hosted project) instead:
#
#   DB_URL='postgresql://postgres:<password>@<host>:5432/postgres' scripts/gen-types.sh
#
# Env overrides: PG_BIN (Postgres binaries), PG_PORT (default 54333).
set -euo pipefail

PG_META_VERSION="0.100.0"

DASH="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$DASH/.." && pwd)"
CACHE="$DASH/.cache-pg"
TOOLS="$CACHE/pgmeta"
OUT="$DASH/lib/types.ts"
mkdir -p "$CACHE"

# 1. The generator.
installed=""
if [ -f "$TOOLS/node_modules/@supabase/postgres-meta/package.json" ]; then
  installed="$(node -p "require('$TOOLS/node_modules/@supabase/postgres-meta/package.json').version")"
fi
if [ "$installed" != "$PG_META_VERSION" ]; then
  echo "Installing @supabase/postgres-meta@$PG_META_VERSION into $TOOLS"
  mkdir -p "$TOOLS"
  printf '{ "private": true }\n' > "$TOOLS/package.json"
  (cd "$TOOLS" && npm install --no-audit --no-fund --ignore-scripts --save-exact \
    "@supabase/postgres-meta@$PG_META_VERSION" >/dev/null)
fi

# 2. The database.
started_here=""
DATA="$CACHE/data"
PG_PORT="${PG_PORT:-54333}"
if [ -z "${PG_BIN:-}" ]; then
  PG_BIN="$(pg_config --bindir 2>/dev/null || echo /opt/homebrew/bin)"
fi

stop_cluster() {
  if [ -n "$started_here" ]; then
    "$PG_BIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null || true
  fi
}
trap stop_cluster EXIT

if [ -z "${DB_URL:-}" ]; then
  if [ ! -f "$DATA/PG_VERSION" ]; then
    "$PG_BIN/initdb" -D "$DATA" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null
  fi
  if ! "$PG_BIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then
    # Unix sockets are off: the worktree path is longer than the socket path limit.
    "$PG_BIN/pg_ctl" -D "$DATA" -l "$CACHE/log.txt" -w \
      -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=''" start >/dev/null
    started_here="yes"
  fi

  export PGHOST=127.0.0.1 PGPORT="$PG_PORT" PGUSER=postgres
  "$PG_BIN/psql" -q -v ON_ERROR_STOP=1 -d postgres \
    -c "drop database if exists within_reach_types" \
    -c "create database within_reach_types" >/dev/null

  # Stand-ins for objects every hosted Supabase project already has.
  "$PG_BIN/psql" -q -v ON_ERROR_STOP=1 -d within_reach_types >/dev/null <<'SQL'
set client_min_messages = warning;
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
end $$;
create schema if not exists auth;
create or replace function auth.uid() returns uuid language sql stable as $f$ select null::uuid $f$;
create or replace function auth.role() returns text language sql stable as $f$ select 'anon'::text $f$;
create or replace function auth.jwt() returns jsonb language sql stable as $f$ select '{}'::jsonb $f$;
create schema if not exists storage;
create table if not exists storage.buckets (
  id text primary key, name text not null, owner uuid, public boolean default false,
  avif_autodetection boolean default false, file_size_limit bigint, allowed_mime_types text[],
  created_at timestamptz default now(), updated_at timestamptz default now()
);
create table if not exists storage.objects (
  id uuid primary key default gen_random_uuid(), bucket_id text references storage.buckets(id),
  name text, owner uuid, owner_id text, metadata jsonb, path_tokens text[], version text,
  created_at timestamptz default now(), updated_at timestamptz default now(),
  last_accessed_at timestamptz default now()
);
create publication supabase_realtime;
SQL

  for f in "$ROOT"/supabase/migrations/*.sql; do
    echo "Applying $(basename "$f")"
    if ! "$PG_BIN/psql" -q -v ON_ERROR_STOP=1 -1 -d within_reach_types -f "$f" >/dev/null 2>"$CACHE/migration.err"; then
      cat "$CACHE/migration.err" >&2
      echo "Migration $(basename "$f") failed. If it needs another Supabase-only object, add a stand-in above." >&2
      exit 1
    fi
  done
  DB_URL="postgresql://postgres@127.0.0.1:$PG_PORT/within_reach_types"
fi

# 3. Generate.
tmp="$(mktemp)"
PG_META_DB_URL="$DB_URL" \
PG_META_GENERATE_TYPES=typescript \
PG_META_GENERATE_TYPES_INCLUDED_SCHEMAS=public \
PG_META_GENERATE_TYPES_DETECT_ONE_TO_ONE_RELATIONSHIPS=true \
  node "$TOOLS/node_modules/@supabase/postgres-meta/dist/server/server.js" >"$tmp" 2>"$CACHE/generate.err" || {
    cat "$CACHE/generate.err" >&2
    rm -f "$tmp"
    exit 1
  }
if ! grep -q "export type Database" "$tmp"; then
  echo "Generator output has no Database type; see $CACHE/generate.err" >&2
  rm -f "$tmp"
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
{
  echo "// Generated by dashboard/scripts/gen-types.sh from supabase/migrations"
  echo "// with @supabase/postgres-meta $PG_META_VERSION. Do not edit by hand; rerun the script."
  echo
  cat "$tmp"
} >"$OUT"
rm -f "$tmp"
echo "Wrote $OUT"
