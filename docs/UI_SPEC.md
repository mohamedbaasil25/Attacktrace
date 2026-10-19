# AttackTrace UI redesign spec (Phase 15, Part 0)

Frontend visuals only. No backend/contract/behaviour change. Branding: **TechWizards** (not "AL
Tech Falcon" — confirmed with the owner; this overrides §3/§4.12 of the source prompt, everything
else in that prompt stands).

## Audit: current state and concrete problems

Screenshots: `submission/evidence/ui_before/01-idle.png` through `08-metrics.png` (1440×900, SIM,
captured live via `submission/tools/capture_ui_before.mjs`).

| # | Problem | Evidence |
|---|---|---|
| 1 | **Runtime network dependency on Google Fonts** — violates the new hard rule "no external network at runtime." Must self-host or fall back to system fonts. | `frontend/index.html:6-7` loads `fonts.googleapis.com` |
| 2 | **No hero treatment for the twin.** Equal visual weight to the console; a large unused black canvas in idle state (nothing below the equipment row down to the panel edge). | `01-idle.png` |
| 3 | **Status shown by colour + a tiny dot only**, not the shape language (circle/triangle/diamond/ring+crosshair) the spec requires. Every node badge looks the same shape regardless of status. | `01-idle.png`, `04-incident-open.png` |
| 4 | **Flat elevation.** Panels, cards and the canvas background are near-identical dark tones; no bg-0/1/2/3 step is visually legible. | all |
| 5 | **No confidence ring**, only a 3-segment bar (keep the bar, it's good; add the ring per spec). | `04-incident-open.png` |
| 6 | **Path shown as inline arrow-text**, not the vertical connected-dot stepper the spec calls for. | `04-incident-open.png` |
| 7 | **Top bar is minimal text buttons**, no segmented control with sliding indicator, no logo mark, no source pill (state/latency/rate as one legible unit), no About popover. | all |
| 8 | **Buttons have one visual treatment** (flat fill); no clear primary/secondary/disabled hierarchy beyond colour alone. | `01-idle.png` |
| 9 | **Metrics KPI cards are already a reasonable foundation** (big mono numbers, baseline deltas) — keep the bones, add delta arrows/chips, `n=`/CI, definition tooltips. | `08-metrics.png` |
| 10 | **Contrast unmeasured.** No `scripts/check_contrast.ts` exists yet; several text-3-on-bg-1 pairs look borderline on inspection. | n/a — Part A deliverable |
| 11 | Split-view mini-twin text is legible (Phase 14 C4 already fixed this: 12.2–19.7px across required resolutions) — **do not regress it** during the twin rebuild. | `05-split.png` |

## 1. Tokens

Adopting the source prompt's token table as-is (surfaces, borders, text, accent, status colours,
radius, 4-pt space scale, elevation, motion durations, type scale) in `frontend/src/styles/tokens.css`
and the Tailwind theme. One change: every "AL Tech Falcon" string becomes **TechWizards**.
Status shapes: normal = filled circle + check, suspect = triangle, affected = diamond, origin =
ring + crosshair, quality-fault = slashed square — each also carries a text label, never colour alone.
`scripts/check_contrast.ts` computes WCAG ratios for every text/surface and status/surface pair
from the tokens; fails under 4.5:1 (text ≤18px) or 3:1 (icons/large text). Tokens get adjusted
until it passes, and the pass table is reported in Part A.

## 2. Layout (primary 1440×900)

Top bar (56px) → 3-column body (attack console 280px | twin/graph/split stage, fluid | incident
360px) → timeline (168px). 12-column grid, 16px gutters, 8/16/24 spacing only. At 1280px: console
collapses to an icon rail, incident panel narrows to 320px, timeline drops to 2 sparklines. At
1920px: stage grows, panels stay fixed-width, centre content caps at 1400px. No horizontal scroll
≥1280px; below 1280 show a `Best at 1280px+` notice, stay usable to 1024 (incident panel stacks
under the stage).

## 3. Components (full detail: source prompt §4, adopted as-is except branding)

Top bar · digital twin (P&ID rebuild: dot grid, animated tank fill + ghost-truth marker + Δ badge,
flow-animated pipes, rotating pumps, bow-tie valves, instrument-bubble sensors, PLC chips with
dashed control-loop lines, propagation pulse along the path, hover/focus tooltips, fully vector) ·
attack console (segmented scenario buttons with MITRE chips, grouped target select, magnitude
slider, Launch with loading/cooldown, compact node list) · incident panel (status header chip +
timer, origin card with confidence ring + breakdown bar + ambiguous handling, path stepper, action
+ Isolate with state machine, MITRE/report/baseline-count meta row, impact meters) · stage tabs
(Twin/Graph/Split, 200ms crossfade) · timeline (scrubber, onset markers, 4 sparklines, shared
crosshair) · metrics page (mode tabs, KPI cards with delta chips + n/CI + definition tooltips, one
grouped bar chart in a tokens-derived ECharts theme) · global states (skeletons, No signal with
retry countdown, Calibrating ring, empty states, error toasts, no modal dialogs) · copy rules
(≤3-word labels, sentence case, mono tabular numbers, ≤12-word tooltips) · motion (120–320ms,
`prefers-reduced-motion` disables flow/spin/pulse/tickers) · accessibility (visible focus ring,
full keyboard path, `aria-live=polite` incident announcements, ≥32px hit targets).

## 4. Engineering

`features/{twin,incident,console,timeline,graph,split,metrics}` + `components/ui` primitives
(Button, Chip, Card, Tooltip, SegmentedControl, Toast, Meter, Ring, Skeleton), no component over
200 lines. Tokens only — no hard-coded colours/spacing (grep check in CI). Existing Zustand shape
unchanged; view models via selectors; twin animates via ref/CSS-variable updates, React state only
for discrete status changes. One ECharts theme file; sparklines hand-drawn SVG. Bundle size
reported before/after; investigate >25% growth.

