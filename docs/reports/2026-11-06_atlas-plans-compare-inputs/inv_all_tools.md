# Инвентарь планов «понять систему и управлять ею» (окно 2026-09-06…11-06; main c07fb7cb7)

Собрал Haiku-агент (Explore) по `git log/grep/ls`, лид сжал. Статусы — как сказано в файлах; «дубль» = два документа/плана описывают одно, а не доказанный дубль кода. Не читано по существу: `docs/reports/2026-11-06_atlas-plans-compare.md` (наш отчёт), `plans/2026-10-27_system-run-state/` (пересечение полей состояния с каталогом не проверено), `docs/maps/*`, `docs/diagrams/*` (заголовки), 149 файлов `plans/2026-10-04_atlas/{tasks,reports}`.

## Что есть (путь | статус | плюс, который нельзя потерять)
| Группа | Путь | Статус | Плюс |
|---|---|---|---|
| Атлас старый | `plans/2026-10-04_atlas/plan.md` (+research, tasks, reports) | в файле DRAFT; в `plans/queue/ORDER.md:318` IN PROGRESS (противоречие) | гейт CI 1.7a, трейлеры `Why/Layer/Refs`, `Task:`, view `ref/card/pack`, метрики M1–M4, kill K1.1 |
| Атлас новый | `docs/reports/2026-11-06_atlas-{system-vision,map-merge-design,plans-compare}.md`, `cto-atlas-path-verdict.md`, `cto-map-vision-advice.md` | видение одобрено; Д5 ждёт владельца | паспорт 6 разделов, скан по блобам, nav_bench, стопы |
| Ветка | `origin/feat/atlas-lookup-map` (75f818845): `scripts/atlas/{scan,tree,store}.py`, `scripts/arch_map/*`, `scripts/nav_bench/*` | пауза | скан 4,79 с/0,06 с; бенч; схема-карта |
| Карточка модуля | `docs/reports/2026-11-01_module-card-architecture*.md`, `cto-brief/verdict-module-card*.md`, `cto-roadmap-above-8*.md`, `control-core-vision-and-review-brief.md` | вердикты сохранены; «разбор с владельцем не проводился» | одна форма `command_specs()`, `access`, `register_from`, `module.info` |
| Каталог команд | `backend_ctl/` (53 инструмента), `dump_capabilities.py`, `docs/contracts/CAPABILITIES.{md,yaml}`, `command_contracts.py`, тесты `test_capabilities.py`, `test_command_contract_oracle.py` | Production; ORDER:77 «своего плана нет» | живой каталог, Pydantic-схемы параметров, оракул AST |
| Ф9 | `plans/2026-07-06_constructor-master/f9-foundation-above-8*.md` | DRAFT, ждёт S1′ | поля `access`, `idempotent`, `owner` |
| Камера | `plans/2026-10-18_camera-device-service/` | ACTIVE | пилот `command_contracts` → `command_specs()` (1.3) |
| Консоль | `docs/reports/2026-11-01_module-card-architecture-console-services.md`, `console_module` | проект | help/status/ps через каталог |
| Карты и графы | `scripts/arch_graph/ast_graph.py` (main, hard/lazy/tc), `scripts/graph_slice/`, graphify (48 870 узлов), sentrux dsm, `scripts/channel_map`, `scripts/message_contracts`, `COMMUNICATION_MAP.md` | в main | точная классификация импортов, blast radius, карта каналов и сообщений |
| Ручные карты | `docs/maps/*`, `docs/diagrams/*`, `docs/atlas/INDEX.md` | снимки | зоны с номерами строк; диаграммы как код; оглавление модулей |
| Память | `plans/2026-10-11_memory-rules-delivery/` | FREEZE до 2026-11-10 | доставка уроков агентам; индекс по модулям |
| Планы-дашборд | `plans/2026-10-02_plans-progress-dashboard/`, `plans_progress --json` | ACTIVE | HTML-вид планов; контракт якоря (ORDER:266) |
| Коммиты | `plans/2026-10-03_commit-mechanism/` | IN PROGRESS | трейлеры, COMMIT_GUIDE |
| GUI/состояние | `plans/2026-09-22_gui-service/`, `plans/2026-10-27_system-run-state/` | APPROVED | токен PSK, состояния системы |

## Пересечения без владельца (8)
1. Паспорт/`module_spec`/`atlas card` ↔ карточка модуля в `base_manager` ↔ Д4 «паспорт читает только объявленное».
2. Каталог команд ×3: `command_specs()`/`command_contracts` ↔ `introspect.capabilities` + дамп ↔ поля Ф9 (`access`, `idempotent`, `owner`).
3. «Кто от кого зависит»: `graph_slice` ↔ `atlas ref/card` ↔ graphify; Д7 откладывает решение до стопа 1.
4. Карта архитектуры ×6: `arch_map` (ветка) ↔ `atlas map`/imports ↔ `ast_graph.py` ↔ `docs/maps` ↔ `docs/diagrams` ↔ `docs/atlas/INDEX.md`. merge-design велит удалить `arch_map`, задачи в `plans/` нет.
5. Раздел `## Map` в правилах ролей: memory-rules 2.3 ↔ Атлас 1.10b ↔ Атлас 2.4g; memory-rules в FREEZE.
6. `backend_ctl` (53 инструмента) без плана; пересекается с 1 и 2.
7. Удаление дублей: Атлас 2.5 (`plan_file_map.py`, `aggregate_context`, `session-project-map.sh`) ↔ принцип FREEZE не KILL — нужно поимённое слово владельца.
8. Видение (A1 первым) ↔ вердикт CTO §5 (0a→0b→1); видение не обновлено.
Есть владелец (не проблема): два HTML-вида планов (контракт якоря ORDER:266); «ветка → план» (дашборд 5.4 решает, Атлас 2.5 удаляет).

## Противоречия статусов
`plans/2026-10-04_atlas/plan.md:5` DRAFT ↔ `ORDER.md:318` IN PROGRESS; `backend-ctl-review-remediation`: ORDER:308 «не начат» ↔ ORDER:420 «4 из 18».
