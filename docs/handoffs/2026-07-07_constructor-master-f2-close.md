---
date: 2026-07-07
topic: constructor-master — Ф2 закрыта целиком (2.3 + волны C 2.4∥2.5), merge в main
machine: macOS
branch: main (feat/constructor-f2 влита)
---

## Session goal

Продолжение по handoff `2026-07-07_constructor-master-f2-debugplane.md`: Ф2.3,
волны C 2.4∥2.5, закрытие Ф2 и merge в main. Плюс новая идея владельца
(observability-hub) — зафиксирована.

## Done (всё в git, дерево чистое кроме app.yaml-артефакта лаунчера)

- **Ф2.3 закрыт** (a4d86595): discovery честный — `PluginRegistry.discover`
  `except→debug` заменён на WARNING + персистентный `failed_imports`; новая
  команда `introspect.plugins` + `driver.introspect_plugins` + MCP-инструмент
  (**25**); CAPABILITIES перегенерирован. `ObservableMixin._call_manager`:
  `except: pass` → счётчик `manager_call_failures` + WARNING раз на пару
  (stdlib logging — не через себя, анти-рекурсия). Live-acceptance: сломанный
  plugin.py в Plugins/ → boot → `failed_imports` с SyntaxError через driver ✓.
- **Волны C 2.4∥2.5 закрыты** (двумя параллельными worktree-агентами, merge
  чистый): M-err-1/M-err-2 («камера умирает молча») + 31 `report_error` в 16
  файлах (hot-path с `throttle=30`), 29 легитимных swallow — тег
  `# no-health: <причина>`. **Постоянный AST-гейт**
  `Plugins/tests/test_no_silent_swallows.py`: каждый except в Plugins/ —
  report_error | raise | тег; регресс невозможен по построению.
- **`SubPluginContext.health`** (enabling-правка 2.5): log-only fallback +
  проброс родительского reporter'а — sub-плагины больше не падают на error-пути.
- **Ф2 вмержена в main** по решению владельца («давай»); гейт перед merge:
  полный прогон 3536 passed + Plugins 749 + live 5/5 (boot + breaker).
- **Идея владельца зафиксирована**: `plans/2026-07-06_constructor-master/
  observability-hub-idea.md` — фасад модуля с каналами err/log/stats через
  слоты ObservableMixin + IChannel (реализуемо без правок внутри модулей).
  Триаж на ближайшем гейте; слот Ф5/Ф7.

## What worked well / оркестрация

- **Формат «2 агента ∥ в worktree с дизъюнктными зонами» отработал чисто**
  (в отличие от инцидента «двух инстансов» Ф2.2): зоны Plugins/sources vs
  остальное, live-эксклюзив у одного, skip-список в гейте как шов согласования
  (снят при merge). Оба агента сами сделали ff устаревшей базы worktree до
  актуального HEAD — иначе не было бы health-API.
- Уроков-инцидентов в этой сессии нет.

## Key decisions made

- Конвенция волны C: легитимный swallow обязан нести тег `# no-health: <причина>`
  — enforced постоянным AST-гейтом (не разовым grep'ом).
- 2.6 (JSONL-sink) остаётся опциональной — Ф2 закрыта без неё.
- app.yaml — по-прежнему артефакт лаунчера, в коммиты не берём.

## Next step

1. **Ф3 Supervisor v2** (новая ветка `feat/constructor-f3` через /plan-конвенцию).
   Внутренний порядок ЖЁСТКИЙ: 3.1 routing-epoch / 3.2 self-reported ready /
   3.5 wire-статусы — строго ДО 3.8 (GATE G1, включение RestartPolicy — за
   владельцем). Параллелимо: 3.3 guard system-очереди, 3.4 M-race-1.
2. Триаж observability-hub-idea.md на ближайшем гейте.
3. Hardware-gated хвосты: FPS-baseline, «выдернуть камеру физически» (стенд).

## Files/refs

- Ветки: main = всё (Ф0–Ф2 + трек F + debug-plane); feat/constructor-f2 можно удалить.
- Гейт: `Plugins/tests/test_no_silent_swallows.py`.
- Идеи: observability-hub-idea.md, debug-plane-idea.md, capability-manifest-idea.md.
- ADR: PM-010 (health), PM-011 (breaker).
- Память: docs/claude/memory/project_constructor_master_progress.md (+локальная).
