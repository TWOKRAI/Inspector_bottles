---
name: switch-live-survivor
description: live-тест выжившего-отправителя после topology.apply — использовать protected `devices`, НЕ camera_0 (FullReplacePlanner + strip_gui)
metadata:
  type: project
---

Для live-теста, где нужен **процесс-отправитель, ПЕРЕЖИВШИЙ `topology.apply`**,
отправителем бери **`devices`** (protected, `base.yaml`, DeviceHubPlugin,
GenericProcessApp — без Qt/железа), а не `camera_0`.

**Why:** прототип использует ТОЛЬКО `FullReplacePlanner`
(`multiprocess_prototype/backend/assembly/planner.py`) — любой `topology.apply`
сносит и пересоздаёт ВСЕ non-protected процессы. Выживают лишь protected. В
headless (`BackendHarness`) `gui` вырезан `strip_gui`, поэтому единственный
наблюдаемый выживший ребёнок-отправитель — `devices`. `camera_0` non-protected →
пересоздаётся с свежими очередями → стейл-ссылку не воспроизводит (тест был бы
зелёным на main). IncrementalPlanner (где выживают нетронутые процессы) в
планах, но пока не существует.

**How to apply:** любой routing/switch live-сценарий «выживший → пересозданный
сосед» строй на `devices`→`<pipeline-процесс>`. Для `process.restart` (single-
process) выживает кто угодно — restart сносит только целевой процесс. Изолируй
switch- и restart-тесты РАЗНЫМИ бэкендами: switch необратимо роняет очередь
соседа у отправителя (тот навсегда доставляет через hub-relay), пачкая restart-
пробу `relayed_to_hub`. Порты live-тестов заняты: 8765/66/67/70/74/76/78/79/81
(8781 — Ф3.2 test_self_reported_ready_live), 8782/8784 — RS-2/RS-3
test_switch_honest_state_live (switch/shutdown), 8783 — test_fault_injection_live.
Switch-тест «region_pipeline → line_filter_inspect»: оба рецепта бутятся headless
(source camera_0 + CapturePlugin). После RS-2 `processes.<name>.pid`/`.config`
публикуются в state на старте (pid читается из дерева, не только introspect).
Shutdown-выживших ловить psutil'ом: `harness._orchestrator_pid()` →
`children(recursive=True)` до `harness.stop()`, потом сверять живость.
См. [[commit-trailers-single-line]] для коммитов.
