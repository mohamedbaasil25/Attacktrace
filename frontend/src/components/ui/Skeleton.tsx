/** Loading placeholder: shimmer for <=1.2s, then holds static (no infinite shimmer -- the spec
 *  caps it so a stuck connection doesn't read as "still loading forever"). */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={`animate-[shimmer_1.2s_ease-out_1] rounded-sm bg-surface-3 ${className}`}
    />
  );
}
