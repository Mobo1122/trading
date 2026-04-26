import type { Metadata } from "next";
import { Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";

import { WsProvider } from "@/components/providers/ws-provider";
import { NavSidebar } from "@/components/nav-sidebar";
import { LiveBanner } from "@/components/operator/live-banner";
import { StatusBar } from "@/components/operator/status-bar";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Editorial display face: italic for emphasis, regular for headlines.
// Pairs with the mono everywhere to give the system literary gravitas
// rather than terminal coldness alone.
const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "Operator — Trading Console",
  description: "Mission console for an autonomous options trading system",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistMono.variable} ${instrumentSerif.variable} dark`}
    >
      <body className="bg-background text-foreground antialiased">
        <StatusBar />
        <LiveBanner />
        <div className="grid grid-cols-[176px_1fr] min-h-[calc(100vh-2.25rem)]">
          <NavSidebar />
          <main className="overflow-auto border-l border-rule">
            <WsProvider>{children}</WsProvider>
          </main>
        </div>
      </body>
    </html>
  );
}
