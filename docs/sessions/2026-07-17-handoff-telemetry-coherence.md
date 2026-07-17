# Handoff: telemetry-coherence — ревью телеметрии + Фаза 1 remediation

- **Дата:** 2026-07-17
- **Ветка:** `feat/telemetry-coherence` (от `feat/telemetry-publish-control`, та — от `main`)
- **Для:** продолжения в новом чате
- **Статус:** Фаза 1 remediation ЗАКРЫТА и чистая; дальше — **Task 1.4 → Фаза 4 GUI** (рекомендация)

---

## TL;DR

Отревьюили два закрытых плана телеметрии (`gui-telemetry-read-model` + `telemetry-publish-control`)
трёхуровневым пайплайном (Sonnet-флот 5 подсистем → Opus кросс-срез → Fable архитектурный вердикт
**24→42/60**). Все находки исправлены или заведены задачами. Fable написал план устранения
`plans/telemetry-coherence-remediation.md`; **Фаза 1 (3 задачи + ниты) выполнена, зелёная,
заревьюена**. Осталась Task 1.4 (блокер per-process GUI-крутилки) + Фазы 2/3 remediation.

## Рекомендованный следующий шаг

**Task 1.4 (Cap-детекция на адресном per-process пути) → затем Фаза 4 GUI плана telemetry-publish-control.**
Причина: цель — GUI-управление телеметрией; per-process крутилка частоты поверх молчаливого cap (finding #1)
воспроизвела бы ровно тот баг, что чинили. Task 1.4 небольшая, разблокирует полноценный GUI.
Broadcast-путь (`telemetry_set("all", …)`) уже покрыт — если нужен только он, Фаза 4 стартует и без Task 1.4.

Приоритет владельца: **продукт > движок** (memory `project_priority_product_over_engine`). Фазы 2/3
remediation — фоновый долг когерентности/простоты, могут подождать.

---

## Что сделано в этой сессии

### 1. Ревью-пайплайн (3 уровня)
- **Sonnet-флот** (5 подсистем + адверсариальная верификация): 3 medium-находки → все исправлены.
- **Opus кросс-срез** (межподсистемные стыки): 1 medium + 2 low → A/C исправлены, B в follow-up.
- **Fable архитектурный вердикт**: **24→42/60** по 6 осям; 7 находок (A HIGH, D design-critical); 4 рычага.
  Вердикт сохранён: `.claude/agent-memory/investigator/project_telemetry_branch_verdict.md`.

### 2. Фиксы ревью (коммит `9b9dbf1a`)
generation-guard графика · ring по wall-окну · `override is None` (per-process `telemetry:{}`) ·
try/except throttle-ветки broadcast · `events()` расщеплён (pyright) · +6 тестов.

### 3. Фаза 1 remediation (план `telemetry-coherence-remediation.md`)
| Task | Суть | Коммит | Ревью |
|------|------|--------|-------|
| 1.1 | delta-семантика `mode: merge\|replace` (обе плоскости); оживил `update_rule`/`remove_rule` | `92d6f6f6` | APPROVE |
| 1.2 | `publish.tick_sec` — тик в контракте (находка D); **ADR-PM-016** (вариант а: один heartbeat-воркер `min(interval, tick)`, liveness-сообщение по time-gate) | `03449743` | APPROVE (liveness-инвариант надёжен) |
| 1.3 | троттл=IPC-страховка, publisher=авторитет частоты; дефолт троттла 0.05с; `capped_by_throttle`-флаг (auto-relax отвергнут); **ADR-PM-017** | `173f5ff4` | APPROVE-с-замечаниями |
| ниты | docstring `telemetry_set` · порядок cap-детекции · сужение ADR-инварианта · Task 1.4 заведена · system.yaml оговорка | `f2151d6b`, `06dfe374` | — |

**Regression:** framework **4909 passed** (+53 от Фазы 1), prototype backend 197 passed.
Пре-existing (НЕ регресс): 2 фейла Windows app_module (`test_manifest_store` os.replace WinError5,
`test_minimal_app_smoke` endswith slash) — memory `project_app_module_windows_test_debt`.

---

## Ключевая архитектура (что важно знать перед продолжением)

**Три частотные плоскости** (после Фазы 1 — согласованы):
1. **heartbeat tick** (`ProcessHeartbeat`): теперь `min(heartbeat_interval, publish.tick_sec)` — управляем
   контрактом (Task 1.2). Раньше был захардкожен 5с и доминировал молча (находка D).
2. **publisher-gate** (per-метрика `interval_sec`, `enabled`): **единственный авторитет частоты**.
3. **центральный ThrottleMiddleware** (оркестратор): **только IPC-страховка**, дефолт мягкий 0.05с
   (не режет publisher). При ручном строгом правиле поднятие частоты помечается `capped_by_throttle`
   (broadcast-путь). ADR-PM-017.

**Контракт реконфигурации:** единая точка `apply_telemetry_reconfigure(section, *, mode)`; `mode` едет
в `data["telemetry_mode"]` (сосед `publish`/`throttle`), на проводе только при `merge` (replace=бит-в-бит).
Неизвестный `mode` → error-dict → `success=False` во всех 3 хендлерах.

---

## Осталось в плане remediation

- **Task 1.4** — Cap-детекция на адресном per-process пути (**Фаза 1, БЛОКЕР per-process GUI-крутилки**). Заведена, не реализована. Senior/teamlead.
- **Фаза 2** (когерентность): 2.1 boot≡reload `throttle:{}` (B) · 2.2 `config.reload` сохраняет per-process overlay (C) · 2.3 валидация `metrics`-ключей против GATED_METRICS (E). Middle+/developer.
- **Фаза 3** (гигиена+простота): 3.1 типизировать `ProcessConfig.telemetry` · 3.2 персист runtime-дельты через hot-swap + watcher-fan-out (residual #7) · 3.3 ре-адопция covered-подписок (F) · 3.4 гигиена ThrottleMiddleware (G) · 3.5 read-model во `frontend_module` + вырезать legacy (vector #4).

Известные follow-ups размещены в плане (таблица «Уже известные follow-ups»).

---

## Как продолжить (в новом чате)

1. `git checkout feat/telemetry-coherence` (уже на ней).
2. Прочитать `plans/telemetry-coherence-remediation.md` (Task 1.4 + Фазы 2/3) и этот handoff.
3. Модель исполнения: **фазы последовательно, task-by-task, ревью-гейт после каждой** (внутрифазовый
   параллелизм рискован — overlap `telemetry_reload.py`/`process_heartbeat.py` + коммит-гонка,
   memory `feedback_parallel_agents_commit_race`).
4. Прогон тестов: `.venv/Scripts/python.exe -m pytest <targets> -q` (проектный .venv обязателен,
   memory `feedback_always_project_venv`). Полный: `.venv/Scripts/python.exe scripts/run_framework_tests.py`.
5. Коммиты: trailers `Why:`/`Layer:` + `Refs: plans/telemetry-coherence-remediation.md` (хук отклонит без);
   pre-commit ruff-format → re-stage + повтор (memory `feedback_commit_msg_format`).
6. Незакоммичены (чужое, не сметать): `.claude/agent-memory/investigator/*`, `plans/backend-ctl-framework-module.md`.

## Пуш / merge
Не пушили. Ветка локальная. `f75d77b1` и ниже — работа telemetry-publish-control (до этой сессии).
Эта сессия: `9b9dbf1a`..`06dfe374` (9 коммитов).
