"use client";

import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { AgentConsole } from "@/components/console/AgentConsole";

/** The census agent console, except on /live, which needs the full width. */
function Gate() {
  const pathname = usePathname();
  if (pathname?.startsWith("/live")) return null;
  return <AgentConsole />;
}

export function ConsoleGate() {
  return (
    <Suspense fallback={null}>
      <Gate />
    </Suspense>
  );
}
