# Карточка модуля (2026-11-01): решения CTO, состояние в main @c07fb7cb7, стык с паспортом атласа

Пути: V=docs/reports/2026-11-01_cto-verdict-module-card.md; V1=...-q1-7.md; V2=...-q8-14.md; A=...module-card-architecture.md; AV=docs/reports/2026-11-06_cto-atlas-path-verdict.md; F9=plans/2026-07-06_constructor-master/f9-foundation-above-8(-tasks).md.

## 1. Решение CTO (V:31-33, V:67-78)
Состав утверждён: `access` (4 класса, умолчание `write`) в каталоге `introspect.capabilities` (V2:15); одна форма объявления `command_specs()` (кортежи, 1:1 в kwargs `register_command` + `access`) (V1:15); `CommandManager.register_from(owner)` зовёт ВЛАДЕЛЕЦ после своего `initialize()`, не реестр (V1:19); `module.list/info` читают `get_stats/get_debug_info` (V1:13,19). Порядок (V2:11): 1 `access`+клиент читает+`READ_SAFE_*` заморожен; 2 `command_specs`+`register_from`+тест «дамп до/после побайтно», пилот stats(5)/state_store(7); 3 `module.list/info`; 4 семьи `BuiltinCommands` к владельцам (мерило: 92 `self._services` вниз); 5 адаптер плагинов после camera-device 1.3. Вырезаны шаги 7–8 (BaseService). Отклонено: `@expose` как основной путь (сахар после пилота), отмена ADR-SVC-002, `unregister_command`, `declare_module`, «все 18 на BaseService», God Mode, второй статический описатель (V:78). Место: 2.0, не 1.0 (V2:21).

| Q | Решение |
|---|---|
| 1 | ПРИНЯТЬ: карточка — вид; ядро = существующий каталог, не новый `CommandSpec`; `CommandCatalog` прототипа — третий каталог (V1:11) |
| 2 | ИЗМЕНИТЬ: сразу команды+`access`+владелец; `registers`/`router_handlers` уже в карточке; вырезать «Конфиг», «Здоровье»; состояние — `module.info` (V1:13) |
| 3 | ИЗМЕНИТЬ: `@expose` отклонён; одна форма = плагинная `command_contracts` (camera 1.3) → `command_specs()`; имена без префикса заморожены, новым `<модуль>.<действие>` (V1:15) |
| 4 | ИЗМЕНИТЬ: BaseService опционально; ADR-SVC-002 не отменять; оболочки `state:"shell"`; приёмка «ресурс виден» (V1:17) |
| 5 | ИЗМЕНИТЬ: реестр не расширять; `register_from` из места сборки владельца (образец `state_store_manager.py:613`) (V1:19) |
| 6 | ИЗМЕНИТЬ: `modules.yaml` единственный статический источник; `declare_module` не вводить (V1:21) |
| 7 | ИЗМЕНИТЬ: `unregister_command` не добавлять; остановленный сервис отвечает «not running» (V1:23) |
| 8 | ИЗМЕНИТЬ: порядок выше; прототип первым — стенд тождества таблицы, не автоадаптер (V2:11) |
| 9 | ПРИНЯТЬ: `introspect.*`, `declare_log_source`, Atlas card — часть карточки; `module.info`↔`introspect.status`, `describe`↔`atlas card` (V2:13) |
| 10 | ПРИНЯТЬ: `access`+`source`+аудит в контракте; `policy(spec, envelope)->bool`, None=ноль; L0–L3 не строить; `access` обязан быть в CI-дампе (V2:15) |
| 11 | ИЗМЕНИТЬ: консоль — экран+аварийный вход; God Mode FREEZE; до доказательства только `access=read` (V2:17) |
| 12 | ИЗМЕНИТЬ (находки): бог-файл, `modules.yaml`, коллизии `set_config`, `sentrux` нет в venv (V2:19) |
| 13 | ИЗМЕНИТЬ: старт после 6а; малый план, владелец constructor-master (V2:21) |
| 14 | Упущено: `CommandCatalog`, camera 1.3/1.4, 92 связки, `sentrux`, `set_config` без владельца (V2:23) |
Открыто (V:90-100): консоль при зависшем `message_processor` не воспроизведена; команды плагина после стопа не проверены; размеры S/M/L — суждение.

