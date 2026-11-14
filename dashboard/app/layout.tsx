import type { Metadata } from "next";
import { AppStatusProvider } from "@/components/shell/AppStatus";
import { TopBar } from "@/components/shell/TopBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Within Reach",
  description: "Life-safety census of real buildings, and the live response that uses it.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="flex h-full flex-col overflow-hidden">
        <AppStatusProvider>
          <TopBar />
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
          </div>
        </AppStatusProvider>
      </body>
    </html>
  );
}
