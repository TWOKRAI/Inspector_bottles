---
name: angle-boundary-rounds-outward-at-raw-precision
description: "exact-degree sector boundary computed via atan2 from raw x0.1mm ints can round to the wrong side of the boundary — use a small margin, not the literal value / граница угла сектора, округление регистров, тестовая фикстура"
module: [services/robot_comm]
mechanism: [fixtures, test-assertions]
role: tester
metadata:
  type: feedback
---

When constructing a "just inside the boundary" test point for an angular sector
check (e.g. `ang_min <= atan2(y,x) <= ang_max`), computing `x = r*cos(ang_min)`,
`y = r*sin(ang_min)` and rounding to the register's raw precision (×0.1mm ints)
does NOT reliably land back exactly on `ang_min` — the rounding can push the
recomputed `atan2(y_rounded, x_rounded)` to either side.

Measured on T2.2 (robot-protocol-v2), r=300mm, ang_min=-165°: the literal
boundary point rounds to raw `(-2898, -776)`, whose actual angle is
`-165.0095°` — OUTSIDE the valid sector, even though the intent was "accept".
A test asserting ACK there would have been silently wrong (pinning a
non-existent contract, or worse, becoming a flaky RED/GREEN depending on the
implementation's own rounding).

**Fix:** don't use the boundary value itself for the "accept" twin. Use a
margin (e.g. ±0.5°) large enough that register rounding (±0.05° at these
radii) can't flip the side, and verify numerically (`atan2` on the *rounded*
raw ints, not the float inputs) before hardcoding the literal in the test.
This weakens boundary precision slightly (doesn't prove exact-0.1mm
inclusivity) but avoids a self-contradicting fixture.

**How to apply:** any test that derives register-precision (raw ×scale int)
fixtures from a trigonometric or otherwise non-linear formula (angle, but also
things like arc-length or projected distance) — always recompute the "true"
value from the ROUNDED raw inputs, not the float the formula produced, before
asserting the expected accept/reject side. Applies beyond this project to any
fixed-point register protocol with angular/trig checks. See also
[[feedback_red_without_interface_needs_one_named_guessed_hook]] for the
broader pattern of flagging assumptions explicitly in the tester report
instead of silently picking one.
