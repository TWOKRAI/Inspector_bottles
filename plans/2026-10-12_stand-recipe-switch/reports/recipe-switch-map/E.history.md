# Срез E — история и замысел горячей смены рецепта (Explore/haiku, 2026-10-13)

Сырой отчёт агента-разведчика для схемы `docs/maps/recipe-switch.md`.

## Ответ
Смена задумана как транзакция `topology.apply` в PM: параллельный стоп, пересборка тем же конвейером, что и boot, откат тем же конвейером, барьер готовности по `ready_event`, debounce. Большая часть сделана в июне–июле 2026. Не доделано: доставка кадров после switch (hot-swap Task 7, развилка A/B не записана). Владение активацией решено в ADR-RCP-007 (бэкенд), но GUI до сих пор шлёт `topology.apply` напрямую; 1b.3 заморожена решением О-16. Поправка к плану: constructor-master 4.9 DONE (2026-07-11), DEFERRED только 4.10.

## 1. Хронология
- 2026-06-06 `eb6f15754`, `d78414741`, `5cd231929`: hot-swap — параллельный стоп, `release_process_memory`, трансформация proc_dict, debounce. `plans/_archive/2026-06-06_replace-blueprint-hotswap.md` закончен открытым Task 7 (камера не инициализируется, кадры не текут); развилка A (доделать hot-swap) / B (чистый рестарт boot-путём, рекомендация плана) — решение не записано.
- 2026-06-07 `362d16df3` TopologyManager, `6b1b140ee` транзакция `PM.apply_topology`, `e8092b0d7` FullReplacePlanner, `2407f5ac7` `replace_blueprint` → `apply_topology`, `5eb98b8ce` снят алиас `blueprint.replace`, `7a845d256` rollback сносит частично созданное.
- 2026-07-04 `plans/_archive/2026-07-04_topology-switch-hardening.md` (DONE): `1e886e50c` откат тем же 5-фазным конвейером, `fcf6dacdb` stop_many с подтверждением смерти, `24fb4f8d5` барьер готовности, `d73209dce` settle 2 с → 0.5 с.
- 2026-07-08 ADR-PMM-010 (routing epoch), ADR-PMM-011 (ready через mp.Event), ADR-PMM-012 (wire re-issue `17e11800a`).
- 2026-07-11 constructor-master: 4.9 DONE (`ccf82606`), 4.10 DEFERRED (`plans/2026-07-06_constructor-master/plan.md:445`).
- 2026-07-13 `cb003c46f`, `1b9f30a6a` RS-2/RS-3: честный громкий switch, `live_protected`.
- 2026-07-26 `6ef985e73`: снят каскад `process.hot_add/hot_remove` (приёмника в PM нет); живой аналог — `topology.apply`.
- 2026-07-29 R6 (`70a6cfe76`, `32397d598`): ретаргет адреса рецепта до сборки.
- 2026-09-23/24 gui-service ред. 2, ADR-RCP-007 (`recipe.*` на хабе, владелец — бэкенд), 1b.1 реализован (`RecipeService`).
- 2026-10-04 О-16: GUI-планы полосы И отложены (`docs/handoffs/2026-10-03_plans-progress-lead.md:60`).
- 2026-10-12 `680e9f545`: R-8…R-12, план `stand-recipe-switch`; ADR-PMM-035/036 (бюджет стопа).

## 2. Замысел
- PM исполняет команды на одном потоке сообщений. Стоп non-protected параллельно с общим дедлайном → cleanup → provision → create → start (5 фаз). Откат тем же конвейером; провал ДО исполнения → no-op.
- Готовность: `_wait_started_ready` по `ready_event`, settle-окно — только фолбэк (ADR-PMM-011).
- Protected (`devices`, `gui`, PM из `base.yaml`) не трогаются; конфликт конфига ловит планировщик (`planner.py:341`).
- Владение активацией: ADR-RCP-007 — бэкенд; GUI на диск не пишет.
- Routing: ADR-PMM-010, incarnation и refresh очередей после switch.

## 3. Задумано → статус → код
| Задумано | Статус | Код |
|---|---|---|
| Параллельный стоп `stop_many` | DONE | `process_registry.py:350` |
| SHM release при switch | DONE | `shared_resources_module/memory/core/manager.py:458`; `process_manager_process.py:1287` |
| hot-swap == boot (proc_dict) | DONE | сборка через `planner.py` `proc_dicts_fn` |
| Свежая инкарнация SHM | DONE | не проверено в `shm.py` |
| Task 7: кадры после switch | ОТКРЫТ, A/B не решена | `docs/audits/2026-09-29_transport-f4-payload-inventory.md:61` |
| FullReplacePlanner | DONE | `backend/assembly/planner.py:136` |
| IncrementalPlanner | в docstring, не создан | `planner.py:11` |
| Откат тем же конвейером | DONE | `process_manager_process.py:3917` |
| Debounce | DONE | `process_manager_process.py:798` |
| Барьер готовности | DONE | `process_manager_process.py:4041`, `:4162` |
| Routing epoch | DONE | `process_manager_module/process` (18 вхождений) |
| Wire re-issue | DONE | `process_manager_process.py:1117` |
| Ретаргет адреса до сборки (R6) | DONE | `process_manager_process.py:751-790` |
| Topology gate (ADR-SS-019) | DONE | `state_store_module/middleware/topology_gate.py:43` |
| `recipe.*` сервис с `activate` | 1b.1 реализован | `recipe/service.py:122,348`, `prototype/orchestrator.py:155` |
| GUI на `recipe.*` (1b.3) | заморожен (О-16) | в `multiprocess_prototype/frontend` вызовов нет |
| `recipe_path` от GUI (R-11) | открыт | `process_manager_proxy.py:95` |
| `process.hot_add/hot_remove` | сняты с действия | билдеры `frontend_module/bridge/system_commands.py:64,86`; обработчика в PM нет |
| 4.10 watch-from-revision | DEFERRED | `constructor-master/plan.md:445` |

## 4. Незавершённое / спорное
- hot-swap Task 7 — без решения A/B.
- IncrementalPlanner — только в docstring.
- Билдеры `process.hot_add/hot_remove` без обработчика (спорно по принципу FREEZE).
- 1b.3 (GUI на `recipe.*`) — не начата, О-16. Значит путь активации сейчас ДВОЙНОЙ: `recipe.activate` на бэкенде есть, GUI им не пользуется.
- Settle-окно 0.5 с — фолбэк, а не барьер.

## 5. Дефекты, касающиеся смены
R-8…R-12 (`plans/queue/defects.md`); R-9 уже чинился (`189da4020`, 2026-08-04) — почему открыт снова, не проверено; LP-4 (`constructor-master/plan.md:307`, stale state старой топологии) и stale PSR GUI после switch (`docs/claude/memory/project_switch_routing_stale.md`) — статус не проверен. Ссылка R-8 «:780» указывает на вызов ретаргета, обработчик начинается на :751.

## Что осталось открытым
Память `search.py` не запускалась; `shm.py`, `topology_manager.py:163-278` не читались; история обработчика `process.hot_add` (`git log -S`) не снята; ADR-PM-052 (коммит `8bb09ee3b`) в DECISIONS не найден; статус 1b.1 — по коммитам, не по плану.
