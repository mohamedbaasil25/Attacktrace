import type { Mode } from "../../lib/types";
import { SegmentedControl } from "./SegmentedControl";

interface Props {
  mode: Mode;
  haiAvailable: boolean;
  liveAvailable: boolean;
  liveReason?: string | null;
  onChange: (m: Mode) => void;
}

export function ModeToggle({ mode, haiAvailable, liveAvailable, liveReason, onChange }: Props) {
  return (
    <SegmentedControl<Mode>
      aria-label="Mode"
      layoutId="mode-indicator"
      value={mode}
      onChange={onChange}
      segments={[
        { value: "sim", label: "sim" },
        {
          value: "hai",
          label: "hai",
          disabled: !haiAvailable,
          title: !haiAvailable ? "HAI data missing" : undefined,
        },
        {
          value: "live",
          label: "live",
          disabled: !liveAvailable,
          title: !liveAvailable ? (liveReason ?? "LIVE unavailable") : undefined,
        },
      ]}
    />
  );
}
