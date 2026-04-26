import type { ReactNode } from "react";

/**
 * Editorial page header. Numbered eyebrow on top, oversize serif
 * title with an amber period, an optional editorial lede paragraph
 * in italic serif, and an optional right-aligned meta block.
 */
export function PageHeader({
  number,
  section,
  title,
  lede,
  meta,
}: {
  number: string;
  section: string;
  title: string;
  lede?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header>
      <div className="flex items-end justify-between border-b border-rule pb-6">
        <div>
          <div className="eyebrow">
            {number} — {section}
          </div>
          <h1 className="mt-2 font-display text-[56px] sm:text-[72px] leading-[0.95] tracking-tight text-foreground">
            {title}
            <span className="text-accent">.</span>
          </h1>
        </div>
        {meta && <div className="hidden md:block text-right">{meta}</div>}
      </div>
      {lede && (
        <p className="mt-6 max-w-2xl font-display italic text-[18px] leading-snug text-muted-foreground">
          {lede}
        </p>
      )}
    </header>
  );
}

/**
 * Right-aligned meta block helper.
 */
export function PageMeta({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div className="eyebrow">{label}</div>
      <div className="mt-1.5 text-xs text-muted-foreground tnum">{value}</div>
    </>
  );
}