## 5. Dependency requests (asking once, per rule 4)

1. **`@fontsource-variable/inter` + `@fontsource-variable/jetbrains-mono`** — self-hosts the two
   fonts already in use, removing the Google Fonts runtime call (problem #1 above). Without this:
   fall back to the system font stack.
2. **`@axe-core/playwright`** — automated WCAG checks on `/` and `/metrics` in SIM and LIVE.
   Without this: a manual contrast/keyboard pass only, no automated axe scan.

## 6. Verification plan (Part F)

eslint/tsc/vitest(127+)/playwright(6)/contrast script/hard-coded-colour grep/axe(if approved) all
green · before/after screenshots at 1280×800, 1366×768, 1440×900, 1920×1080 across the 14 listed
states · critique rubric (1–5, honest) on hierarchy/density/consistency/polish/clarity · render
time per tick + animation frame rate + bundle size · zero console errors across a full SIM and LIVE
run.

## 7. Future work: multi-incident view (sketch, not implemented)

The whole interface — `IncidentPanel`, the status chip, the twin's origin/affected highlighting —
assumes exactly one active incident at a time. That's a known gap from the UX evaluation: a real
adversary's standard move is a loud decoy attack drawing attention while a second, quieter one
proceeds elsewhere, and the current design has no answer for that case. This section sketches one,
without committing to building it.

**Triage list.** When more than one incident is open, `IncidentPanel` would show a compact list
instead of jumping straight to detail: one row per incident, each carrying its status chip, origin
id, confidence, and elapsed time — the same vocabulary already used in the single-incident header,
just repeated per row. Rows would sort by severity first (origin confidence descending, Ambiguous
incidents pinned near the top rather than buried), then by detection time. This mirrors how the
existing `NodeScores` list already handles "many similar rows, one glance each" — the same compact
row pattern, not a new one.

**Opening a row.** Clicking a triage row would swap the panel into today's existing single-incident
`Details` view (Ring, breakdown bar, path stepper, Isolate, Reveal — unchanged) for that incident,
with a back affordance to return to the triage list. The single-incident view doesn't need to
change at all; it just stops being the *only* state the panel can be in.

**Twin and graph.** The digital twin and process graph currently highlight one incident's
origin/path. With several open, they'd need to either highlight whichever incident is selected in
the triage list (simplest, consistent with "detail view follows the list"), or layer multiple
origin rings with a legend — the former is the safer default and should be tried first.

This is a design sketch responding to a named gap, not scheduled work — no implementation estimate
is given here, and it should be revisited once there's a concrete need (e.g. before any multi-site
or longer-running deployment, where concurrent incidents become likely rather than hypothetical).

### 7.1 Status: the frontend above is built; the backend admission rule has a known limitation

The triage list, drill-down and twin/graph-follows-selection behavior sketched above are
implemented (`IncidentTriageList.tsx`, `IncidentPanel.tsx`, `resolveSelected()` in `lib/incident.ts`)
and backed by an additive `LiveMessage.incidents: Incident[]` field (`backend/app/schemas.py`).
`Engine._open` (`backend/app/engine.py`, SIM and LIVE only — `engine_hai.py` is untouched) is a
dict keyed by incident id, and a new incident's admission is decided by `_fold_target`: a node
whose own per-node EWMA score sustains past its threshold (`PERSIST` samples) either folds into an
already-open incident or opens a new one, based on `settings.zone_hops` — the number of undirected
P&ID hops from a node already verified to belong to that incident (seeded with the triggering node,
grown one verified hop at a time as the chain is independently confirmed).

**Known limitation, found during hands-on validation of the decoy-plus-quiet-attack scenario this
sketch was written for:** on SIM's 9-node plant, pure topological (hop-count) distance cannot
separate two concurrent incidents, at any `zone_hops` setting. The plant is small and tightly
coupled — a single real attack's own downstream propagation legitimately reaches most of the plant
within a few seconds, each hop independently crossing its own node threshold along the way, so by
the time a second, physically distant attack starts, the first incident's verified footprint has
already grown to cover the second attack's target. Testing confirmed both directions of failure:
`zone_hops=2` and `zone_hops=1` both let the first incident's chain walk far enough to absorb a
second attack launched up to 20s later; `zone_hops=0` broke the opposite way, splitting a *single*
attack into as many as six spurious incidents, since nothing but the exact triggering node could
ever fold into an existing one. There is no `zone_hops` value on this topology that keeps one real
attack cohesive while treating a second, distant one as separate.

**What this means for production work:** separating concurrent incidents on a tightly-coupled plant
needs a temporal/causality-aware admission rule, not a static graph-hop radius — for example,
gating admission on whether an incident's verified footprint is still actively growing (a
quiet incident shouldn't keep absorbing nearby alerts indefinitely), or on whether a new node's
deviation is better explained as a consequence of the already-open incident's own ground truth than
as an independent cause. That is deliberately **not** attempted here: the project is in feature
freeze, and a causality-aware admission rule is a meaningfully larger piece of work than this
sketch's scope. `zone_hops` (`backend/app/config.py`) stays as a documented, tunable heuristic — it
remains correct at preventing a single attack's own propagation from being mistaken for several
(the regression it was built to avoid; see `backend/tests/test_multi_incident.py`), just not
sufficient, on this plant, to demonstrate genuinely concurrent, unrelated incidents. That
capability is more naturally demonstrable on a less tightly-coupled topology, such as HAI's
multi-process (P1/P2/P3) layout, which was explicitly left out of this phase's scope.
