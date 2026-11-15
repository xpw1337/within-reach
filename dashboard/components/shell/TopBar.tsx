"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { cx, Dot } from "@/components/ui";
import { copy } from "@/lib/copy";
import { supabaseConfigured } from "@/lib/env";
import { int, usd } from "@/lib/format";
import { useAppStatus } from "./AppStatus";

const NAV = [
  { href: "/live", label: "Live" },
  { href: "/", label: "City map" },
  { href: "/handcheck", label: "Hand-check" },
];

function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <nav className="flex items-center gap-1">
      {NAV.map((n) => {
        const active = pathname !== null && (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href));
        return (
          <Link
            key={n.href}
            href={n.href}
            className={cx(
              "rounded-xl px-3.5 py-1.5 text-sm font-extrabold transition",
              active ? "bg-accent/10 text-accent" : "text-muted hover:text-text",
            )}
          >
            {n.label}
          </Link>
        );
      })}
      {pathname?.startsWith("/building/") && (
        <span className="rounded-md bg-raised px-3 py-1.5 text-sm font-semibold text-text">Building</span>
      )}
    </nav>
  );
}

// usePathname is runtime data: it streams in behind Suspense so routes can prerender.
function CurrentNav() {
  return <NavLinks pathname={usePathname()} />;
}

export function TopBar() {
  const { latestCensusRun: latestRun, runsStatus, health } = useAppStatus();

  const dataTone = !supabaseConfigured
    ? "down"
    : runsStatus === "live"
      ? "ok"
      : runsStatus === "error"
        ? "down"
        : "warn";
  const dataLabel = !supabaseConfigured
    ? "Data: not configured"
    : runsStatus === "live"
      ? "Data: live"
      : runsStatus === "error"
        ? "Data: error"
        : runsStatus === "reconnecting"
          ? "Data: reconnecting"
          : "Data: connecting";
  const dataTitle = !supabaseConfigured ? copy.supabaseMissing : undefined;

  const apiTone =
    health.status === "up" ? "ok" : health.status === "checking" ? "idle" : health.status === "down" ? "down" : "down";
  const apiLabel =
    health.status === "up"
      ? "Agent API: up"
      : health.status === "checking"
        ? "Agent API: checking"
        : health.status === "down"
          ? "Agent API: unreachable"
          : "Agent API: not configured";

  return (
    <header data-topbar className="flex h-16 shrink-0 items-center gap-6 border-b-2 border-line bg-panel px-6">
      <Link href="/live" className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" className="size-6 fill-accent" aria-hidden>
          <path d="M12 21s-7.5-4.6-9.6-9.3C.9 8.3 3 4.5 6.7 4.5c2.1 0 3.6 1.2 4.3 2.4.7-1.2 2.2-2.4 4.3-2.4 3.7 0 5.8 3.8 4.3 7.2C19.5 16.4 12 21 12 21z" />
        </svg>
        <span className="text-[1.35rem] font-black tracking-tight text-accent">within reach</span>
      </Link>
      <Suspense fallback={<NavLinks pathname={null} />}>
        <CurrentNav />
      </Suspense>
      <div className="ml-auto flex items-center gap-4 text-xs text-muted">
        {latestRun && (
          <span className="hidden items-center gap-2 xl:flex">
            <span className="label">Run</span>
            <span className={cx("font-semibold", latestRun.status === "running" ? "text-accent" : "text-text")}>
              {latestRun.status ?? "--"}
            </span>
            <span className="num text-text">
              {int(latestRun.buildings_done)}/{int(latestRun.buildings_target)}
            </span>
            <span className="num">{usd(latestRun.est_cost_usd)}</span>
          </span>
        )}
        <span className="flex items-center gap-1.5" title={dataTitle}>
          <Dot tone={dataTone} />
          {dataLabel}
        </span>
        <span
          className="flex items-center gap-1.5"
          title={health.status === "down" ? health.error : health.status === "unconfigured" ? copy.agentMissing : undefined}
        >
          <Dot tone={apiTone} />
          {apiLabel}
        </span>
      </div>
    </header>
  );
}
