---
name: gui-constructor-layers-2026-09-26
description: "Owner's decision 2026-09-26 on the GUI constructor — framework = constructor (shell, connections, widget contract, layout), Services = application slices with widget packs, prototype = thin inspection layer assembled via recipe topology; reference apps examples/minimal_app (exists) + examples/minimal_gui (to create); unit = widget, windows belong to the shell (T4.1 Р-E flipped)."
metadata:
  node_type: memory
  type: project
  last-verified: 2026-09-26
---

Owner, 2026-09-26: the front is built by a constructor from widgets and tabs; the base gives windows,
tabs and the backend link; widgets are placed into windows, talk to each other and to the backend,
and can be moved between windows quickly. The framework keeps "a constructor from modules";
`Services` holds ready application blocks (the app "like the prototype, but improved") and the Pult;
the prototype is a thin layer that binds framework + services and builds the inspection app through
recipe topology. The prototype is the first consumer; future ones may come from another domain.
Reference apps: backend `examples/minimal_app` (exists, Ф5.11–5.13), front `examples/minimal_gui`
(to create; zero imports of prototype/Services/Plugins, headless CI-smoke against minimal_app).

Recorded in `plans/frontend-constructor/constructor-layers.md`; banner in `gui-bootstrap-design.md`
(T4.1 Р-E flipped: windows belong to the shell; `GuiAppSpec` = widget catalog + default layout;
`GuiHostWindow` moves up to gui-service 1.4; interim `inspector.classic` = whole MainWindow as one widget).

**Why:** the owner wants a universal architecture where a second-domain consumer needs no copy from the
prototype. Gen-1 of `frontend_module` (WidgetRegistry/WindowRegistry/layout_composer) was built upfront
and has 0 consumers — so mechanisms enter the framework only when two consumers need them
(inspection + `apps/line_sim` or `examples/*`).

**How to apply:** when adding GUI code, ask which layer it belongs to; nothing domain-specific in
`frontend_module`; widgets reach the outside only through the widget context (state glob / command
with reply / frames / ui bus), never reference another widget. `minimal_gui` building without the
prototype is the measurable debt counter. Open, not decided: where the Pult program lives (owner said
`Services`, recommendation = runnable shell in the framework + `apps/pult` as config); the name "Пульт"
is taken three times (`Services/control_panel`, `apps/pult`, `Plugins/sim/pult_web`). Related:
[[gui-services-composition-2026-09-23]], [[work-order-2026-09-22-line-sim-then-pult]].
