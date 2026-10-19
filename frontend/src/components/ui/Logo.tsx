/** Original wordmark glyph: three nodes and the traced path between them (origin -> two affected
 *  nodes), echoing the product itself. Not a copy of any real mark. */
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-hidden="true">
      <path
        d="M7 17 L12 7 L17 12"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
      <circle cx="12" cy="7" r="3" fill="none" stroke="var(--origin)" strokeWidth="1.75" />
      <circle cx="12" cy="7" r="1" fill="var(--origin)" />
      <circle cx="7" cy="17" r="2" fill="var(--bg-0)" stroke="var(--text-2)" strokeWidth="1.5" />
      <circle cx="17" cy="12" r="2" fill="var(--bg-0)" stroke="var(--text-2)" strokeWidth="1.5" />
    </svg>
  );
}
