# Handoff: telemetry — Task 1.4 + Ф4.1 GUI + PyQtGraph-дашборд + merge-анализ

- **Дата:** 2026-07-17
- **Ветки этой сессии:** `feat/telemetry-coherence` (Task 1.4 + Ф4.1), `feat/telemetry-dashboard` (дашборд) — обе локальные, main НЕ тронут
- **Параллельно (второй чат, worktree):** `feat/backend-ctl-hardening` — Phase 0 закрыта, отревьюена (Opus+Fable PASS), ждёт мержа
- **Для:** продолжения в новом чате — **главное решение на входе: порядок мержа в main**

---

## TL;DR

За сессию закрыты: **Task 1.4** (cap-детекция per-process, coherence Фаза 1 полностью), **Ф4.1**
(GUI-контролы телеметрии — шаблонная секция), и **весь план `telemetry-dashboard`** (PyQtGraph:
компонент `TelemetryChart` + системный дашборд + crosshair-читаемость + зум колесом + миграция
спарклайнов). Всё зелёное, qt-smoke-verified. Параллельный второй чат закрыл `backend-ctl-hardening`
Phase 0. **Следующий шаг — мерж в main; порядок проанализирован (см. ниже), ждёт твоего «go».**

---

## Что сделано (коммиты)

### Ветка `feat/telemetry-coherence` (от publish-control)
| Коммит | Что |
|--------|-----|
| `f64a6700` | **Task 1.4** — cap-детекция на адресном per-process пути (вариант «а» перехват в PM: driver → `telemetry.broadcast` с `target`; `_send_child_command`). Reviewer **APPROVE**. ADR-PM-017 Amendment |
| `1fd10930`, `d3db0c65` | Task 1.4 план-закрытие + ниты ревью |
| `6977cb7e`, `5f96f900` | memory dual-write |
| `b8ee3353` | **Ф4.1** — `TelemetryControlsSection` (шаблонная секция вкл/выкл+частота по `GATED_METRICS`), запись через command-result-bridge, `capped_by_throttle` в UI. qt-smoke verified |

### Ветка `feat/telemetry-dashboard` (от coherence) — план `plans/telemetry-dashboard.md` ЗАКРЫТ
| Коммит | Что |
|--------|-----|
| `398263ea` | Ф0 pyqtgraph 0.14.0 (PySide6) + Ф1 `TelemetryChart` (framework, конструкторный, 15 тестов) |
| `c4e8c3ae` | Ф2 дашборд «Все процессы»: серия/процесс, легенда-тумблеры, метрика, live |
| `ff58143e` | Ф2.2 **crosshair + значения серий** (читаемость при разном масштабе) + подпись оси Y |
| `750910a6` | Ф2.3 зум колесом по X + Ф3 миграция спарклайнов на `TelemetryChart` (кастом удалён) |
| `e724b164` | memory dual-write |

**Тесты:** telemetry_chart/29, processes-tab/194, framework 4919 (2 pre-existing Windows app_module
fail — вне скоупа, [[project_app_module_windows_test_debt]]). pyright 0, ruff чист. qt-smoke (dualcam_synth,
порт 9142) — всё рендерится, 0 ошибок в работе.

---

## Merge-анализ (ГЛАВНОЕ для нового чата)

### Топология
```
main (f0968ca8)
 └─ publish-control (+18)
     └─ coherence Фаза 1 … 11dd9dfc  ← ОБЩАЯ БАЗА обеих веток
         ├─ coherence: Task1.4 + Ф4.1 (+15) → dashboard (+6)   ← этот чат
         └─ backend-ctl-hardening (+41)                         ← второй чат (worktree)
```
- **main — прямой предок ОБЕИХ веток.** bctl и телеметрия **независимы** (обе от `11dd9dfc`).
- bctl НЕ содержит Task 1.4 (ответвился ДО него).

### Пересечение и конфликты (проверено `git merge-tree`, эмпирически)
- Пересечённые файлы: `backend_ctl/driver.py`, `docs/claude/memory/MEMORY.md`, `docs/sessions/2026-07-17.md`.
- **`driver.py` сливается ЧИСТО** — правки в разных регионах: мои Task 1.4 на строках 723–794
  (`telemetry_reconfigure`/`telemetry_set`), bctl — ≤537 и ≥827 (connection/request/subscribe/MCP).
- **`MEMORY.md` — чисто.**
- **Единственный реальный конфликт — `docs/sessions/2026-07-17.md`** (авто-лог pre-commit хука
  `append session log`, тривиальный «оставить оба»).

### FF-возможность
- `main` — предок dashboard И bctl → **whoever мёржится первым, входит fast-forward** (без конфликта);
  второй — обычный merge с session-log конфликтом.

