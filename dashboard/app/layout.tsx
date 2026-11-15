import type { Metadata } from "next";
import { ConsoleGate } from "@/components/shell/ConsoleGate";
import { AppStatusProvider } from "@/components/shell/AppStatus";
import { TopBar } from "@/components/shell/TopBar";
import { Nunito } from "next/font/google";
import "./globals.css";

const nunito = Nunito({ subsets: ["latin"], weight: ["600", "700", "800", "900"], variable: "--font-nunito" });

export const metadata: Metadata = {
  title: "Within Reach",
  description: "Camera-detected falls and fires, the nearest responder alerted, and directions to them and the nearest AED or extinguisher.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full ${nunito.variable}`}>
      <body className="flex h-full flex-col overflow-hidden">
        <AppStatusProvider>
          <TopBar />
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
            <ConsoleGate />
          </div>
        </AppStatusProvider>
      </body>
    </html>
  );
}
