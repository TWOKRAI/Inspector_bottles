# Handoff 2026-07-09 — Pre-Ф5 hardening закрыт, честное ревью Ф0-Ф4, next Ф5

> Читать вместе с памятью `project_constructor_master_progress.md` (LATEST-блок) и `plans/2026-07-06_constructor-master/plan.md` (H-блок + Ф5).

## Где мы

- **main @ `b083b086`** (merge Pre-Ф5 hardening). В main: Ф0-Ф4.2 + Pre-Ф5 hardening (H1-H8).
- Ветка `fix/pre-f5-hardening` влита (`--no-ff`), можно удалить.
- `sentrux check` exit **0**; fw **3673** / proto **2932** passed, 0 красных.

## Честное ревью Ф0-Ф4 (36 агентов, 19/21 CONFIRMED скептиком)

- **Направление ВЕРНОЕ**, инверсий в порядке фаз нет. Две несущие ставки доказали эффект конкретными находками: (1) no-rewrite при 0 циклов; (2) tooling-first (backend_ctl первым) — verify-probe и fault-injection вскрыли латентные баги в момент их существования.
- **Fault-isolation ~70% доставлен** (control-plane + супервизия — enforced через 2 постоянных AST-гейта + live fault-injection); data-plane (torn-frame/QoS) — by-design в Ф7.
- **Числовые цели НЕ достигнуты:** quality 7174→7074, depth 0.615→0.571 (пробил порог), modularity flat. Единственная удержанная — 0 import-циклов.
- Полный список находок — в памяти + коммит-истории ветки.

## Что починено (H1-H8, все с регресс-тестами)

| # | Механизм | Файл |
|---|---|---|
| H1 | breaker прод-путь: `record_success` только если `error_count` не вырос за итерацию (раньше «съедал» внутренний `report_error` флагманов) | `process_module/generic/source_producer.py` |
| H2 | restart: `_bump_incarnation` ДО `create_and_register` (иначе stale-incarnation → fence false-positive) | `process_manager_module/process/process_manager_process.py` |
| H3 | recovery-watchdog `_check_recovery_timeouts`: тихий провал рестарта (path A снят с реестра / path B send не ушёл) → ретрай/give-up | `process_manager_module/monitor/process_monitor.py` |
| H4 | health-based restart `_maybe_health_restart` за флагом **`FW_HEALTH_RESTART`** (default off), гейт `_given_up` от шторма; `RestartPolicy.restart_on_health_failed` | `process_monitor.py`, `core/restart_policy.py` |
| H5 | контракты `MessageContract.params_in_data` → валидация `message["data"]` (была инертна) | `message_module/contracts/registry.py`, `process_module/commands/builtin_commands.py` |
| H6 | KILL Operation_crop −858 LOC (G0-K9) | `Services/Operation_crop/` (удалён) |
| H7 | KILL topology-editor-виджет −722 LOC (G0-K8), **presenter сохранён** | `frontend/widgets/topology/` |
| — | бонус: Pipeline edge-delete (удаление одного провода, v1-паритет) | `widgets/tabs/pipeline/{tab,presenter,mutations}.py` |

## Уроки/ловушки для нового чата

1. **kill'ы изолированных мёртвых листьев НЕ двигают метрики** (modularity 5665→5667, depth 0). G0-план ошибочно ждал «+modularity». Реальный фикс depth — структурный (Ф5.18), не удаление.
2. **depth-долг:** `min_depth` 0.60→**0.57** в `.sentrux/rules.toml` (принято владельцем, датировано; возврат 0.65 в Ф8 H.5). Реальный фикс — **Ф5.18** (сплющить глубокие leaf-пакеты god-split: `pipeline/graph`, `inspector/`, `forms/factory/`).
3. **commit-trailers строго однострочные** — `Why:`/`Layer:` на ОДНОЙ строке, иначе hook отвергает.
4. **merge в main:** `git merge --no-ff -F <файл>` (не `-F -`); protect-branch блокирует `git commit` на main, но не `git merge`.
5. **бэкенд тестировать через driver** (backend_ctl), не qt-mcp; hardware-рецепты (phone_sketch/hikvision) не бутятся headless — валидировать через assemble + синтетический `region_pipeline`.

## NEXT — Ф5 путь B (рекомендация аудита)

Ф5 **не готова целиком**: в main влита только 4.2; recipe/manifest-ядро **4.5→4.6→4.7** блокирует carve `launch.py` (5.1-5.3, 5.11-5.13). Стартовать на НЕзаблокированном подмножестве:

- **ObservabilityHub 5.15-5.17** (примитивы `IChannel`/`IBufferStrategy` готовы; hot-path adoption всё равно отложен в Ф7) — максимум видимой ценности.
- **carve E1/E2/E6** (5.4/5.5/5.7 — чистые переносы без `launch.py`).
- **5.6a** diff-отчёт 4 механизмов форм → GATE G2.
- **Ф5.18** depth-reduction.

**ДО старта Ф5:** (1) снять `session_start` baseline Ф5; (2) прогнать полный pytest на main; (3) явным `docs(plans)`-коммитом решить scope открытой Ф4 (что переносится/дефёрится) — чтобы «Ф4 закрыта» стало правдой.

**Recipe/manifest-carve (5.1-5.3, 5.11-5.13) — отложить** до приземления 4.5/4.6/4.7.
