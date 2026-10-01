---
name: node-page-harness-blind-to-browser-defaults
description: page_offline.mjs (node:vm) cannot see browser default actions — focus, Space pressing a focused button, scroll; a live Chrome pass via Claude in Chrome found B1 that 35 green tests and 3 reviews missed (1.3h-b, 2026-09-29)
metadata:
  type: feedback
---

Before accepting a pult_web page change that handles pointer/keyboard, run it once in real Chrome through
Claude in Chrome — the node:vm harness executes the page script but none of the browser's default actions.

**Why:** line-sim 1.3h-b canvas — 35 green harness tests, lead's break-injection and three reviews, yet the
first real-Chrome pass found B1: `pointerdown` + `preventDefault` suppressed the focus change, focus stayed
on the last clicked form button, and Space (pan) made the browser press it ("Отмена" fired; "Сохранить" would
have written the preset). The harness has no focus model and no "Space activates focused button". The same
pass also showed a tool artefact to discount: the extension's `scroll` action scrolls the page itself even
when the page's wheel event is `defaultPrevented` — check `defaultPrevented`/`isTrusted` before calling it a bug.

**How to apply:**
- In the VS Code extension Claude in Chrome is not a toggle: the user must mention `@browser` in a message
  (panel `/chrome` shows "Disabled in this session" until then). CLI: `claude --chrome`.
- Checklist for a canvas/editor page: selection, drag with DPR ≠ 1, handles, undo, wheel, Space and arrows
  with focus on a previously clicked BUTTON, console errors, reload to discard edits (never press Save).
- Log trusted events + `document.activeElement` via `javascript_tool`; numbers, not screenshots alone.
- Tool artefacts (1.3h-c, 2026-09-29): `form_input` on a `<select>` leaves the native popup open — the next click
  and keys are eaten (looked like "button does nothing"); set `select.value` via JS instead. A button that adds a
  form row shifts every control below it — re-screenshot before the next coordinate click (two misclicks landed
  in a name field and typed a space into it).
- Probe typed error codes through the LIVE stand with curl, not only the route tests: 1.3h-c found every
  `preset.*` refusal arriving as HTTP 504 because `DeviceHubClient._normalize_response` drops `code` (R-4) —
  route tests were green on a fake client.
- Related: [[injection-scripts-on-committed-code]].
