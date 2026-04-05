import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { WsProvider } from "@/components/providers/ws-provider";
import { NavSidebar } from "@/components/nav-sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Trading Dashboard",
  description: "Real-time options trading dashboard",
};

/**
 * Root layout -- Server Component (no client directive).
 *
 * Client-side interactivity is delegated to child client components:
 * - NavSidebar: navigation with active link highlighting via usePathname
 * - WsProvider: WebSocket connection lifecycle via useWebSocket hook
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark`}
    >
      <body className="bg-background text-foreground antialiased">
        <div className="grid grid-cols-[240px_1fr] min-h-screen">
          <NavSidebar />
          <main className="p-6 overflow-auto">
            <WsProvider>{children}</WsProvider>
          </main>
        </div>
      </body>
    </html>
  );
}