## 2. Что есть в коде main (git grep, `*.py`, весь репозиторий)
| Элемент | Код | Где |
|---|---|---|
| `CommandSpec`, `register_from`, `command_specs`, `@expose`/`def expose` | нет (0 вхождений в .py) | только `plans/…/f9-foundation-above-8-tasks.md:17-26` (Ф9.7) |
| `module.list` / `module.info` | нет (0 в .py и в framework/*.md) | — |
| `access` в каталоге | нет (B3=0, `f9-foundation-above-8.md:B3`); клиентский кортеж жив: `backend_ctl/mcp_tools.py:1579,1643` | — |
| `command_contracts` у плагина (camera 1.3) | нет: в `plugins/base.py` только `command_options` (`:1744`); `command_contracts.py` — реестр процесса | `process_module/commands/command_contracts.py` |
| `introspect.capabilities` | ЕСТЬ | `builtin_commands.py:687,840-920` (+`CAPABILITIES.yaml/.md`) |
| `introspect.status/plugins/registers` | ЕСТЬ | `builtin_commands.py:662,667,692` |
| `command_options` плагина | ЕСТЬ (SPI.d1 `de9c47a64`) | `plugins/base.py:1744` |
| `get_stats/get_debug_info` | ЕСТЬ | `base_manager/interfaces.py:99,103` |
| `BaseService`/ADR-SVC-005, `state:"shell"` | нет | — |
План: отдельного `command-cards` нет (`ls plans`, `git log --grep` по module-card/CommandSpec: только 3 docs-коммита 2026-11-01: `cf087e491`, `d6f267fe0`, `dcf7bc22c`). Живёт как Ф9 мастер-плана: Ф9.2 (`access`) → Ф9.7 (`command_specs`+`register_from`) → Ф9.19 → Ф9.8, все [PENDING] (`plan.md:~551`), статус DRAFT, коммит `aae113c76`, ORDER стр. 45 (`plans/queue/ORDER.md:78`): 2.0, код после приёмки 6а и camera 1.3.

## 3. Карточка ↔ паспорт (Д1: purpose/interface/links/runtime/checks/status, AV §4)
| Поле карточки | Раздел паспорта |
|---|---|
| id, слой, ярус, `purpose` | `purpose` / `status.tier` (AV:Д5 — yaml → докстринг) |
| API (`interfaces.py`) | `interface` |
| команды: имя, описание, теги, `access`, `params` | `runtime.commands` (статически) |
| `executor/key_from/targets` | `runtime.commands` (как опции) |
| `router_handlers`, `registers` | не относится (рантайм-снимок процесса) |
| `get_stats/get_debug_info/get_status`, `module.info` | не относится (рантайм) |
| `declare_log_source/metric` | `runtime.io` (литералы в AST) |
| владелец команды | `links` (`where: файл:строка`) |
| Конфиг/FieldMeta, Здоровье | вырезаны CTO (V1:13), не в паспорте |
Статика для `runtime.commands` сегодня: сканер читает литералы `commands = {…}` и `register_command("…")`, пишет «динамических: M» (AV:§2 вопр.2; vision:86-88). Д4: шаги 1–2 карточки выбирают литеральные формы (`@expose`/кортеж `CommandSpec`) (AV:Д4). Прообраз: `origin/feat/atlas-lookup-map:scripts/arch_map/signboard.py:912` (`card.get("commands")`), тест `I16` — не в main.
Оценка «сколько динамических» (git grep, без tests; не AST-счёт):
| Форма | Число | Читается статически |
|---|---|---|
| класс-атрибут `commands = {…}` не пустой, в Plugins/ + Services/*/plugin | 24 + 7 = 31 из 58 файлов с атрибутом (остальные `{}`) | да |
| литеральный `register_command("…")` вне докстрингов | 1 (`plugins/base.py:1742`, `set_config`) | да |
| `register_command(name, …)` с переменной имени, циклы `specs`/`commands.items()` | `builtin_commands.py` 13 вызовов + `state_store_manager.py:636`, `stats_adapter.py:41-56` (лямбды), `console_adapter.py:114,156`, `tap_commands.py:74`, `plugin_orchestrator.py:387,409`, `process_manager_process.py:316,630` | частично (`stats_adapter` — литералы в вызове; остальное — цикл/словарь) |
| генерируемые в рантайме | `device_hub` robot_*/vfd_* (55) через `install_op_commands`, `Plugins/hub/device_hub/plugin.py:113,1044-1047` | нет |
Итого динамика: 18 файлов с `register_command(` в production, из них литерально статичны ~1–2; 38 `_cmd_*`, 10 `_register_*` в `builtin_commands.py`.

## 4. Риск второго реестра
- Рантайм в карточке, не в паспорт: `get_stats/get_debug_info` (`module.info`), `introspect.status`, `registers`/`router_handlers` — `builtin_commands.py:884-902` читает `rm.model_dump_all()` и `event_dispatcher` живьём.
- Каталог уже самосведён: комментарий «новый реестр не вводится» (A:26); `builtin_commands.py:843` — «свод КОНТРАКТА, не runtime-значений».
- Паспорт должен только читать объявление в коде; `backend_ctl capabilities` — сверка (AV:Д4, §2.2). Риск CTO: две правды об `access` — клиентский кортеж `mcp_tools.py:1579` и каталог (V2:25).
- Третий список команд — `multiprocess_prototype/frontend/bridge/command_catalog.py` (V1:11); `modules.yaml` ещё рукописный (AV:Д5).

## Что не нашёл / ненадёжно
- Содержимое `cto-brief` (28 КБ) читал по заголовкам, §4 и вопросам; §2–3 не вычитывал.
- Подсчёты — `git grep` по regexp без AST: `register_command(` включает определения и докстринги, число «динамических» — оценка, не факт; `commands = ` в backend_ctl/frontend — не плагины (счёт 58 файлов только Plugins/ и Services/*/plugin).
- Статус camera-device 1.3 (`command_contracts`) по main выведен отсутствием символа, сам план 1.3 не читал.
- Файлы `cto-roadmap-above-8*.md` и статус приёмки 6а (ORDER:38, на 11-02) не открывал; ветку `feat/atlas-lookup-map` смотрел только `git show`/`grep` по `signboard.py`.
- `docs/reports/2026-11-06_atlas-system-vision.md` вопрос 2 — строки 86-88; ответа в нём нет, ответ — AV §2 п.2.
