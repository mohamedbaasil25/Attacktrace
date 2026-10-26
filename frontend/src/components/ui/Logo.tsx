/** Wordmark glyph: a shield (the security product) with a traced anomaly path inside it (the
 *  product's actual job -- origin, then the path it took) instead of a generic security badge.
 *  Not a copy of any real mark. */
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-hidden="true">
      <defs>
        <linearGradient id="logo-shield-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.04" />
        </linearGradient>
      </defs>
      <path
        d="M12 1.6 L20.5 5 V11.2 C20.5 16.4 17 20.4 12 22.4 C7 20.4 3.5 16.4 3.5 11.2 V5 Z"
        fill="url(#logo-shield-fill)"
        stroke="var(--accent)"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path
        d="M7.2 13.6 L10.6 8.8 L14 12.2 L17 7.6"
        fill="none"
        stroke="var(--text-2)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.8"
      />
      <circle cx="10.6" cy="8.8" r="1.5" fill="none" stroke="var(--origin)" strokeWidth="1.5" />
      <circle cx="10.6" cy="8.8" r="0.55" fill="var(--origin)" />
    </svg>
  );
}