### Рекомендация (моя, обоснована выше)
**Гибрид `coherence → bctl → dashboard`:**
1. `coherence` (Task 1.4 reviewed + Ф4.1) → main **FF**.
2. Сигнал второму чату → он мёржит **bctl** (резолвит тривиальный session-log).
3. `dashboard` → main позже, желательно после быстрого ревью (новый pyqtgraph-компонент + dep).

Причина гибрида: в main сперва отревьюенное (Task 1.4 APPROVE + bctl Opus+Fable), а свежий/крупный
дашборд (**self-verified, независимого код-ревью НЕ было**) не смешивается с мержем bctl.

**Альтернатива A (просто):** влить весь `dashboard` FF одним махом, затем bctl. Тоже чисто (merge-tree
доказал), но тащит непроверенный ревьюером дашборд сразу.

### Команды (когда будет «go»)
```bash
# Шаг 1 — coherence в main (FF)
git checkout main && git merge --ff-only feat/telemetry-coherence   # или --no-ff для merge-коммита (стиль репо)
# → сигнал второму чату: "coherence в main"
# Шаг 2 (второй чат): git merge feat/backend-ctl-hardening  → резолв docs/sessions/*.md (оба)
# Шаг 3 — dashboard в main (позже)
git checkout main && git merge --ff-only feat/telemetry-dashboard   # main должен быть предком dashboard
```
> ⚠️ Если между шагами main уедет (влили bctl) — шаг 3 станет обычным merge (session-log конфликт, тривиально).
> Репо использует merge-коммиты (см. `main` log «chore(main): слить …») — можно `--no-ff` для явной точки.

---

## Осталось / бэклог

- **Task 4.2** (план publish-control Фаза 4): ADR «управляемая публикация» + memory. Не сделан.
- **coherence-remediation Фазы 2/3** (фоновый долг когерентности/простоты): boot≡reload, типизация
  `ProcessConfig.telemetry`, персист runtime-дельты, ре-адопция covered-подписок, гигиена ThrottleMiddleware,
  read-model во framework. См. `plans/telemetry-coherence-remediation.md`.
- **Дашборд follow-ups** (по желанию): пороги/алерты, экспорт, несколько Y-осей (задел `SeriesSpec.y_axis`).
- **Зум колесом:** config-уровень применён (`setMouseEnabled x=True/y=False` + `setAutoVisible`), но
  колёсный жест НЕ скриптуется qt-mcp — **проверить вживую руками** (скорость/2D-vs-X/инверсия по вкусу).
- Windows app_module 2 fail — pre-existing, отдельный тикет.

---

## Как продолжить (новый чат)

1. Прочитать этот handoff + `plans/telemetry-dashboard.md` (закрыт) + memory (`project_telemetry_dashboard`,
   `project_telemetry_gui_controls`, `project_telemetry_coherence_remediation`).
2. **Решить порядок мержа** (гибрид / A) и выполнить шаг 1 — я оставил команды выше. main НЕ тронут.
3. Тесты: `.venv/Scripts/python.exe -m pytest <targets> -q` (проектный .venv, [[feedback_always_project_venv]]).
   Полный: `.venv/Scripts/python.exe scripts/run_framework_tests.py`.
4. qt-smoke: `QT_MCP_PROBE=1 .venv/Scripts/python.exe multiprocess_prototype/run.py dualcam_synth` (порт 9142).
   Грабли: выбор процесса в nav — кликать по **viewport** (`qt_scrollarea_viewport`), не рамке QListWidget;
   гасить GUI — точечно по PID ([[feedback_no_global_taskkill]]), `MSYS_NO_PATHCONV=1 taskkill /PID <pid> /T /F`.
5. Коммиты: trailers `Why:`/`Layer:` + `Refs:` (хук отклонит без); pre-commit ruff-format → re-stage.

## Не сметать (чужое / worktree)
- `feat/backend-ctl-hardening` в worktree `../Inspector_bottles_bctl` — второй чат, НЕ трогать.
- Второй чат сам сделает `git merge feat/backend-ctl-hardening` по сигналу.

## Ключевые артефакты
- Компонент: `multiprocess_framework/modules/frontend_module/widgets/telemetry_chart.py` (`TelemetryChart`, `SeriesSpec`)
- Дашборд: `multiprocess_prototype/frontend/widgets/tabs/processes/_system_dashboard.py`
- Контролы Ф4.1: `.../processes/_telemetry_controls.py`
- Планы: `plans/telemetry-dashboard.md` (закрыт), `plans/telemetry-publish-control.md` (Ф4.1 done, 4.2 open),
  `plans/telemetry-coherence-remediation.md` (Фаза 1 done)
