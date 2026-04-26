"use client";

import { useEffect } from "react";
import { GreeksDisplay } from "@/components/greeks/greeks-display";
import { PageHeader, PageMeta } from "@/components/operator/page-header";
import { useGreeksStore } from "@/stores/greeks-store";
import { getGreeks } from "@/lib/api";

export default function GreeksPage() {
  const setPortfolioGreeks = useGreeksStore((s) => s.setPortfolioGreeks);

  useEffect(() => {
    let mounted = true;
    async function fetchGreeks() {
      try {
        const greeks = await getGreeks();
        if (mounted) setPortfolioGreeks(greeks);
      } catch {
        /* non-fatal: poll will retry */
      }
    }
    fetchGreeks();
    const interval = setInterval(fetchGreeks, 10_000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [setPortfolioGreeks]);

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="02"
        section="Risk Surface"
        title="Portfolio Greeks"
        lede="The aggregate exposure of the book to delta, gamma, theta, and vega — refreshed every ten seconds."
        meta={<PageMeta label="Updated" value="live · 10s poll" />}
      />
      <div className="mt-10">
        <GreeksDisplay />
      </div>
    </div>
  );
}
