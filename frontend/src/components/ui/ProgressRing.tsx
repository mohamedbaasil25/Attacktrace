import { Ring } from "./Ring";

/** A ring that fills as `progress` (0..1) advances; a static partial ring when unknown.
 *  Thin wrapper over the generic `Ring` primitive, kept for the existing call site/contract. */
export function ProgressRing({ progress }: { progress: number | null }) {
  return <Ring value={progress} size={72} strokeWidth={6} />;
}
