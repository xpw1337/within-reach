"use client";

import dynamic from "next/dynamic";

// Rendered in the browser only: it reads the clock, the page host and live sockets.
export const LiveConsoleClient = dynamic(() => import("./LiveConsole").then((m) => m.LiveConsole), {
  ssr: false,
  loading: () => <div className="p-6 text-sm text-muted">Loading live console...</div>,
});
