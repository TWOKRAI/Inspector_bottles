# Ф1+Ф2 — адрес=путь и снятие=поддерево (неделимая поставка) + Ф2-Т

_Часть плана [`plans/observation-port/plan.md`](./plan.md) — вынесено при дроблении 2026-08-27 для полного чтения инструментами (исходно единый файл 295 КБ превышал лимит чтения в 256 КБ). Контекст, критерии приёмки и правила §1-3 — в основном plan.md._

---

## Ф1 — адрес = путь: поддерево писателя вместо арбитража

**Ветка:** `feat/observation-port` от `main` (после merge Ф6). **Цель фазы:** плагинные уровни
едут в `state.plugins.<plugin>.<метрика>`; арбитраж владения удалён; класс дефектов мёртв
структурно. **Видимый результат:** GUI показывает метрики capture под новым путём; инъекция
«вернуть плоское имя» не находит механизма, который можно сломать.

**Ф1 и Ф2 — одна неделимая поставка** (решение владельца по итогам ревью плана, блокер Б2):
Ф1 вырезает старое поимённое снятие ВМЕСТЕ с арбитражем — его посылки во вложенной форме ложны
(Ф0-фильтр снятия стоит на `metric_owners`, который Ф1 удаляет; писатель надгробий кладёт плоское
`state[имя] = None` и после переезда листьев в поддерево положил бы надгробие на плоский путь при
живом писателе — форма A1 внутри самого плана, см. Task 1.2 шаг 6). Замену приносит Ф2; между
ними механизма снятия нет, поэтому Ф1 отдельно не предъявляется на стенде и не merge'ится —
единица поставки, ревью и merge — пара Ф1+Ф2 (§11.7).

> **СТОП перед Task 1.2 ставился и СНЯТ в тот же день — посылка стопа была неверна.**
> Стоп звучал так: «предусловие „Ф1+Ф2 от `main` ПОСЛЕ merge Ф6“ не выполнено по существу, потому
> что гейт Ф6 не прогонялся». Владелец возразил, и он прав: план говорит **merge**, а не «гейт
> пройден», и merge состоялся — `feat/telemetry-stage6` влита в `main`, обе на `ff0308f4`
> (`git merge-base --is-ancestor` подтверждает). Более строгое чтение внёс исполнитель и вынес его
> же в варианты вопроса владельцу, то есть выбор делался из неверно поставленной развилки.
> **Ф1 не заблокирована.** Запись оставлена, а не удалена: тот же класс ошибки («посылка плана
> прочитана строже, чем написана») стоит дороже, чем чистая страница.
>
> Гейт Ф6 прогнан (2026-08-19) и **не принят** — 6 пунктов из 16; разбор на три класса в
> [`telemetry-stage6.md`](../telemetry-stage6.md), раздел «Результат гейта Ф6». Для Ф1 это соседний
> трек. **Точка касания одна и названа явно:** `telemetry_reload.py:212` фигурирует и в находках
> гейта (Р-2/Р-3 — ручка не подтверждается сверщиком), и в инвентаре Task 1.1 как читатель,
> мигрирующий в Task 1.4. Правки двух треков в этом файле развести по времени, а не по счастью.
>
> **Настоящее предусловие переезда — было, и оно закрыто.**
> `multiprocess_prototype/backend/tests/test_build_characterization.py` был красен на `main` до
> всякой Ф1 (golden протух относительно `telemetry.publish`, `cb79d884`), а регенерация golden
> замораживает заодно ПЛОСКИЕ правила троттла — то есть делать её надо было строго ДО переезда
> путей. Сделано `69da0abb`; заодно снят второй красный `20327f66`. Корневой гейт на принимаемом
> HEAD — **6992 passed / 64 skipped / 0 failed ×3**, фреймворковый — **8620 / 8 skipped / 1 xfailed**.

### Task 1.1 — Инвентарь читателей путей (стоп-условие фазы)
**Level:** Middle · **Assignee:** developer
**Goal:** Поимённый список всех читателей `processes.*.state.*` — до любой правки.
**Files:** результат — раздел в этом плане (обновить), без правок кода.
**Steps:**
1. Известные читатели (проверено): `telemetry_readmodel_module/telemetry_read_model.py:49-51`
   (суффиксы `.state.fps`, `.state.latency_ms`, `.state.uptime`); GUI-строки метрик
   (`multiprocess_prototype/frontend/widgets/tabs/processes/_telemetry_controls.py`);
   троттл-правило прод-конфига `processes.**.state.fps` (остаётся валидным — `fps` не переезжает).
2. DB-sink телеметрии ПРОВЕРЕН ревью плана, гипотеза снята: ключ — по ПУТИ
   (`Plugins/io/telemetry_sink/plugin.py:221-226` — известное плоское имя → колонка таблицы,
   прочее → `_extra` с ключом-путём). Коллизий нет; рвётся непрерывность `_extra`-историй
   плагинных метрик (новый ключ). Решение владельца 2026-08-19: разрыв ПРИНЯТ как осознанная
   цена (§10), стоп-условия по стоку НЕТ.
3. Найти НЕИЗВЕСТНЫХ: `qex:search_code` + grep по `\.state\.`, `state.plugins`, подписки
   (`subscribe` с паттернами по `processes.`).
4. Каждому читателю — вердикт: «не задет» / «мигрирует в Task 1.4» / «неизвестный — СТОП фазы»
   (стоп остаётся только для читателей, которых план не знает).
**Acceptance criteria:**
- [x] таблица читателей в плане (ниже); неизвестных не осталось. **Три** были неизвестны плану —
      `alert_rules.py:104` (`drops_growing` читает `state.drops`), `bootstrap.py:64-70` (засев
      кладёт плоский `frame_count`), `telemetry_reload.py:227-231` (потолок троттла матчится по
      последнему сегменту); все три классифицированы «мигрирует в Task 1.4», фаза не остановлена
**Out of scope:** правки читателей.

#### Результат Task 1.1 — таблица читателей (снято 2026-08-19, HEAD `ff0308f4`)

> Ред. 2 — после ревью итерации 1 (`CHANGES REQUESTED`). Ревью нашло три пропуска
> (`bootstrap.py`, регресс-страж `test_alerting.py`, два build-снапшота) и пять съехавших
> якорей; один читатель (`frontend/app.py:314`) оказался комментарием, а не подпиской, и снят.
> Всё внесено ниже; расхождения ред. 1 в тексте не сохраняются — сохраняются в git.

**Первый факт, без которого таблица не читается: сегодня переезжают РОВНО ТРИ листа.**
Каталог `declared_metrics()` (`observability_declarations.py:234`) наполняется вызовами
`declare_metric(`; вне тестов их восемь, и владельцы разные:

| Имя | Владелец | Якорь | Переезжает в Ф1? |
|---|---|---|---|
| `fps`, `latency_ms` | фреймворк | `process_module/heartbeat/telemetry.py:39-40` | нет |
| `effective_hz`, `cycle_duration_ms` | фреймворк (поддерево `workers.`) | `telemetry.py:41-42` | нет |
| `shm` | фреймворк | `process_module/heartbeat/process_heartbeat.py:21` | нет |
| **`capture_fps`, `frame_count`, `drops`** | **плагин `capture`** | `Plugins/sources/capture/plugin.py:103-105`, публикация `:359-361` | **да** |

Инвариант тут прочнее, чем «список объявлений»: `build_plugin_levels`
(`heartbeat/telemetry.py:661-664`) отбрасывает лист, если `owners.get(name) != publisher` —
недекларированная публикация в дерево не попадает **по построению**. Четвёртой плагинной
метрики на боевом коде не существует (подтверждено независимым grep ревьюера).

Всё остальное, что лежит под `processes.<P>.state.*` (`cam.actual.*`, `phone.*`,
`control_panel.controls`, `status`/`paused`/`frozen`, `word_layout`), пишется плагинами
**напрямую** через `state_proxy.merge`, а не разъёмом `publish_metric`
(`Plugins/sources/camera_service/plugin.py:364`, `Services/phone_gateway/plugin/plugin.py:234,260,296`,
`Services/control_panel/plugin/plugin.py:122`, `Plugins/sources/capture/plugin.py:323`,
`Plugins/processing/word_layout/plugin.py:414`, `Plugins/utility/pilot_widgets/plugin.py:113`,
`Plugins/processing/color_mask/plugin.py:129`, `Services/ml_inference/plugin/plugin.py:318`).
Ревью открыло все десять якорей: ни один не идёт через `PluginLevels`. Ф1 трогает сборщик тика,
а не прямую дорогу `merge` — эти поддеревья остаются на месте, их читатели **не задеты**. Прямая
дорога — предмет Ф5; здесь названа, чтобы её читателей не считали дважды.

**Таблица читателей.**

