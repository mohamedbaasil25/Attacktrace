import { describe, expect, it } from "vitest";
import { f1Rows, parseMetrics, pct } from "./metrics";

const det = (f1: number) => ({
  precision: 0.9,
  recall: 0.8,
  f1,
  false_alarm_per_hour: 1.5,
  mean_detection_delay_s: 9,
  per_scenario: {
    sensor_freeze: { f1: f1 - 0.1, recall: 0.5, runs_detected: 1 },
    sensor_offset: { f1, recall: 0.9, runs_detected: 1 },
  },
});
const good = {
  detection: { attacktrace: det(0.9), baseline: det(0.7), active_model: "gdn" },
  localization: {
    top1: 0.88,
    top3: 1,
    mean_time_to_localize_s: 23.6,
    baseline: { top1: 0.68, top3: 0.86 },
  },
};

describe("parseMetrics", () => {
  it("accepts a complete file and reads the baseline localization", () => {
    expect(parseMetrics(good)?.localization.baseline).toEqual({ top1: 0.68, top3: 0.86 });
  });

  it("accepts an older file without baseline localization", () => {
    const { top1, top3, mean_time_to_localize_s } = good.localization;
    const older = { ...good, localization: { top1, top3, mean_time_to_localize_s } };
    expect(parseMetrics(older)?.localization.baseline).toBeUndefined();
  });

  it.each([
    ["null", null],
    ["no detection", { localization: good.localization }],
    ["no localization", { detection: good.detection }],
    ["missing baseline", { ...good, detection: { attacktrace: det(0.9) } }],
    ["non-numeric f1", { ...good, detection: { ...good.detection, attacktrace: { ...det(0.9), f1: "x" } } }],
    ["no top1", { ...good, localization: { top3: 1 } }],
  ])("rejects %s", (_, raw) => {
    expect(parseMetrics(raw)).toBeNull();
  });
});

describe("f1Rows", () => {
  it("lists overall first, then the scenarios present in both detectors", () => {
    const m = parseMetrics(good);
    expect(m).not.toBeNull();
    if (!m) return;
    const rows = f1Rows(m);
    expect(rows.map((r) => r.label)).toEqual(["Overall", "Freeze", "Offset"]);
    expect(rows[0]).toEqual({ label: "Overall", baseline: 0.7, attacktrace: 0.9 });
  });
});

describe("pct", () => {
  it("rounds to whole percent", () => {
    expect(pct(0.884)).toBe("88%");
    expect(pct(1)).toBe("100%");
  });
});

describe("HAI section", () => {
  const hd = {
    precision: 0.9,
    recall: 0.3,
    f1: 0.45,
    f1_point_adjusted: 0.9,
    false_alarm_per_hour: 0.2,
    windows_detected: 0.8,
    n_windows: 28,
  };
  const hai = {
    files: ["test1"],
    tuned_on: "test2",
    active_model: "mlp",
    attacktrace: hd,
    baseline: { ...hd, f1: 0.08 },
    localization: {
      process_top1: 0.71,
      process_top1_given_detected: 0.91,
      always_majority_given_detected: 0.86,
      always_majority_process: 0.79,
      majority_process: "P1",
      n_windows: 28,
      n_detected: 22,
    },
  };

  it("is read when complete and absent in SIM-only files", () => {
    expect(parseMetrics({ ...good, hai })?.hai?.localization.n_detected).toBe(22);
    expect(parseMetrics(good)?.hai).toBeUndefined();
  });

  it("is dropped, not fatal, when malformed", () => {
    const bad = { ...hai, attacktrace: { ...hd, f1: "x" } };
    const m = parseMetrics({ ...good, hai: bad });
    expect(m).not.toBeNull();
    expect(m?.hai).toBeUndefined();
  });
});

describe("live_session block", () => {
  const session = { mode: "sim" as const, uptime_s: 120, false_alarm_per_hour: 0 };

  it("is read when present and absent otherwise", () => {
    expect(parseMetrics({ ...good, live_session: session })?.live_session).toEqual(session);
    expect(parseMetrics(good)?.live_session).toBeUndefined();
  });

  it("rejects a mode outside sim/live (HAI is never merged by the backend)", () => {
    const m = parseMetrics({ ...good, live_session: { ...session, mode: "hai" } });
    expect(m).not.toBeNull();
    expect(m?.live_session).toBeUndefined();
  });

  it("drops a malformed block instead of failing the page", () => {
    const m = parseMetrics({ ...good, live_session: { mode: "sim" } });
    expect(m).not.toBeNull();
    expect(m?.live_session).toBeUndefined();
  });
});

describe("Phase 11 blocks", () => {
  const amb = { gate_margin: 0.21, n_incidents: 50, n_ambiguous: 6, ambiguous_rate: 0.12 };
  const iso = { n_detected: 48, isolate_top1: { n: 48, contained: 40, success_rate: 40 / 48 } };

  it("reads the ambiguity and isolation blocks when present", () => {
    const m = parseMetrics({ ...good, ambiguity: amb, isolation: iso });
    expect(m?.ambiguity?.ambiguous_rate).toBe(0.12);
    expect(m?.isolation?.isolate_top1.contained).toBe(40);
  });

  it("drops a malformed block instead of failing the page", () => {
    const m = parseMetrics({ ...good, ambiguity: { n_incidents: 5 }, isolation: { n_detected: 1 } });
    expect(m).not.toBeNull();
    expect(m?.ambiguity).toBeUndefined();
    expect(m?.isolation).toBeUndefined();
  });

  it("accepts a file without either block", () => {
    const m = parseMetrics(good);
    expect(m?.ambiguity).toBeUndefined();
    expect(m?.isolation).toBeUndefined();
  });
});