| Читатель (`файл:строка`) | Что читает | Вердикт |
|---|---|---|
| `multiprocess_prototype/frontend/widgets/tabs/processes/_telemetry_controls.py:181` | `f"processes.{proc}.state.{metric}"` для КАЖДОЙ метрики каталога — список из `_panels.py:792` (`list(gated_metrics())`). **ПОСЫЛКА «каталог содержит все три переезжающих» ЛОЖНА — измерено ревью Task 1.4 и перепроверено:** в процессе GUI каталог = `['cycle_duration_ms', 'effective_hz', 'fps', 'latency_ms', 'shm']`. Пять фреймворковых объявлены ИМПОРТОМ (`heartbeat/telemetry.py:39-42`), а `capture_fps`/`frame_count`/`drops` объявляет РАНТАЙМОМ сам плагин внутри процесса захвата (`Plugins/sources/capture/plugin.py:103-105`, `ctx.declare_metric`) — в процесс GUI это объявление не доезжает. Значит строка `_telemetry_controls` сегодня НИ РАЗУ не спрашивает мигрировавшее имя, и восемь новых тестов работают на синтетическом каталоге. Код мигрирован и станет живым после Ф4.2 (каталог из readback `introspect_telemetry(...).gated_metrics`, `_telemetry_controls.py:15`). Ф2 и Ф4 обязаны строиться на ЭТОМ факте, а не на прежней строке | **мигрирует в Task 1.4 (вступит в силу после Ф4.2)** |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/cam_actual_section.py:143` | bind `processes.{proc}.state.capture_fps` → метка «FPS (измеренный)» | **мигрирует в Task 1.4** |
| `multiprocess_prototype/backend/state/manager_setup.py:54,57,58` | glob-правила троттла `processes.**.state.{capture_fps,frame_count,drops}` (54 — `capture_fps`, 57 — `frame_count`, 58 — `drops`; 55/56 — `latency_ms`/`uptime`, не переезжают) | **мигрирует в Task 1.4** |
| **`multiprocess_framework/modules/process_manager_module/core/alert_rules.py:104-105`** + потребители `alert_rules.py:66-74` (`paths_for`), `monitor/process_monitor.py:381-387` (`_check_counter_alerts`: `current = self._read_state_int(path)`, `if current is None: continue`) | правило `drops_growing` читает `processes.{process}.state.drops` / `.drops_count` точным путём | **мигрирует в Task 1.4 — ПЛАН ЕГО НЕ ЗНАЛ** (разбор ниже) |
| **`multiprocess_prototype/backend/state/bootstrap.py:64-70`** | засев начального дерева: `state = {"status","pid","fps","frame_count","error"}` — **плоский `frame_count: None` каждому процессу**; боевая дорога (`backend/launch.py:653` → `build_initial_state`) | **мигрирует в Task 1.4** (разбор ниже) |
| `multiprocess_framework/modules/process_module/managers/telemetry_reload.py:212` (`_central_rule_for_metric`, тело `:227-231`: `pattern.rsplit(".", 1)[-1] == metric`) + потребитель `detect_throttle_caps` (`:281`) | сопоставление правила троттла с именем метрики **по последнему сегменту**. Докстринг `:215-218` объявляет это посылкой: «central-правила троттла авторятся как листовые глобы вида `processes.**.state.fps` — последний сегмент == имя метрики… framework не знает layout дерева прототипа — это app-specific» | **мигрирует в Task 1.4**: суффикс-матч переезд переживёт, и в этом дефект — `processes.**.state.capture_fps` станет мёртвым глобом (в дереве не матчит ничего), а `detect_throttle_caps` продолжит рапортовать его как действующий потолок |
| `Plugins/io/telemetry_sink/plugin.py:216-226` | `parts = path.split(".")` (`:216`); `len(parts)==4 and parts[3] in _STATE_COLS` → колонка (`:223-224`); иначе `_extra[".".join(parts[2:])]` (`:226`). `_STATE_COLS = ("fps","latency_ms","uptime","status")` (`:192`) | не задет структурно (три имени и сегодня идут в `_extra`); **ключ `_extra` меняется** `state.capture_fps` → `state.plugins.capture.capture_fps` — принятая цена §10 |
| `multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py:49-51`, матчер `:339` (`path.endswith(suffix)`) | `DEFAULT_TRACKED_SUFFIXES` = `.state.fps`, `.state.latency_ms`, `.state.uptime` (+ per-worker) | не задет — ни одного переезжающего имени в наборе |
| `multiprocess_framework/modules/frontend_module/state/telemetry_poller.py:97-113` | `_flatten_levels` — рекурсивная раскладка ответа опроса в плоские пути | не задет **по построению**: вложенный `plugins` раскроется сам, без правки |
| `multiprocess_framework/modules/process_module/configs/telemetry_publish_config.py:118` | `resolve(metric_name)` — гейт публикации ключуется **ИМЕНЕМ метрики**, не путём дерева | не задет; названо явно, чтобы ключ гейта и адрес дерева не разошлись по семантике молча |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:497` | `handle_state_get("processes.{p}.state.fps")` → `system.health.avg_fps` | не задет (`fps` остаётся) |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:465,1555` | пишет `state.uptime` / `state.status` | не задет (писатель-фреймворк, не переезжает) |
| `backend_ctl/driver.py:1283-1290` | `_telemetry_matches_metric`: `path == metric or path.endswith("." + metric)` | не задет: `metric="capture_fps"` матчит и новый путь. **Нюанс:** форма `metric="state.capture_fps"`, названная в докстринге `:1286`, матчить перестанет |
| `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py:587-595,664,919-921,1208-1221,1244-1245` | VM-сеттеры и `history()` по `state.{fps,latency_ms,status,uptime}` | не задет |
| `multiprocess_prototype/frontend/widgets/tabs/processes/_system_dashboard.py:120` | `state.{fps,latency_ms}` (хардкод `_DASHBOARD_METRICS`) | не задет |
| `multiprocess_framework/modules/process_module/plugins/io_peek.py:155` | `f"processes.{proc}.plugins.{plugin}.io_peek"` — узел `plugins` **рядом** со `state` | не задет; но узлов `plugins` после Ф1 будет **четыре**, и ближайший — не этот: корневой каталог `plugins`, `processes.<P>.**config**.plugins` (оба есть уже в засеве, `bootstrap.py`), `processes.<P>.plugins.<плагин>.io_peek` (рантайм) и новый `processes.<P>.**state**.plugins.*`. С конфигурационным разница ровно в одном сегменте, и паттерн `processes.**.plugins.**` ловит **три из четырёх** (прогнано: `config.plugins` → True, `io_peek` → True, новый узел Ф1 → True, корневой `plugins` → False). Имя-коллизия названа здесь, чтобы Ф3 не считала её случайной |
| `multiprocess_prototype/frontend/process.py:102`, `Plugins/io/telemetry_sink/plugin.py:126` | подписки `processes.**` | не задет — wildcard покрывает любую глубину |
| `state_store_module/middleware/topology_gate.py:85-88` | `parts[0]=="processes"`, `parts[1]` — имя процесса | не задет — читает только два первых сегмента |
| `state_store_module/{middleware/throttle.py:345,588-606; middleware/logging_mw.py:112-125; core/subscription_manager.py:325; manager/state_store_manager.py:507,529-533; proxy/state_proxy.py:838-841,959; selectors/selector.py:270; health/monitor.py:150-155}` | один и тот же сегментный матчер `match_pattern` | не задет **сам по себе**; ломается только через ТЕКСТЫ паттернов, которые авторятся снаружи |
| `state_store_module/devtools/inspector.py:112-117` | `value = store.get(path)`; **если dict — возврат на `:113`**; ветка `:116-117` (обёртка по последнему сегменту) — только для скаляра | не задет; но **форма ответа `inspect("processes.<P>.state")` меняется**: в dict появится узел `plugins` рядом с плоскими листьями |

**Механика промаха — прогнана, не выведена.** Паттерн `processes.**.state.frame_count`
разбирается в `["processes","**","state","frame_count"]`; путь после переезда —
`["processes","camera_0","state","plugins","capture","frame_count"]` (второй сегмент — имя
ПРОЦЕССА, четвёртый-пятый — новые). `**` поглощает 0..N сегментов, но требует, чтобы `state` и
`frame_count` шли **подряд**. Прогон `_match_pattern` (`core/subscription_manager.py:66-106`):

```
pat=processes.**.state.frame_count  path=processes.camera_0.state.frame_count                  -> True
pat=processes.**.state.frame_count  path=processes.camera_0.state.plugins.capture.frame_count  -> False
контроль: pat=processes.**          path=processes.camera_0.state.plugins.capture.frame_count  -> True
```

Контрольная строка обязательна: без неё `False` неотличим от сломанного матчера.

**Неизвестных читателей не осталось — но их было три, и каждый стоит абзаца.**

**(1) `alert_rules.py:104` (`drops_growing`).** В §1 плана не назван. Его собственный комментарий
(`:96-102`) описывает ровно тот класс, которым переезд его и убьёт: «путь обязан совпадать с тем,
что РЕАЛЬНО публикуют источники… иначе правило молча мертво (находка ревью NEW-7: дефолт указывал
на `drops_count` под `processes.*`, который не публикует НИКТО)». Правило уже было мёртвым по этой
причине и было починено — Ф1 без правки убивает его вторично. Хуже: докстринг `paths_for`
(`:70-73`) обещает «монитор берёт ПЕРВЫЙ путь, который реально резолвится, — правило не умирает
молча от переименования». После переезда **не резолвится ни один** из двух кандидатов, и обещание
становится ложью — класс «уверенное неверное объяснение переживает баг». Правку докстринга внести
вместе с путём в Task 1.4.

**(2) `bootstrap.py:64-70` — писатель мигрирующего имени по старому адресу.** Найдено ревью;
не попадает ни в одну половину развилки «переезжает / пишется прямой дорогой». Сегодня сборщик
тика перетирает засеянный `frame_count: None` живым числом. После Ф1 не перетрёт: имя окажется по
двум адресам сразу — вечный `processes.<P>.state.frame_count = None` рядом с настоящим
`state.plugins.capture.frame_count`. Диагноз «пути нет» превращается в «путь есть, но мёртв», а
это разные диагнозы. Требование к Task 1.4: после переезда плоского `frame_count` в засеве быть не
должно — либо решение оставить его записано с доводом. `drops`/`capture_fps` в засеве нет
(проверено grep'ом и прогоном самого засева).

**(3) `telemetry_reload.py:212` (`_central_rule_for_metric`) — посылка задокументирована, и Ф1 её
ломает.** Функция ищет central-правило троттла для метрики по ПОСЛЕДНЕМУ сегменту паттерна, и её
докстринг (`:215-218`) объясняет почему: «framework не знает layout дерева прототипа
(`processes.**.state.*`) — это app-specific. Суффикс-матч оставляет framework generic». Довод
верный, и именно он делает дефект незаметным: после переезда `processes.**.state.capture_fps`
перестаёт матчить дерево (прогон выше), но суффикс `capture_fps` у паттерна остаётся, поэтому
`detect_throttle_caps` (`:281`) продолжит считать правило действующим потолком и рапортовать
`capped_by_throttle`. Оператор увидит «капнуто» там, где не капается ничего. Расхождение молчаливое
с обеих сторон: и глоб не жалуется на промах, и сверщик не жалуется на глоб.

**Отказ немой — у ПЯТИ читателей из шести, и у двух по разным механизмам.** Мигрантов в таблице
шесть. Четыре умирают промахом glob'а (несовпавший паттерн не ошибка: троттл перестаёт троттлить,
метка застывает на «—», потолок рапортуется несуществующий). `bootstrap.py:64-70` — **другой**
механизм: не промах, а живой лист-призрак по старому адресу, который никто больше не перетирает.
Шестой, `drops_growing`, немым не будет — у него регресс-страж **есть** и он выстрелит:
`multiprocess_framework/modules/process_manager_module/tests/test_alerting.py:48-58`
(`assert rule.counter_paths[0].endswith(".state.drops")`) — сейчас зелёный
(`pytest … -k drops` → `1 passed`), после переезда красный обоими ассертами. Поставлен он прошлым
ревью против того же класса дефекта.

**Чем Task 1.4 НЕ может доказать переезд.** Тесты
`multiprocess_prototype/backend/state/tests/test_integration.py:376-386` и
`multiprocess_prototype/backend/tests/test_rt2_config_flip_acceptance.py:44-53` сверяют СЛОВАРЬ
правил троттла с эталоном, а не факт совпадения правила с живым путём: поправь писателя, забудь
glob — оба останутся зелёными при снятом предохранителе. Приёмка Task 1.4 обязана нести пару
«правило матчит реально опубликованный путь», а не сверку словаря.

**Два build-снапшота пиннят плоские правила — и КРАСНЫ до начала фазы.**
`multiprocess_prototype/backend/tests/snapshots/hikvision_letter_robot.build.json:611-614` и
`phone_sketch.build.json:1101-1104` держат полный набор плоских `state_throttle_rules` и
сверяются бит-в-бит (`test_build_characterization.py:138`, `assert actual == expected`). На HEAD
`ff0308f4` оба теста **уже падают** (`2 failed in 4.16s`), и причина к путям отношения не имеет:
golden протух относительно правки `telemetry.publish` — сборка добавляет
`telemetry.publish.metrics.fps` и `.latency_ms` (`{"enabled": true, "interval_sec": 1.0}`) в
`sys_config` и в конфиг КАЖДОГО процесса (7 процессов в `phone_sketch`, 10 в
`hikvision_letter_robot`), а в golden этих ключей нет. Следствие двойное: (а) опереться на
снапшоты как на сигнал Ф1 нельзя, пока красный не снят; (б) регенерация golden
(`UPDATE_BUILD_SNAPSHOTS=1`) **зафиксирует заодно и плоские правила троттла** — то есть выполнить
её надо ДО переезда либо ПОСЛЕ правки правил, но не между.

**Тесты, пиннящие плоский путь переезжающих имён** (станут красными — ожидаемо; список для
Task 1.4): `test_alerting.py:48-58` (framework); от `multiprocess_prototype/` —
`backend/state/tests/test_integration.py:376-386`,
`backend/tests/test_rt2_config_flip_acceptance.py:44-53`,
`backend/tests/snapshots/{hikvision_letter_robot,phone_sketch}.build.json` (красны и сейчас),
`frontend/widgets/tabs/pipeline/tests/test_cam_actual_section.py:59,66-96,189-192,202`,
`frontend/widgets/tabs/pipeline/tests/test_inspector_characterization.py:218`,
`frontend/widgets/tabs/processes/tests/test_telemetry_vm_panels.py:215,222-254`.
Тесты `backend/state/tests/test_capture_state.py:94-118` проверяют контракт `ctx.publish_metric`,
а не адрес в дереве, и остаются зелёными.

**ТРИ места с протухшей моделью — вне таблицы, но под ногами у Task 1.4.**
(1) `multiprocess_framework/modules/frontend_module/tests/state/test_telemetry_poller_hazards.py:41-52`
держит `_PUSH_ONLY_KEYS` с литералами `frame_count`/`drops` под комментарием «восемь ключей
дерева, которых опрос НЕ приносит». (2) `backend_ctl/driver.py:414-416` — докстринг утверждает то
же самое: «`uptime`/`frame_count`/`drops`/… пишут другие публикаторы и опросом не приходят».
Обе посылки уже неверны, и опровергает их сосед по репозиторию — `backend_ctl/mcp_tools.py:509`
прямо пишет, что `frame_count` и `drops` мигрировали в опрос задачей 3.5. (3) Там же
`mcp_tools.py:508` перечисляет состав опроса плоскими именами — тот же класс, что нюанс докстринга
`driver.py:1286`. Красными от переезда эти места, скорее всего, не станут; опасны они не поломкой,
а тем, что уверенное неверное объяснение переживает баг. Найдено ревью: третье место лежало в
файле, который сам же раздел объявлял проверенным.

**Где не смотрели (честно).** Не открывались построчно тестовые файлы широкого grep-хита
(`test_history_graph`, `test_system_dashboard`, `test_telemetry_controls`,
`test_telemetry_poll_visibility`, `test_bindings`, `test_delta_message`, `test_glob_match`,
`test_gui_process`, `test_tail_activator`, `test_topology_bridge`, `test_schema`,
`test_topology_schemas`, `test_connection_map`, `test_demo_recipe`) — ни один не назван читателем
в таблице. Не вычитаны построчно `backend_ctl/{recorder,conditions,watch,registers,dispatch,
transport}.py` и `backend_ctl/probes/*` — из `backend_ctl` построчно подтверждён только `driver.py`
(и он же дал третье место протухшей модели, `:414-416`). Не вычитаны построчно `Services/auth`,
`Services/sql`, `scripts/{arch_graph,message_contracts,channel_map}`, `Plugins/runtime/*`,
`Plugins/hub/device_hub` — по ним сделан только целевой grep трёх переезжающих имён, и он пуст:
единственные вхождения во всех этих зонах — `driver.py:414` и `mcp_tools.py:508-509`.
`.claude/worktrees/` исключены явно (чужие копии репозитория).

**Что подтверждено прогоном, а что чтением.** Живого прогона системы не было — Task 1.1 статичен
по определению, и последствия переезда (лист-призрак `frame_count`, мёртвый глоб, коллизия
`plugins`) остаются предсказаниями по коду. Прогонами подтверждены четыре факта: `-k drops` →
`1 passed`; `test_build_characterization` → `2 failed`; ключ-в-ключ диагноз протухшего golden
(32 добавленных ключа в `phone_sketch` = (7 процессов + sys_config) × 2 метрики × 2 поля; 44 в
`hikvision_letter_robot` = (10 + 1) × 2 × 2; изменённых значений и пропавших ключей — ноль, то
есть правила троттла в actual и golden идентичны); прогон `_match_pattern` с контрольной строкой
(выше). Регенерация golden под `UPDATE_BUILD_SNAPSHOTS=1` не запускалась — следствие «заморозит
заодно плоские правила троттла» выведено из кода (`test_build_characterization.py:122-124`,
`_dump_golden` дампит весь канонический срез), не наблюдено.

### Task 1.2 — Хранилище и сборка: писатель → имя → значение, арбитр удалён
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** `PluginLevels` ключуется писателем; сборщик строит поддерево `plugins.<писатель>.*`
без проверки владения; арбитраж и голос удалены.
**Files:** `multiprocess_framework/modules/process_module/heartbeat/telemetry.py`,
`.../heartbeat/process_heartbeat.py`, `multiprocess_framework/modules/observability_declarations.py`,
`.../process_module/plugins/base.py` (дописан по ревью Ф1: Ф1 сама открывает дыру — точка в имени
листа ИЛИ в имени писателя рвёт путь на два сегмента и оставляет вечно-мёртвый лист-двойник,
потому что до Ф1 точечное имя не пропускал арбитр, а теперь пропускать некому; guard живёт там же,
где `publish_metric`)
**Steps:**
1. `PluginLevels._values` → `dict[писатель][имя] = значение` (лок сохраняется — писатели в
   потоках воркеров, читатель в тике; довод из докстринга `telemetry.py:302-308` остаётся).
2. `build_plugin_levels` → чистая проекция хранилища в поддерево
   `{"plugins": {<писатель>: {<имя>: значение}}}` под гейтом; проверка `owner is None or
   owner != publisher` (`telemetry.py:606-610`) удаляется вместе с `rejected`-веткой.
3. Гейт: матчинг остаётся по ИМЕНИ ЛИСТА (суффиксу) — существующие правила конфига работают без
   миграции; glob-язык — Ф4, не здесь.
4. `observability_declarations.py`: у метрик снимается семантика владения — `metric_owners`
   (`:249`) и `ValueError` двух владельцев (`:102-111`, для KIND_METRIC) удаляются; каталог имён
   (`declared_metrics`, `gated_metrics`) остаётся — им живут гейт и авто-строки GUI
   (`_telemetry_controls.py:9`). Повторное объявление того же имени — идемпотентный no-op.
5. `_warn_rejected_levels` + `_warned_rejected_levels` (`process_heartbeat.py:75, 825`) удаляются:
   отсеивать больше нечего. Голос «публикация без объявления» НЕ заводится — необъявленное имя
   легально едет под дефолтным правилом гейта (та же логика, что у `resolve()` — тотальна).
6. Старое поимённое снятие ВЫРЕЗАЕТСЯ здесь же, вместе с арбитражем (блокер Б2 ревью): его
   Ф0-фильтр стоит на `metric_owners` (удаляется шагом 4), а писатель надгробий
   (`process_heartbeat.py:795-823`) кладёт плоское `state[имя] = None` со стражем
   `if name not in state` — во вложенной форме страж ВСЕГДА истинен для плагинных имён, и
   надгробие легло бы на плоский путь при живом писателе. Интерим-механизма не заводится:
   снятие возвращается в Ф2 поддеревом, до неё Ф1 не поставляется (см. заголовок фазы).
7. Poll (`current_levels_snapshot`) отдаёт ту же вложенную форму — push и poll остаются одним
   сборщиком (инвариант ADR-PM-035 сохраняется).
8. Удалить тесты умершего механизма (список — §9, блок Ф1), взамен — авторские hazard-тесты
   новой формы (потокобезопасность per-писатель, вложенная проекция, гейт по суффиксу).
**Acceptance criteria:**
- [x] в `heartbeat/` не осталось ни `metric_owners`, ни сравнения владельца с публикатором —
      `grep -E "metric_owner"` вне тестов пуст; `_warn_rejected_levels`, `_warned_rejected_levels`,
      `RETRACTION_REASSERT_TICKS`, `pending_retractions`, `confirm_retracted`, `owned_now`,
      `PluginLevels.snapshot()` — ноль вхождений (сверено ревью независимо)
- [x] два писателя с одинаковым именем листа дают ДВА листа в двух поддеревьях, оба с литералами —
      приёмка тестера `TestTwoWritersSameLeafName` (push и poll), 7/7 зелёные; инъекция «ключевание
      писателем снято» убивает 10 из 20 авторских hazard и 2 из 7 тестерских
- [x] правила гейта из прод-конфига работают без единой правки конфига — на нетронутом
      `system.yaml`: `fps=777.5` проходит, `unknown_probe_metric_xyz=888.5` не проходит (пара
      снята и тестером, и авторским `TestProdGateSectionWorksUnedited`); инъекция «гейт пропускает
      всё» красит ровно 1 тестерский тест
**Out of scope:** механизм снятия поддеревом (приходит в Ф2; старое снятие вырезано шагом 6,
интерима НЕТ — прежняя формулировка «до Ф2 работает поимённое снятие с Ф0-фильтром» была ложной
посылкой, её вскрыло ревью: фильтр Ф0 умирает вместе с `metric_owners`); менеджер-слот (Ф3).

### Task 1.3 — Приёмка фазы независимым тестером
**Level:** Middle+ · **Assignee:** tester
**Goal:** Приёмка неймспейса от критериев, по правилам §3.
**Files:** `multiprocess_framework/modules/process_module/tests/test_observation_namespace_acceptance.py` (новый)
**Steps:** критерии:
- Н1: плагин P публикует `x=11.0` → лист `processes.<proc>.state.plugins.P.x == 11.0` (push и poll);
- Н2: два плагина публикуют одноимённое `x` → два листа, каждый со своим литералом, ни один merge
  не содержит значения одного под путём другого;
- Н3: порядок публикаций не меняет итог (обе перестановки, оба литерала на месте);
- Н4: capture-совместимость: `Plugins/sources/capture/plugin.py` НЕ ИЗМЕНЁН (git-диффом), а его
  три метрики (`plugin.py:359-361`) видны под `state.plugins.<имя>.{capture_fps,frame_count,drops}`;
- Н5 (М2): обход `processes.<proc>.state` одним `state_get_subtree`-эквивалентом находит все
  опубликованные листья, включая свежедобавленного писателя из самого теста (ноль правок механизма — М1).
**Acceptance criteria:**
- [x] предсказания записаны до прогона; инъекции рода 1 (вернуть плоскую публикацию, перепутать
  писателя в пути) и рода 2 («сборщик пуст», «сборщик пропускает всё») — против файла тестера;
  под «пусто» ни один тест с отрицанием не выживает — **10 инъекций из 10 легли в предсказание**
  (FLAT / SWAP / COLLECTOR-BLIND / PORT-MUTE → 11 красных из 12; MERGE-OFF / PUSH-DEAD → 8, только
  push; POLL-DEAD → 3, только poll; пересечение push- и poll-наборов ПУСТО, то есть «опрос отдаёт
  то же, что push» проверяется, а не декларируется). Под «пусто» выжил единственный тест —
  сверка `git diff` capture-плагина, у которого отрицаний о механизме нет
- [x] раздел «недостижимо на стенде» заполнен (минимум: гейт, если стенд его не строит) — и
  **подтверждён измерением**: инъекции «гейт пропускает всё» (GATE-OPEN) и «гейт не получает
  необъявленные имена» (EXTRA-STARVED) не покрасили НИЧЕГО, то есть активного гейта на стенде
  тестера действительно нет. Дыра не остаётся открытой: гейт на НЕТРОНУТОМ прод-конфиге снят
  приёмкой Task 1.2 (`test_writer_subtree_acceptance.py::TestProdGateRulesWorkUnedited`)

**Инъекции рода 2 сгенерированы вслепую** — отдельным агентом по докстрингам механизма, до прогона
тестера и без доступа к критериям Н1–Н5 (§3.2). Он же назвал три инъекции, которые предложил НЕ
гонять, потому что они воспроизводят форму дефекта, а не механизм: «сломать снятие» (механизма
снятия между Ф1 и Ф2 нет вовсе), «вернуть ValueError двух владельцев» (несущей половиной арбитража
была сверка в сборщике, её больше нет) и переименование ключа поддерева — последнее прогнано как
ЗОНД, и зонд сработал: poll-тесты пережили смену адреса, потому что суффиксный поиск не пришпиливал
сегмент `plugins`. После правки тестера тот же зонд даёт 11 красных вместо 8.

**Известное ограничение файла приёмки:** `test_capture_plugin_file_is_byte_for_byte_unchanged_vs_main`
одноразов и привязан к фазе — после merge Ф1+Ф2 в `main` он станет тавтологией и подлежит удалению,
а не починке. Пропускается с явной причиной там, где локального рефа `main` нет.
**Тестеру запрещено:** `heartbeat/telemetry.py`, `heartbeat/process_heartbeat.py`, дифф Ф1,
авторские тесты Ф1, `DECISIONS.md`, этот план (кроме процитированных критериев).
**Out of scope:** тесты снятия (Ф2).

### Task 1.4 — Миграция читателей: read-model и GUI
**Level:** Middle · **Assignee:** developer
**Goal:** Единственный читатель GUI понимает поддерево `plugins.*`; фреймворковые суффиксы не тронуты.
**Files:** `multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py`
(+ его тесты), `multiprocess_prototype/frontend/widgets/tabs/processes/_telemetry_controls.py`,
`multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/cam_actual_section.py`,
`multiprocess_prototype/backend/state/manager_setup.py`,
**`multiprocess_framework/modules/process_manager_module/core/alert_rules.py`** +
`.../monitor/process_monitor.py` + `.../tests/test_alerting.py`,
`multiprocess_prototype/backend/state/bootstrap.py`,
`multiprocess_framework/modules/process_module/managers/telemetry_reload.py`
*(список дополнен по ревью Task 1.2: раньше здесь стояли двое, а инвентарь Task 1.1 нашёл шестерых —
и `alert_rules.py` не входил в Files НИ ОДНОЙ задачи, то есть план его починить не мог в принципе)*
**Steps:**
1. К суффиксам `:49-51` добавить обход `.state.plugins.<писатель>.<метрика>` — строка метрики
   получает писателя как источник (ADR-136 — read-model остаётся единственным читателем).
2. DB-sink: решение уже принято, СТОПа здесь нет — см. §10. Ключ стока **по пути**
   (`Plugins/io/telemetry_sink/plugin.py:221-226`: `_extra[".".join(parts[2:])]`), поэтому
   `_extra`-истории плагинных метрик рвутся на флипе; разрыв принят владельцем 2026-08-19 как
   осознанная цена. Колонки `fps`/`latency_ms` не задеты. Task 1.1 ищет только НЕИЗВЕСТНЫХ
   читателей — сток к ним не относится.
   *(Правка по второму проходу ревью: здесь оставался хвост старой гипотезы «ключ по имени листа»
   вместе с воскрешённым стопом — два ответа в одном документе, тот самый класс, с которым план
   борется.)*
3. Переходный период — НЕТ: двойная публикация (плоско + поддерево) запрещена, она возвращает
   двух писателей одного листа — ровно тот класс, который хороним. Флип атомарный, в одной ветке
   с Task 1.2.
4. **Правило супервизии `drops_growing` — БЛОКЕР, найден ревью Task 1.2.**
   `alert_rules.py:104` читает `processes.{process}.state.drops` точным путём; после Ф1 лист лежит
   на `state.plugins.capture.drops`, оба кандидата резолвятся в `None`, `_check_counter_alerts`
   (`process_monitor.py:383`) делает `continue` — алерт «дропы растут» не сработает НИКОГДА, при
   `FW_SUPERVISOR_ALERTS` по умолчанию включённом. Воспроизведено ревью на настоящем `TreeStore`:
   дерево `{'state': {'plugins': {'capture': {'drops': 7}}}}`, оба запроса правила → `None`,
   фактический лист → 7. Починить путь И **переписать сторож**: `test_alerting.py:48` сверяет
   строковую константу в `DEFAULT_RULES` и потому остался ЗЕЛЁНЫМ на мёртвом правиле — шпион на
   имени, а не на свойстве. Новый сторож обязан заполнить `TreeStore` выхлопом настоящего тика и
   убедиться, что `_read_state_int` вернул число.
5. **Предохранитель троттла** (`manager_setup.py:54,57,58`): правила
   `processes.**.state.{capture_fps,frame_count,drops}` после Ф1 не матчат ничего (измерено ревью:
   новый путь → пустой список правил, агрегат `state.fps` цел). Publisher-гейт частоту держит, так
   что это потеря второго эшелона, — но либо дописать правила под новым путём здесь, либо явно
   записать, что предохранитель снят до Ф4, и не делать вид, что он есть.
6. **Засев `bootstrap.py:64-70`** кладёт плоский `frame_count: None` каждому процессу: после Ф1 его
   больше некому перетереть, и он остаётся вечным листом-призраком рядом с настоящим. Убрать —
   либо оставить с записанным доводом. Регенерация golden сборки идёт В ПАРЕ с этой правкой,
   иначе корневой гейт покраснеет (снапшоты пиннят засев).
7. `telemetry_reload.py` (`_central_rule_for_metric`, `:212`) матчит правило по последнему сегменту
   — мёртвый глоб продолжит рапортоваться действующим потолком через `detect_throttle_caps` (`:281`).
**Acceptance criteria:**
- [x] **`drops_growing` стреляет на живом стенде** — с ОДНОЙ честной оговоркой, названной, а не
  замолчанной. Сторож переписан на наблюдаемый эффект (настоящий тик → настоящий
  `StateStoreManager` → настоящий `_check_counter_alerts` → алерт в дереве), прежняя сверка
  строковой константы удалена. На живом стенде (`webcam_sketch`, 8 процессов, `BACKEND_CTL=1`)
  **сам `drops` спровоцировать нельзя**: он растёт только когда `camera.read()` не вернул кадр
  (`Plugins/sources/capture/plugin.py:189`), пауза потребителя его не двигает — измерено, `drops`
  простоял 0 при `frame_count` 766 → 3208. Поэтому механизм доказан живьём ВРЕМЕННЫМ правилом на
  той же форме адреса (`processes.{process}.state.plugins.*.frame_count`, счётчик растёт ~21/с):
  `system.alerts.camera_0` получил `severity: warning`, `reason: «счётчик вырос на 109 (сейчас
  524)»`. **Пара-контроль — в том же снимке:** `drops_growing` в алертах ОТСУТСТВУЕТ, потому что
  роста нет. Одним замером сняты оба исхода на одной форме адреса. Временное правило и расширение
  белого списка откачены, проверено `git status`
- [x] живой стенд (`backend_ctl`): `introspect_telemetry` отдаёт **вложенную форму** —
  `levels.state.plugins.capture = {capture_fps: 21.3, frame_count: 766, drops: 0}`, рядом плоские
  агрегаты фреймворка `fps: 21.4`, `latency_ms: 47.0`; push-дорога подтверждена отдельно —
  `state_get_subtree('processes.camera_0.state')` содержит `plugins.capture.*` и **не содержит
  плоского `frame_count`**, то есть засев-призрак снят живьём, а не только в тестах.
  **Стенд поднимался с расширенным белым списком** (`capture_fps`/`frame_count`/`drops` временно
  добавлены в `telemetry.publish.metrics`) — ровно та развилка, которую критерий предусматривал;
  расширение откачено. GUI-строка живьём НЕ проверена (оффскрин, без `QT_MCP_PROBE`) —
  проверен боевой матчер глоба и тесты виджетов
- [x] тесты read-model: старые фреймворковые суффиксы + новые plugin-пути, с литералами — 58 тестов
  модуля зелёные, из них 15 новых hazard про свёртку и кольцо истории
**Out of scope:** правки sink-схемы БД (если понадобятся — отдельная задача по итогам 1.1).

### Task 1.5 — Ревью фазы
**Level:** Senior+ · **Assignee:** reviewer (синхронно)

> **Состояние на 2026-08-20.** Ревью Task 1.4 прогнано синхронно и вернуло CHANGES REQUESTED с
> девятью находками, каждая с воспроизведением; итерация 1 из 2 закрыла все (коммит `465c7365`).
> Несущая: узость свёртки read-model не сторожилась ничем — обе половины проверки снимались с НУЛЁМ
> красных, а половина про `plugins` держит живой адрес `state.cam.actual.fps` от сворачивания в
> суффикс агрегата. Вторая по весу: read-model была СЛЕПА к производителю — переименование
> `PLUGINS_SUBTREE_KEY` красило шесть тестов в `process_manager_module` и ноль в её собственных.
> Реализатор аргументированно отверг предложенное ревью лекарство (импорт константы в чистый
> модуль правил и в generic read-model — зависимость наоборот) и закрыл измеренную дыру тестом
> против настоящего выхлопа производителя. Мои инъекции на новые свойства: K1/K2/K3 — ровно по
> одному красному, именно на названных тестах. K4 сначала дала НОЛЬ, и промах был мой — заменил
> ТЕКСТ сообщения, оставив вызов, то есть воспроизвёл форму, а не механизм; при снятии всей ветки
> отказа — ровно 1 красный. Побочно вскрылось, что тест сверял только факт вызова: усилен до сверки
> содержимого (соло, одна строка), после чего первая, промахнувшаяся инъекция его тоже красит.
**Goal:** Вердикт с воспроизведениями; отдельно — подтверждение удалений (grep-чек, что арбитраж
не жив под другим именем) и прогон инъекции рода 2 своей рукой.
**Acceptance criteria:**
- [x] **Вердикт фазового ревью: CHANGES REQUESTED, итерация 1 из 2, все пять находок закрыты**
  (коммиты `05e4dd58`, `5a80c373`, `0dd72ca9`). Каждая пришла с воспроизведением вход→выход.
  Несущая — **красная база, которую не видел ни один гейт**: `test_plugin_subtree_history_hazards.py`
  в `finally` снимал объявление `fps` безусловно, а `fps` объявляет ФРЕЙМВОРК импортом
  (`heartbeat/telemetry.py:39`); с Ф1 повторное объявление — идемпотентный no-op, то есть тест
  ничего не добавлял и только разрушал каталог процесса. Красило соседа
  (`test_rt2_config_flip_acceptance`) **только в совмещённом прогоне**: нарушитель и жертва лежат
  в разных `testpaths`, и оба гейта по отдельности зелены. Вторая по весу — `process_module`
  оказался единственным модулем-носителем механизма, чьи `.md` ветка не тронула: README держал
  «Правило второе: публикуй в СВОЁ имя… ключуется парой `(имя, публикатор)`» как действующее.
  Остальные три: обещание `alert_rules` про плоских кандидатов (работают только пока порт молчит
  — воспроизведено: при `plugins.capture.drops=0` рост плоского 100 → 900 монитор видит как 0),
  три протухших текста (`backend_ctl/driver.py` утверждал, что `frame_count`/`drops` опросом не
  приходят, и спорил с `mcp_tools.py`), и фейк-харнесс тестов камерной секции
- [x] **удаления §9-Ф1 подтверждены grep'ом**: `metric_owner`/`metric_owners`,
  `RETRACTION_REASSERT_TICKS`, `pending_retractions`, `confirm_retracted`, `_retracted`, парный
  ключ, `rejected`-тройки, голос про самозванца, `owned_now` — вне тестов и надгробных докстрингов
  ноль вхождений. Четыре файла тестов удалённого механизма удалены (`git diff --diff-filter=D`),
  в рабочем дереве от них остались только `.pyc`. `ValueError` двух владельцев снят у метрик и
  осознанно оставлен у лог-источников (расхождение названо в шапке `_declare`). Д4 не срезан.
  **Арбитраж не жив под другим именем** — проверены четыре кандидата на эквивалентную механику:
  свёртка read-model (ключ кольца — ПОЛНЫЙ путь, два писателя = два кольца), `TelemetryGate._next_due`
  (ключ — имя листа, оба писателя проходят или не проходят вместе), `_read_state_int_sum` (сумма,
  не выбор), `_plugin_readout` (печатает всех). Единственный остаток — одна метка GUI, см. ниже
- [x] **live-прогон capture процитирован числами** — снят в Task 1.4 и здесь НЕ переизмерялся
  (бэкенд не поднят, `WinError 10061`; поднимать ради цитаты значило бы рискнуть вторым стендом):
  `levels.state.plugins.capture = {capture_fps: 21.3, frame_count: 766, drops: 0}`, рядом плоские
  `fps: 21.4`, `latency_ms: 47.0`; алерт `severity: warning`, `reason: «счётчик вырос на 109
  (сейчас 524)»`; пара-контроль `drops_growing` в тех же алертах отсутствует. Форму опроса ревьюер
  подтвердил в процессе заново, проводку до стенда — нет, и это сказано явно

#### Матрица инъекций рода 2 — 18 инъекций, сгенерированы ЧУЖОЙ РУКОЙ вслепую

Генератор (отдельный агент) читал только исходники десяти файлов механизма; план, каталоги
`tests/`, `DECISIONS.md` и история git были ему запрещены. Он честно признал единственную
утечку: докстринги РАЗРЕШЁННЫХ файлов называют тесты по именам, то есть факт существования
сторожа в пяти местах ему был известен (содержания — нет). Прогон — мой, в отдельном worktree
от закоммиченного HEAD, предсказания записаны ДО прогона.

**Результат: 8 предсказаний из 18.** Запись честная — это плохой счёт, и промахи однородны:
девять из десяти в сторону ЗАНИЖЕНИЯ (покрытие плотнее, чем я думал: `POLL-LEVELS-UNPLUGGED` 18
против 3–6, `WRITER-COLLAPSE` 55 против 20–40, `TRACKED-ALWAYS-TRUE` 11 против 1–3,
`B1-WILDCARD-SUM-NULL` 21 против 6–10). Два занижения в другую сторону названы отдельно ниже —
именно они и есть содержательный выход матрицы.

**Вакуумная инъекция ровно одна, и она предсказана: `COUNTER-ALERTS-UNPLUGGED` — 0 красных.**
Снятие единственного боевого вызова `self._check_counter_alerts()` из `_run_iteration`
(`process_monitor.py:736`) оставило ЗЕЛЁНЫМИ все 4297 тестов охвата фазы: каждый сторож — а их
больше тридцати — звал хелпер напрямую. Правило было бы исправно и не вызывалось бы никогда.
Закрыто тестом на настоящую итерацию монитора (`0dd72ca9`); повторная инъекция поверх него даёт
**ровно 1 красный, и это он** — то есть дыра закрыта и закрыта единственным сторожем.

**Тонкий сторож, найденный заодно:** `LEVELS-EXTRA-UNPLUGGED` (гейт перестаёт получать реальные
имена листьев, необъявленное имя тихо не едет) красит РОВНО ОДИН тест —
`test_writer_subtree_acceptance.py::TestUndeclaredNameRidesLegally`. Не ноль, но свойство «публиковать
можно без объявления» держится на одной нитке. `B3-GATE-ALLOWS-ALL` — 3 красных против ожидаемых
5–15; механизм до-Ф1, в предмет фазы не входит, но записан как наблюдение.

**Инъекции против собственных новых тестов** (камерная секция, отдельный worktree): снятие
глоб-матчинга ТОЛЬКО на дороге доставки дало **ровно 3 красных — все три новых теста, все десять
старых зелёные**. Это и есть доказательство находки 5: прежний файл сверял строку адреса в фейке
и разрыва доставки не видел. Вторая инъекция (снять подписку целиком) — 8 красных против
предсказанных 6, промах мой: забыл про два теста баланса `bind`/`unbind`.

**Оговорка о чистоте прогонов 14, 15 и B1:** они шли 880/800/650 с вместо ~90 с — параллельно
работал реиндекс qex (парсинг tree-sitter — CPU, на GPU только эмбеддинг). Числа проверены:
инъекция №14 дала 8 красных, столько же независимо намерил отдельный прогон в третьем worktree.

**Гейты на принимаемом HEAD `0dd72ca9`:** фреймворковый — **8641 passed / 8 skipped / 1 xfailed**,
корневой — **7034 passed / 64 skipped**, `scripts/validate.py` — чисто.

#### Резидуалы Ф1 — названы, не запланированы

1. **Заслон плоских кандидатов `drops_growing`.** Плоский кандидат не спрашивается никогда, если
   порт по этому имени публикует хоть ноль. Сегодня латентно (прямого писателя плоского
   `state.drops` в `Plugins/` нет). Лечится суммированием обеих форм, а это меняет форму
   `_counter_baseline` — отдельная задача. Обещание в коде квалифицировано (`5a80c373`).
2. **Одна метка GUI сводит писателей обратно.** `cam_actual_section` биндит
   `plugins.*.capture_fps` в один QLabel: два писателя → побеждает последняя дельта, имя писателя
   не видно. Соседний `_telemetry_controls._plugin_readout` на тот же вопрос отвечает иначе.
   Довод («секция показывается только для камерной ноды, второго писателя рецепты не заводят») и
   лекарство (`GuiStateBindings.bind_fanout`) записаны в тесте, поведение зафиксировано красным.
3. **Базовая линия супервизии по писателю** (из Task 1.4): писатель, пришедший с ненулевым
   накопленным счётчиком, даёт ложный алерт.
4. **`forget_declarations(names=...)` молча снимает чужое объявление.** Класс дефекта из находки 1
   системный: узор `before = set(declared_metrics())` знают не все файлы. Стоит рассмотреть
   громкий отказ на имени, объявленном не звавшим.

---

## Ф2 — снятие = поддерево писателя (вторая половина неделимой поставки Ф1+Ф2)

**Цель фазы:** ушедший писатель исчезает из дерева удалением поддерева; поимённая бухгалтерия
снятия удалена. **Видимый результат на стенде — ДВУМЯ объективами** (урок S-8: критерий тем же
объективом, что механизм, дыру не видит): (а) стор — стоп capture → `state.plugins.capture`
исчезает целиком за ≤3 тика (`backend_ctl state_get`), соседние писатели не шелохнулись;
(б) сток — ключи ушедшего писателя исчезают из строк БД за ≤1 семпл.

### Task 2.0 — Инвентарь потребителей дельты-корня (стоп-условие фазы, по образцу Task 1.1)
**Level:** Middle · **Assignee:** developer
**Goal:** Удаление поддерева рождает ОДНУ дельту на корень (`TreeStore.delete`,
`state_store_module/core/tree_store.py:346-352`) — каждый, кто чистит своё состояние по ТОЧНОМУ
пути листа, обязан быть найден и получить вердикт до включения механизма.
**Files:** результат — таблица в этом плане; кода не трогает.
**Steps:**
1. Проверенные ревью плана: `StateProxy._update_cache` → `self._cache.pop(delta.path, None)`
   (`state_store_module/proxy/state_proxy.py:914-916`) — чистит ТОЧЕЧНО: merge порождает
   по-листовые дельты, кэш держит листовые пути, и дельта корня их не выбьет; сток
   `Plugins/io/telemetry_sink/plugin.py:162-166` — так же точечно (без правки он бессрочно пишет
   последние числа ушедшего писателя); read-model `_purge_subtree` — чистит по ПРЕФИКСУ, готов.
2. Найти остальных подписчиков дельт/MISSING (`subscribe`, обработчики дельт) за пределами трёх
   названных — grep + `qex:search_code`.
3. Вердикт каждому: «чистит по префиксу — готов» / «нужна префикс-чистка (Task 2.1 для кэша
   прокси, Task 2.3 для стока)» / «неизвестный — СТОП фазы».
**Acceptance criteria:**
- [x] таблица потребителей с вердиктами в плане (bd678248). **ПОПРАВКА ревью 2026-08-23:**
  заявление «неизвестных 0» строго НЕВЕРНО — независимый свип нашёл два сайта того же
  класса вне таблицы: `backend_ctl/conditions.py:248,296` (`_setup_state_path`,
  `_setup_metric_threshold`) фильтруют дельты ТОЧНЫМ сравнением пути, поэтому
  MISSING-дельта корня-предка для них невидима и условие досиживает до таймаута
  вместо диагноза «deleted». Ф2 это не блокирует (инструмент диагностики, не боевой
  кэш), но таблицу дополнить. Прочие 14 строк ревью подтвердило.
**Out of scope:** правки потребителей (Task 2.1 / Task 2.3).

#### Результат Task 2.0 — таблица потребителей (снято 2026-08-23)

**Якоря трёх заявленных плану сверены с HEAD `48d4ed09` — разошлись только вторым знаком, смысл
не изменился.** `TreeStore.delete` конструирует ОДНУ `Delta` на `return` (`core/tree_store.py:346-353`,
план указывал `346-352` — на одну строку короче, тот же блок). `StateProxy._update_cache` — метод
с `902`, точечный `pop(delta.path, None)` на `915` (план: `914-916`, диапазон верный, точная строка
на единицу ниже центра). `Plugins/io/telemetry_sink/plugin.py._on_deltas` — метод с `154`, точечный
`pop` на `164` (план: `162-166`, диапазон верный, `is_delete` на `163`). `TelemetryReadModel._purge_subtree`
подтверждён на `256` (вызов из `ingest(deleted=True)` — `232`): чистит по границе `path` /
`path + "."`, готов.

**Поиск остальных.** `qex:search_code` по «subscribe to state store delta path cache pop» дал
только сам `Delta`/тесты (индекс не разрешил по символам) — рабочим инструментом оказался grep по
`\.subscribe\(` и `is_delete|delta\.path|new_value is MISSING` на весь репозиторий
(`multiprocess_framework/`, `Services/`, `Plugins/`, `multiprocess_prototype/`, `backend_ctl/`),
затем ручная проверка каждого файла (что подписка держит, как чистит). Найдено **14 потребителей
дельт/MISSING** (включая три названных плану) — **11 новых плану неизвестны**. Неизвестных
(«нельзя установить чтением») — **0**: поведение каждого определено чтением callback'а.

| Потребитель (`файл:строка`) | Что держит / делает | Вердикт |
|---|---|---|
| `state_store_module/proxy/state_proxy.py:902-917` (`_update_cache`, pop `:915`) | Клиентский кэш прокси: `pop(delta.path, None)` — точечно | **нужна префикс-чистка → Task 2.1** (уже в плане) |
| `Plugins/io/telemetry_sink/plugin.py:154-166` (`_on_deltas`, pop `:164`) | Кэш стока перед семплом: `pop(d.path, None)` — точечно | **нужна префикс-чистка → Task 2.3** (уже в плане) |
| `telemetry_readmodel_module/telemetry_read_model.py:213-238,256-278` (`ingest(deleted=True)` → `_purge_subtree`) | Снимок/история/`_push_seq` read-model | **чистит по префиксу — готов** (уже в плане) |
| `frontend_module/state/telemetry_view_model.py:154-168` (`on_state_delta`, накопитель `_pending`) | Батч-буфер Qt-сигнала `updated`: `_pending[path] = _REMOVED`, сбрасывается КАЖДЫЙ тик (`_flush`, `:211-218`); долгоживущее состояние — делегат в `TelemetryReadModel` (строка выше) | **готов** — тонкий passthrough, сам не кэширует дольше одного тика; риск уже закрыт read-model'ю |
| `multiprocess_prototype/frontend/state/bindings.py:407-483` (`GuiStateBindings._on_state_msg`) — `match_glob(handle.pattern, path)` точным путём дельты | Реестр `bind()`/`bind_fanout()` виджетов по glob-паттерну; при `deleted=True` без точного совпадения паттерна с `delta.path` виджет НЕ трогается (заморозка на последнем значении) | **тот же класс дефекта, что у прокси/стока, но НЕ задет сегодня**: grep всех вызовов `.bind(`/`.bind_fanout(` в `frontend/` — ни один не адресует `processes.*.state.plugins.*`. **НОВЫЙ адресат вне периметра Ф2** — при появлении виджета, привязанного напрямую к листу под `state.plugins.<писатель>`, точечный `match_glob` пропустит удаление корня. Называю вслух, не блокирую (replay при `bind()` берёт снимок из уже безопасного `TelemetryReadModel` — `:170-178`, живой канал `_on_state_msg` — нет) |
| `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py:587-595,1208-1245` (`_vm_setters` в `ProcessesPanel`/`SingleProcessPanel`) | Статический словарь `{точный_путь: setter}`, наполняется ОДИН раз в конструкторе, не растёт от дельт | **не задет структурно**: ключи — только framework-агрегаты (`state.fps/latency_ms/uptime`, `system.*`), под `state.plugins.<писатель>` сеттеров нет вообще (grep подтверждён) |
| `multiprocess_prototype/backend/state/adapters/registers_adapter.py:24-214` (`RegistersStateAdapter`, `_reverse_mapping`) | Обратный маппинг `state_path → (register, field)`, подписка `"**"`, точный `dict.get(path)` (`:203`) | **нужна префикс-чистка (тот же класс), НО неиспользуемый путь**: класс НЕ инстанцируется нигде в проде (только докстринг-пример и smoke-тест) — грамкая квалификация по правилу «нет вызывающих ≠ не нужен», фазу не блокирует |
| `multiprocess_prototype/backend/state/adapters/camera_state_adapter.py:188-226` (`_on_state_deltas`, `self._camera_states`) | Локальный кэш `{camera_id: {field: value}}`; матч `_CAMERA_STATE_RE` — при несовпадении (делит корня короче листа) `continue`, кэш НЕ чистится (`:203-205`, воспроизведено чтением) | **нужна префикс-чистка (тот же класс), НО неиспользуемый путь**: `CameraStateAdapter` нигде не инстанцируется в проде (только тесты) — квалифицирую громко, не блокирую |
| `multiprocess_prototype/backend/state/adapters/display_state_adapter.py:71-93,158-` (`_on_state_deltas`) | Подписка `displays.*.status` — терминальный лист (детей глубже `.status` не существует по схеме) | **готов структурно** (уязвимого поддерева нет); также неиспользуемый путь в проде (только тесты) |
| `multiprocess_prototype/backend/state/adapters/service_state_adapter.py:31-93` (`ServiceStateAdapter`) | Подписка `services.*.status` — терминальный лист; **подключён в проде** (`frontend/app.py:452`) | **готов структурно, вне периметра Ф2** (домен `services`, не `processes.*.state.plugins.*`) |
| `multiprocess_prototype/backend/state/adapters/recipe_adapter.py:34-90` (`RecipeStateAdapter`) | Подписка на ровно `recipes.active` — один путь, детей нет; **подключён в проде** (`frontend/app.py:507`) | **готов структурно, вне периметра Ф2** |
| `multiprocess_prototype/frontend/bridge/topology_bridge.py:268-283` (`TopologyBridge.on_state_delta`) | Не кэширует — форвардит `processes.<P>.config.<field>` в `RegistersManager.set_value`; ветка `state.plugins.*` явно не парсится (комментарий `:283`) | **вне периметра**: другое поддерево (`config`, не `state.plugins`), и не кэш-потребитель |
| `state_store_module/selectors/selector.py:228-263` (`SelectorRegistry.handle_delta`, `Selector.cached_value`) | `_find_affected` матчит `delta.path` о паттерн ЗАВИСИМОСТИ фиксированной глубины; корень-делит короче паттерна зависимости — селектор не пересчитается, `cached_value`/опубликованный `selectors.<name>` замирают | **тот же класс дефекта, НО неиспользуемый путь**: `SelectorRegistry`/`Selector` нигде не инстанцируются в `multiprocess_prototype`/`Services`/`Plugins` (только тесты фреймворка) — квалифицирую громко, не блокирую. **Отдельно:** `unregister()` сам зовёт `_store.delete(f"selectors.{name}")` (`:207`) — но публикует значения через `set()` (не `merge()`), поэтому НИКОГДА не создаёт многолистовое поддерево под `selectors.<name>` — единственная когда-либо испущенная дельта совпадает с той, что чистит `pop`; для этого конкретного вызывающего риска нет вообще |
| `state_store_module/persistence/persistence_manager.py` (`PersistenceMiddleware`, `after_set`/`after_merge` определены, `after_delete` — НЕТ, наследуется no-op база `middleware/base.py:97-99`) | Debounced YAML-персист секций дерева, помечает `dirty` только на `after_set`/`after_merge` | **НОВАЯ находка — отдельный подкласс того же корня («корень-делит теряется»), но не «точечный кэш», а «пропущенный хук»**: удаление узла НИКОГДА не помечает секцию dirty → персист не увидит исчезновение → при рестарте узел ресуррект(ир)уется из старого YAML. **Неиспользуемый путь**: `PersistenceManager`/`PersistenceMiddleware` не инстанцируются нигде вне `state_store_module` (не в `multiprocess_prototype`) — квалифицирую громко, фазу не блокирует, но это самостоятельный дефект framework-модуля, достойный отдельного тикета вне периметра этого плана |

**Итог по числам.** Найдено потребителей дельт/MISSING всего — **14**. Планом не покрыто (т.е. новых
для Task 2.0) — **11** из 14. Из них: 2 требуют реальной доработки живого прод-кода помимо уже
названных Task 2.1/2.3 (`GuiStateBindings` и статические `_vm_setters` — но оба **структурно не
задеты сегодня**, т.к. ни один виджет не привязан под `state.plugins.<писатель>`); 4 несут тот же
класс дефекта, но код мёртв (не инстанцируется в проде) — `RegistersStateAdapter`, `CameraStateAdapter`,
`SelectorRegistry`, `PersistenceMiddleware`; 5 безопасны структурно или вне периметра
(`TelemetryViewModel._pending`, `DisplayStateAdapter`, `ServiceStateAdapter`, `RecipeStateAdapter`,
`TopologyBridge`). **Неизвестных («нельзя установить чтением») — 0.**

**Вердикт: стоп-условие фазы СНЯТО.** Ни один потребитель не остался неопределённым; два новых
находки (`GuiStateBindings`, dead-code адаптеры/`PersistenceMiddleware`) названы громко по правилу
владельца («нет вызывающих ≠ не нужен»), но ни один не задет живым механизмом Ф2 (единственный
источник root-delete по плану — `processes.{p}.state.plugins.{писатель}` через будущий
`proxy.delete()` из Task 2.1/2.2), поэтому фаза продолжается без расширения периметра Task 2.1/2.3.

### Task 2.1 — `StateProxy.delete` — достроить существующую дорогу
**Level:** Middle+ · **Assignee:** developer
**Goal:** У `StateProxy` появляется `delete(path)` — зеркало `set` — поверх УЖЕ существующего
маршрута `state.delete`.
**Files:** `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py`,
`.../state_store_module/interfaces.py`, тесты модуля
**Steps:**
1. Кирпичи, всё готово на приёмной стороне: `TreeStore.delete` (`core/tree_store.py:323`),
   обработчик `handle_state_delete` (`manager/state_store_manager.py:281`), маршрут `state.delete`
   (`:624, :654`), прун троттла при delete (`middleware/throttle.py:28`). Не хватает только метода
   на прокси (`proxy/state_proxy.py` — есть `set:142`, `merge:162`, `subscribe:262`).
2. Метод по форме `set`: тот же транспорт, тот же source. Ponytail-заметка в
   `process_heartbeat.py:779-781` прямо заказывала этот апгрейд «когда появится читатель» —
   читатель появился (порт, teardown писателя).
3. Кэш прокси — префикс-чистка на дельте корня (вердикт Task 2.0): `_update_cache`
   (`proxy/state_proxy.py:914-916`) сегодня делает точечный `pop(delta.path)`; MISSING-дельта
   поддерева обязана выбивать ВСЕ листовые ключи под этим корнем (образец — `_purge_subtree`
   read-model; граница — точка-разделитель, чтобы `plugins.cap` не задел `plugins.cap2`).
**Acceptance criteria:**
- [x] (1354b4f7) delete с прокси удаляет поддерево у живого StateStoreManager (интеграционный тест модуля);
  идемпотентен (повтор по отсутствующему пути — не ошибка); дельта-подписчики получают удаление
- [x] (1354b4f7) кэш прокси после дельты корня не отдаёт НИ ОДИН листовой путь из-под него (якорь: до
  удаления кэш отдаёт литерал; сосед с общим текстовым префиксом — жив)
- [x] (1354b4f7) инъекции: род 1 — delete шлёт не тот путь; род 2 — delete «молча теряется» (тест обязан
  отличить доставленное удаление от потерянного — якорь: подписка на дельту) и «префикс-чистка
  чистит точечно» (возврат `pop(delta.path)` — кэш-тест краснеет)
**Out of scope:** прун троттла (уже есть); GUI-прокси; сток (Task 2.3).

### Task 2.2 — Снятие по писателю, бухгалтерия по имени — удалена
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Порт помнит ушедших ПИСАТЕЛЕЙ; тик утверждает удаление их поддеревьев с конечным
запасом на потерю доставки; `_retracted`/`pending_retractions`/`confirm_retracted`/
`RETRACTION_REASSERT_TICKS` удалены.
**Files:** `.../heartbeat/telemetry.py`, `.../heartbeat/process_heartbeat.py`
**Steps:**
1. `retract(писатель)` → `_departed[писатель] = K` (K=3 — тот же довод конечного запаса, что в
   S-1: повтор конечен, тратится только на успехе; довод переезжает в докстринг).
2. Тик: для каждого departed — `proxy.delete(f"processes.{p}.state.plugins.{писатель}")`; успех →
  декремент; исключение → запас не тратится. `publish` живого писателя убирает ЕГО ключ из
  `_departed` — пары «имя ↔ чужой писатель» больше не существует нигде, отравление невозможно
  по построению.
3. Удалить: `_retracted`, `pending_retractions`, `confirm_retracted`, `RETRACTION_REASSERT_TICKS`,
   шаг (4) тика с `None`-надгробиями (`process_heartbeat.py:764-823` — блок целиком). `None` как
   «показания нет» перестаёт существовать: нет писателя — нет поддерева.
4. Удалить тесты умершей бухгалтерии (§9-Ф2), взамен — авторские hazard'ы: гонка
   publish/retract одного писателя, потеря delete (запас), два departed подряд.
**Acceptance criteria:**
- [x] (ee110479) сценарий A1 старого мира невозможен: самозванец «в чужое имя» теперь публикует в СВОЁ
  поддерево, его уход удаляет только его поддерево (тест с литералами в обоих поддеревьях)
- [x] (ee110479) потеря первого delete не хоронит снятие (два тика, доставка со второго — кванторный, ≥2 тика)
- [x] (ee110479) grep: `RETRACTION_REASSERT_TICKS` в heartbeat/ не существует — 0 вхождений
**Out of scope:** снятие фреймворковых агрегатов (fps при исчезновении воркеров живёт по старым
правилам — отдельная тема, в этот план не входит).

### Task 2.3 — Сток: префикс-чистка строк ушедшего писателя (блокер Б1 ревью)
**Level:** Middle · **Assignee:** developer
**Goal:** DB-сток перестаёт бессрочно писать последние числа ушедшего писателя: MISSING-дельта
корня выбивает из его строк все ключи под этим корнем.
**Files:** `Plugins/io/telemetry_sink/plugin.py` (`:162-166` — сегодня точечный pop; `:221-226` —
раскладка ключей), его тесты.
**Steps:**
1. По дельте корня `processes.<P>.state.plugins.<писатель>` — вычистить из накопителя строки
   процесса все ключи `_extra` с этим префиксом (граница — точка-разделитель, как в Task 2.1).
2. Семпл после чистки пишет строку БЕЗ ключей ушедшего писателя (колонки фреймворка не задеты).
**Acceptance criteria:**
- [x] (1354b4f7) тест на СТОКЕ (не сторе): до стопа ключи писателя в строках БД с литералами; после стопа —
  исчезают за ≤1 семпл; сосед-писатель в тех же строках жив (пара-контроль)
- [x] (1354b4f7) инъекция рода 2 «чистка не зовётся» — тест краснеет (якорь существования обязателен)
**Out of scope:** схема таблиц; ретеншн; кэш прокси (Task 2.1).

### Task 2.4 — Независимая приёмка + ревью фазы
**Level:** Middle+ · **Assignee:** tester, затем reviewer (синхронно)
**Goal:** Приёмка снятия от критериев (правила §3), ревью с живым стендом — двумя объективами.
**Steps:** критерии тестеру: С1 — стоп писателя убирает его поддерево за ≤K тиков (якорь: до
стопа поддерево есть с литералом); С2 — сосед не задет (якорь: его лист жив с литералом на том же
тике); С3 — переподнятый писатель публикует, поддерево возвращается, отложенное удаление его не
догоняет (≥2 тика); С4 — то же на poll-дороге; С5 — сток: ключи ушедшего писателя исчезают из
строк за ≤1 семпл (якорь: до стопа — литералы в строках).
**Тестеру запрещено:** `heartbeat/telemetry.py`, `heartbeat/process_heartbeat.py`,
`proxy/state_proxy.py` (дифф), `Plugins/io/telemetry_sink/plugin.py` (дифф), авторские тесты Ф2,
этот план целиком.
**Acceptance criteria:**
- [x] **инъекции рода 2 прогнаны 2026-08-23; критерий ПЕРЕПИСАН по факту, решение владельца.**
  Было: «обе ловятся» — подразумевалось приёмочным набором. Это невыполнимо, и не по слабости
  тестов, а структурно:
  - «delete не зовётся никогда» — приёмка ловит: 14 красных, из них 4 приёмочных, включая
    писателя-КОНТРОЛЬ в С3. Условие «под первой не выживает ни один тест с отрицанием» —
    выполнено;
  - «delete зовётся для ВСЕХ писателей каждый тик» — приёмка не ловит ВООБЩЕ (8 красных, все
    авторские). Причина: при порядке «снять → собрать» лишнее снятие живого писателя лечится
    тем же тиком, поэтому объектив «дерево» этот дефект увидеть не может в принципе. Видит
    только объектив «трафик снятий» (число и адреса `delete` на проводе) — он есть в авторском
    наборе `test_writer_retraction_hazards.py`. Свойство ОХРАНЯЕТСЯ; изменилось лишь то, кто
    его охраняет. Вниз по потоку дефект реален: лишние MISSING-дельты чистят строки живого
    писателя у стока и read-model.
  Первый прогон И11 у исполнителя был написан с ошибкой (`for _, w in self._values`
  распаковывает строку-ключ на символы) и дал обратный, ложный результат — снят; верная форма
  подтвердила находку teamlead'а.
- [x] **закрыт долг И1/И2 и вскрыт фейк-харнесс**: сломанный путь в настоящем
  `StateProxy.delete` и его молчаливый `return` оставляли ВЕСЬ приёмочный файл зелёным — и
  приёмка, и авторские hazard'ы гоняют шаг снятия через дубль `_Proxy`. Добавлен провод-тест
  на настоящих объектах (`test_writer_retraction_real_wiring.py`, коммит b84dd653), проверено,
  что
  он не пустой: под обеими инъекциями краснеет
- [ ] live: стоп capture на стенде — стор: поддерево исчезло ≤3 тиков; сток: ключи из строк БД
  исчезли ≤1 семпла; обе пары чисел (до/после) процитированы в ревью
- [ ] **Финальное ревью фазы — Fable, жёсткое и честное** (решение владельца 2026-08-23).
  Модель на вердикт — Fable (экономика моделей: Fable на своды и вердикты). Область ШИРЕ
  диффа Ф2, три слоя обязательны и каждый со своим вердиктом:
  1. **Новая архитектура** — «владение = путь» действительно ли убрало класс дефектов
     структурно, а не спрятало его; не завелось ли нового арбитража под другим именем;
  2. **Реализация** — Ф1+Ф2 как поставка: delete-дорога, префикс-чистки, запас K,
     удалённая поимённая бухгалтерия;
  3. **Система наблюдаемости целиком** — состыкованы ли стор, сток, read-model, GUI и
     пульт после переезда путей; не осталось ли читателя, живущего по старой форме.
  Требования к вердикту: находки только с воспроизведением вход→выход (правило проекта:
  вердикт без воспроизведения — совет, а не факт); «всё хорошо» без прогона не принимается;
  запуск синхронный (run_in_background: false).
  ДОЛГИ, которые ревью обязано проверить, а не принять на слово:
  - инъекции И1/И2 против критериев С1–С4 (в матрице 2026-08-23 НЕ проверены — приёмочный
    файл был красен до Task 2.2);
  - инвентарь Task 2.0 собран по qex-индексу от 2026-08-06 (17 дней) и добит Grep'ом —
    пропущенный потребитель точечной чистки даст призраков молча.

---

## ИТОГИ Ф1+Ф2 — вердикт ревью 2026-08-23 (модель Fable, три слоя)

**Три вердикта, по слою на каждый:**

| Слой | Вердикт | Одной фразой |
|---|---|---|
| 1. Новая архитектура | **APPROVED** | класс дефектов убит структурно; шесть машин арбитража заменены одной ведомостью ~30 строк; нового арбитража под другим именем нет |
| 2. Реализация | **CHANGES REQUESTED → закрыто** | одна воспроизведённая дыра (F2), исправлена в `1c65fda2` |
| 3. Система наблюдаемости целиком | **CHANGES REQUESTED** | стыковка есть, но плоскость нема в логах (F1) и слепа к потерям (F6) |

**Стало лучше — числами, перепроверено ревьюером самостоятельно:**

| Показатель | До | После |
|---|---|---|
| Гейт фреймворка | 8667 | **8705**, падений нет |
| Гейт корневой | 7051 | **7090**, падений нет |
| Вытеснение дельт подписчика | 93.7% / 91.8% | **0** во всех очередях всех процессов |
| `fps` доходит до строки БД стока | 16 минут; `lines`/`pult` — никогда | **6.0 с** |
| Строки истории с данными | 297 / 0 | 42 из 80 за 25 с |

Цена названа: механизменный код Ф1+Ф2 вырос на +1943/−762 строки, из них ~845 —
ремонт транспорта (`request_async`), пригодный всем.

### Находки ревью и их судьба

- **F2 [СРЕДНЯЯ, регресс диапазона] — ЗАКРЫТО `1c65fda2`.** Журнал защиты окна
  ресинка помечал КОРЕНЬ, а `_cache_put` пишет ЛИСТЬЯ: снимок постарше стирал
  или откатывал более новое живое значение (21.3 → 10.0). Регресс привнесён
  разворотом dict-дельт. Два теста на оба сценария ревьюера, инъекция кладёт
  ровно их.
- **F8b, F8c — ЗАКРЫТО `1c65fda2`.** Кириллический идентификатор в боевом
  `frontend/app.py` (внесён тем же коммитом, который заявил, что их не осталось)
  и расхождение чисел 6.0/3.0 в двух yaml.
- **F1 [ВЫСОКАЯ, шире диапазона] — ОТКРЫТО, заводить немедленно.** Немы не
  только `StateProxy`: семь боевых мест передают `logger=self`, где `self` —
  процесс БЕЗ методов `warning/info/debug/error/critical` (есть только
  `log_warning`). `ObservableMixin._call_manager` берёт `getattr(manager,
  "warning") → None` и молча выходит; отсутствующий метод даже не попадает в
  `_note_manager_call_failure` — там считаются только исключения. Немы:
  `StateProxy`, `GuiStateProxy`, `StateStoreManager`, `DeltaDispatcher`,
  `ProcessRegistry`, `ProcessPriority`, `ProcessStateRegistry`. **Именно эта
  немота 22 минуты прятала дефект resync.**
- **F3 — вопрос Д1, ответ ниже.**
- **F4 [СРЕДНЯЯ] — на дефолтном конфиге порт НЕ ВЕЗЁТ в дерево ни одной
  плагинной метрики** (`deny-by-default`, белый список `fps`/`latency_ms`).
  Выигрыш новой адресации сегодня виден только poll-дорогой. Это открытый
  вопрос Ф4 (М1), но для ответа «стало ли лучше» он несущий.
- **F5 [НИЗКАЯ] — инвентарь Task 2.0 неполон.** `backend_ctl/conditions.py:248,296`
  (`_setup_state_path`, `_setup_metric_threshold`) фильтруют дельты точным
  сравнением пути → MISSING-дельта корня-предка невидима, условие досиживает до
  таймаута вместо диагноза «deleted». Тот же класс, что у прокси и стока.
  Заявление «неизвестных 0» строго неверно; прочие 14 строк подтверждены.
- **F6 [НИЗКАЯ] — `system_overview` слеп к data-plane потерям:**
  `queue_data_evicted` и `queue_never_drop_loss_total` не упоминаются в
  `overview.py`/`driver.py` вовсе, тогда как tail-потери выведены. Асимметрия
  тем страннее, что `never_drop_loss` — потеря control-plane.
- **F7 [НИЗКАЯ] — загрузчиков манифеста два**, паритет-тест сторожит только
  ключ `base`: новый ключ, добавленный в один загрузчик, им не ловится.
- **F8a, F8d — гигиена:** чекбоксы (закрыты этой правкой); протухший комментарий
  `inspector_panel.py:42` держит плоскую форму `state.capture_fps`;
  `docs/OBSERVABILITY_MAP.md` (ред. 2026-08-10) новой формы путей не знает.

### Ответы на долги, которые ревью запрещено было принимать на слово

**Д1 — боевого триггера у снятия Ф2 НЕТ. Подтверждено тремя фактами.**
`retract` зовётся только из `ProcessModulePlugin._do_shutdown` → только из
`PluginOrchestrator.shutdown()` → только из `process_module.py:288` (остановка
ВСЕГО процесса); `set_enabled` жизненный цикл не трогает. При смерти процесса PM
сносит `processes.<имя>` целиком, то есть снятию Ф2 нечего добавить. Живьём:
в полном списке команд процесса остановки одного плагина нет.
**Механизм исполнен и охраняем (62 зелёных + инъекции), но live-критерий Ф2
невыполним по построению.** Решение: переписать критерий по образцу Ф0
(«недостижимо на стенде») ЛИБО дать носителя в Ф3+ — кандидат назван самим
планом: `set_enabled` → lifecycle (`DECISIONS.md:2537`).

**Д2 — инвентарь добротный, но «неизвестных 0» неверно** (F5). Не блокирует Ф2:
речь об инструменте диагностики и транзиентных ожиданиях, а не о боевом кэше.

**Д3 — переквалификация критерия ПОДТВЕРЖДЕНА как структурная невозможность.**
Инъекция «delete всем писателям каждый тик»: приёмка — 0 красных, авторские — 8
в `test_writer_retraction_hazards.py` + 1 в `test_writer_retraction_real_wiring.py`.
Уточнение ревьюера принято: это не абсолютная ненаблюдаемость — дефект видим
трафиком снятий и вниз по потоку лишними MISSING-дельтами; слепа именно приёмка
от критериев. Охрана после `b84dd653` усилилась (9 красных против 8).

### Чего ревью НЕ смогло проверить (раздел обязателен и не пуст)

1. До-починочные живые числа (93.7%/91.8%, 16 минут, 297/0) — невоспроизводимы
   без отката починки; приняты по косвенным уликам.
2. «fps за 6.0 с» — сток выключен по умолчанию, включение требует правки
   `app.yaml` + регенерации golden, что ревью запрещено.
3. GUI-рендер живьём — оффскрин без qt-зонда.
4. Прямой счёт доставки дельт подписчику — зонд ревьюера получил 0 событий из-за
   курсорной семантики `events_page`; доставка доказана косвенно.
5. «+375 строк в golden» — не перемерялось.
6. Три из пяти resync-инъекций приняты по сходимости спот-чеков.

---

## Ф2-Т — ПРОЗРАЧНОСТЬ (требование владельца 2026-08-23, дословно)

> «Важно, чтобы система давала максимальную пользу и полную прозрачность — как в
> `backend_ctl`, так и в целом как система наблюдаемости.»

Требование поставлено ПОСЛЕ ревью и попадает ровно в три его открытые находки.
Общий корень у всех трёх один: **система наблюдаемости не умеет рассказать о
собственном отказе.** Диапазон Ф1+Ф2 — прямое тому доказательство: дефект resync
прятался 22 минуты не потому, что был хитрым, а потому, что о нём некому было
сказать.

### Task Т.1 — вылечить немоту плоскости (находка F1, ВЫСОКАЯ)
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** компонент, которому передали не тот логгер, обязан кричать, а не молчать.
**Суть:** семь боевых мест передают `logger=self`, где `self` — процесс БЕЗ методов
`warning/info/debug/error/critical` (у него только `log_warning`). `ObservableMixin._call_manager`
берёт `getattr(manager, "warning") → None` и молча выходит; отсутствующий метод даже
не попадает в `_note_manager_call_failure` — там считаются только исключения.
**Files:** `base_manager/mixins/observable_mixin.py` (`_call_manager`),
`multiprocess_prototype/generic_process_app.py:33`, `multiprocess_prototype/frontend/process.py:79`,
`process_manager_module/process/process_manager_process.py:134,141`,
`state_store_module/manager/state_store_manager.py:68`,
`shared_resources_module/core/shared_resources_manager.py:103`
**Acceptance criteria:**
- [x] «менеджер есть, метода нет» — СЧИТАЕМЫЙ отказ, а не молчаливый None (`a7d7cb60`)
- [x] тест: компонент с логгером-без-методов даёт видимый сигнал (не пустоту) (`a7d7cb60`)
- [x] live: в логах появляются записи `StateProxy` — **закрыто A/B на живом стенде**
      (см. «Живой стенд Ф2-Т» ниже)
- [x] инъекция: вернуть молчаливый None — тест краснеет (12 красных, предсказание совпало)
**Out of scope:** переписывание интерфейса логирования; правка GUI-подписок (Т.3).

### Task Т.2 — `backend_ctl` перестаёт врать умолчанием (находки F5, F6)
**Level:** Middle+ · **Assignee:** developer
**Goal:** оператор видит потери и удаления, а не «ручка не ответила».
**Files:** `backend_ctl/overview.py`, `backend_ctl/conditions.py:248,296`
**Acceptance criteria:**
- [x] (`54ec677a`) `system_overview` выводит в `anomalies` `queue_data_evicted` и
      `queue_never_drop_loss_total` — сегодня они не упоминаются в `overview.py`/
      `driver.py` ВООБЩЕ, тогда как tail-потери выведены (асимметрия тем страннее,
      что `never_drop_loss` — потеря control-plane)
- [x] (`54ec677a`) вейтеры `_setup_state_path`/`_setup_metric_threshold` понимают MISSING-дельту
      корня-предка: сегодня фильтр точным сравнением пути делает удаление поддерева
      невидимым, и условие досиживает до таймаута ВМЕСТО диагноза «deleted»
- [x] (`54ec677a`) у каждого нового сигнала — тест с якорем существования (ноль потерь при
      исправной системе НЕ засчитывается в паре без контроля, дающего ненулевое)
**Out of scope:** новые команды словаря; изменение формата ответа существующих ручек.

### Task Т.3 — GUI-подписки и лживый комментарий (находка ревью, слабое место 5)
**Level:** Middle · **Assignee:** developer
**Goal:** снять четыре таймаута со старта GUI и убрать неверное объяснение.
**Суть:** `frontend/process.py:102-119` делает ЧЕТЫРЕ `subscribe(sync=True)` (дефолт)
из шага 6, когда приёмного потока ещё нет. Замер: 20.03 с → 2.02 с после починки
грейса, и в ОБОИХ случаях подтверждённых подписок — 0. Комментарий над ними
(«subscribe — fire-and-forget») для sync-пути **ложь**.
**Acceptance criteria:**
- [ ] старт GUI не платит таймаутами подписки (замер числом, до и после)
- [ ] комментарий исправлен ВМЕСТЕ с кодом, а не отдельно
- [ ] названо, что делать с `_confirmed_patterns`: сегодня coverage-check мёртв
      (подтверждённых 0) — либо подписка переносится туда, где приёмник уже есть,
      либо проверка покрытия честно объявляется неработающей
**Out of scope:** перестановка шагов `ProcessModule.initialize()` — она открывает
окно «сообщение до регистрации handler'а», и доказать её безопасность тестом нельзя.

### Матрица инъекций Ф2-Т — 12 заплат, предсказания записаны ДО прогона

База без заплат зелёная: Т.1 — 27, Т.2 — 26. Каждая заплата ставилась в отдельном
worktree (`inject-t1t2`), в общем дереве инъекции врут в обе стороны.

| № | Что сломано | Предсказание | Факт | Итог |
|---|---|---|---|---|
| I1 | ветка «метода нет» → тихий `return None` | 12 | **12**, имена совпали | ✅ |
| I2 | `is not None` → truthiness у метода | 1 | **1** | ✅ |
| I3 | `_track_error`: выбор ступени по возвращённому значению | 1 | **4** | ⚠️ недооценил — свойство сторожат все четыре теста класса |
| I4 | `orchestrator`: `logger_manager` → `self` | 3 | **3** | ✅ |
| I5 | снять дедуп WARNING | 1–2 | **2** | ✅ |
| I6 | считать отказом `manager is None` | 3 | **0** | ❗ **НАХОДКА** — см. ниже |
| I7 | снять аномалию `queue_data_evicted` | 2 | **2** | ✅ |
| I7b | снять аномалию `queue_never_drop_loss_total` | 3 | **3** | ✅ |
| I8 | `_is_ancestor_path` → наивный `startswith` | 1 | **3** | ⚠️ недооценил — упали и юнит-тесты хелпера |
| I9 | ветка предка снята ТОЛЬКО у `state_path` | 1 | **2**, зеркальный `metric_threshold` ЗЕЛЁНЫЙ | ✅ тесты различают вейтеры |
| I10 | снять `isinstance(delta_path, str)` | 2 | **0** | ❗ см. «два слоя» ниже |
| I11 | отказ предиката снова тихий | 2 | **2** | ✅ |

**Находка I6 (исправлена, `0c06712d`).** Ноль красных означал не «свойство защищено»,
а «строка сторожит не то». `ManagerRegistry` ставит `_enabled[name] = manager is not None
and enabled`, поэтому до `if not manager` значение `None` не доходит ВООБЩЕ — гейт
`is_enabled` отсекает его выше. Единственный достижимый случай той строки — менеджер
НАСТОЯЩИЙ, но ложный по `__bool__`/`__len__`: его записи уходили в никуда и не
считались, потому что выглядели как «слот пуст». Тот же дефект, который Т.1 починила
строкой ниже — у метода, — жил строкой выше, у менеджера. Четыре теста, два краснеют
на возврате truthiness.

**Находка I10 — защита оказалась двухслойной, и ни один слой не доказан порознь.**
`iter_state_deltas` (`backend_ctl/events.py:105`) объявлен ЕДИНСТВЕННЫМ разборщиком
wire-контракта и уже фильтрует дельты до непустого строкового `path`. Снятие только
охранника в `conditions.py` — зелено (фильтр держит). Снятие только фильтра — зелено
(охранник держит). Снятие ОБОИХ — красные ровно два теста, и в выводе виден
`first_predicate_error: TypeError: unsupported operand type(s) for +: 'NoneType'` —
то есть счётчик отказа предиката из Т.2 сработал на настоящем исключении.
Вывод занесён в докстроку теста: одиночный слом любого слоя эти тесты НЕ ловят,
пара — ловит. Охранник оставлен как защита в глубину, но назван именно так.

---

### Живой стенд Ф2-Т — A/B на двух прогонах, не на слове

Оба прогона: `frontend/run.py`, `INSPECTOR_GUI_UNATTENDED=1`, `QT_QPA_PLATFORM=offscreen`,
свой каталог логов на прогон. «До» — worktree на `44cb7065`, «после» — `48f63af7`.
Стенды поднимались ПООЧЕРЁДНО: два бэкенда конфликтуют по PID-реестру и SHM-cleanup.

| Наблюдение | До | После |
|---|---|---|
| файлов логов | 54 | 54 |
| записей `StateProxy` во ВСЕХ логах | **0** | **9** (`StateProxy:gui`, INFO) |
| четыре boot-подписки GUI | 11:26:22,506 → 24,550 = **2.044 с** | 11:24:09,093 → ,094 = **0.001 с** |
| WARNING `router_gui: приёмный цикл ещё не запускался` | **4** | **0** |

Ноль засчитан только в паре с ненулевым контролем: одинаковый стенд, одинаковые 54 файла,
разница ровно в правках.

**Прогон уточнил формулировку самого критерия.** «В логах появляются записи `StateProxy`»
молча предполагало, что ему есть что сказать. В здоровом бутe у `StateProxy` выше DEBUG
нет НИ ОДНОЙ записи, кроме трёх INFO, привязанных к async-подписке, — то есть критерий
проверяем только на GUI-пути. На backend-only прогоне ноль записей — правильное поведение,
а не недочинка.

**Находка живого прогона, которой не было ни в плане, ни в ревью.** В unattended-режиме
`multiprocess_prototype/run.py` поднимает процесс `gui` классом
`frontend/headless_process.py::HeadlessGuiProcess` — голым `ProcessModule`, который только
дренирует data-очередь. Ни `GuiStateProxy`, ни четырёх подписок в нём нет: дефолтный стенд
код Т.3 **не исполняет вообще**. Настоящий GUI даёт только вход `frontend/run.py`
(presentation-overlay, `INSPECTOR_PRESENTATION`). Всякий будущий замер «старта GUI» обязан
называть, каким входом он снят, — иначе меряется не то.

**Роутер подтвердил и поправил объяснение.** Его собственный WARNING в прогоне «до» —
«Сообщение отправлено, ожидание прервано через 0.5 с вместо 5.0 с» — доказывает, что
подписки уходили на сервер и ДО починки; терялось подтверждение и время, а не подписка.
Живые 2.044 с — это уже ПОСЛЕ починки грейса (4 × 0.5 с); цифра 20.03 с из ревью снята
до неё (4 × 5.0 с) и на текущем `main` не воспроизводится.

---

### Task Т.4 — карта и комментарии догоняют код (находка F8d)
**Level:** Middle · **Assignee:** docs-writer
**Acceptance criteria:**
- [x] (`bfe5d176`) `docs/OBSERVABILITY_MAP.md` знает новую форму путей — и знает, что
      плоская форма ЖИВА как предохранитель под прямой `state_proxy.merge`
- [x] (`bfe5d176`) `inspector_panel.py:42,355` не держат плоскую форму `state.capture_fps`

---
