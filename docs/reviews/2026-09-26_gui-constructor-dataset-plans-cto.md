# Ревью CTO: планы gui-constructor и dataset-annotation, порядок QUEUE (2026-09-26)

**Предмет:** `plans/gui-constructor/`, `plans/dataset-annotation/`, блок «▶ ТЕКУЩИЙ ПОРЯДОК» в `plans/QUEUE.md`, правки
соседей (gui-service, frontend-constructor, rework 2б.2, line-sim-layer-editor). Только документы.
**Роль:** `cto` (Fable), синхронно, только чтение; живьём ничего не запускалось (стенд не поднимался, qt-mcp
`CONNECTION_CLOSED`). Отчёт сохранён лидом без правок по существу.
Предыдущее ревью того же дня — [`2026-09-26_gui-constructor-layers-cto.md`](2026-09-26_gui-constructor-layers-cto.md).

## Вердикты

- **`plans/gui-constructor/` — ACCEPT WITH CONDITIONS.** Условия 1–5 и находки 1–10 прошлого ревью закрыты в тексте (проверено по строкам, не по таблице авторов). До approve — только сверка канала файлов с соседом.
- **`plans/dataset-annotation/` — ACCEPT WITH CONDITIONS.** Одно решение против записанного и замеренного решения репозитория (`base.yaml`), одна задача противоречит сама себе (2.1 про sentrux), форма канала файлов расходится с gui-constructor. Всё — правки текста до approve.
- **Порядок в `QUEUE.md` — ACCEPT WITH CONDITIONS.** Ограничения учтены верно; две перестановки внутри полосы Д.

## Условия 1–5 и находки 1–10 прошлого ревью

| # | Статус | Где (file:line), что проверено |
|---|---|---|
| Усл. 1 редакция T4.1 | закрыто | три файла 22 038 / 23 029 / 23 929 Б; реестр — `design-connection-context.md:16-33`; веер/неблокирующая подписка — `:134-144`; легаси-дверь + sunset — `:177-186`; путь `host/` — `design-shell-layout.md:9-14`; YAML+блоб по `objectName`, замок после `restoreState` — `:36-51, :69-75`; `reload_prefixes` списком — `design-boot.md:177-188` |
| Усл. 2 синхронизация соседей | закрыто | frontend-constructor Ф4/Ф5 перенесены, T4.6 вынут из Блока В; gui-service Task 3.1 — «докинг — оболочка»; `architecture.md` — `Services/line_sim/gui/`; rework 2б.2 — `bootstrap/*`, `host/*`, `knobs/*`; редактор слоёв — «автономное окно» снято; T4.1 — плашка ЗАМЕНЁН |
| Усл. 3 правила слоёв | закрыто в другой форме, обоснованно | `phase-1-boot-split.md:24-47` Task 1.0: `examples ↛ Services/Plugins` — sentrux, `Services ↛ Qt кроме gui/` — грепный контракт-тест. Основание: `.claude/plugins/mcp-sentrux/README.md:57-62` (буквальные префиксы, `*` не раскрывает сегменты); `except/exclude/allow` в `rules.toml` — 0 |
| Усл. 4 вопрос (i), четыре «Пульта» | закрыто | `constructor-layers.md` «Имена (решено)»; `design-shell-layout.md:207-211`; плашка терминологии в gui-service |
| Усл. 5 числа | закрыто | `design-shell-layout.md:125-127` `line_sim` Qt-free (`Services/line_sim/__init__.py:3`) |
| Н1 N рантаймов | закрыто | `design-connection-context.md:10-33`; контракт-набор на двух подключениях — `phase-1:119-120` |
| Н2 веер/блокировка | закрыто, литералы не замерены | `design-connection-context.md:127-144`; `phase-1:176-180` |
| Н3 докинг дважды | закрыто | `phase-3-second-backend-sim.md:15-24` |
| Н4 `windows/` под ножом | закрыто | `design-shell-layout.md:9-14`; rework 2б.2 |
| Н5 пакеты в Services | закрыто | `design-shell-layout.md:113-127`; `architecture.md` |
| Н6 числа | закрыто | см. Усл. 5 |
| Н7 нативные доки | закрыто | `design-shell-layout.md:77-85`; тест «Переместить в окно» `phase-2:42-43` |
| Н8 «Пульты», дрейф `:128` | закрыто | `rules.toml:128-131` сверено |
| Н9 sunset `classic` | закрыто | `design-connection-context.md:177-186`; `phase-1:181-182` |
| Н10 hot-reload Services | закрыто | `design-boot.md:174-188`; `phase-1:147-149` |
| Идея f нож по нулю | закрыто | `phase-5-split-and-promote.md:11-17` |

## Баллы

| Предмет | Балл | Почему |
|---|---|---|
| gui-constructor план целиком | **8** | Все условия закрыты по строкам; литеральные приёмки, инъекции с предсказанием, стенд, канон-шапка. −1: Task 1.0 без тестера и без слова «почему»; −1: литералы 50/200 мс без якоря в коде (stall-порог проекта 5 с — `app.py:83`) |
| дизайн (3 файла) | **8** | Числа `app.py` перепроверены: 1138 строк, `process\._` = 47, строки 91/191/339/351/436/458/769/871/1042/1104/1125 совпали; `bridge_impl.py:34,48` один `_frame_cb`; `remote_frame_source.py:236` «блокирует до ответа хоста»; `main_window.py:266`; `process.py:385-392`; `registers.py:103`; `controls.py:61`. −2: Qt-free ли `bus` — решает 1.1; `getattr/setattr` = **5**, не 6 |
| dataset-annotation план целиком | **7.5** | Факты по коду верны (все спот-чеки сошлись); Ф1/Ф4 — литеральные приёмки, hazard-тесты автора, reviewer-security на 1.3, честная стартовая точка Ф3. −1.5: процесс в `base.yaml` против решения репо 2026-08-23; −1: 2.1 противоречит сам себе про sentrux |
| порядок QUEUE | **7.5** | Правила порядка верны, один блок, 3 ссылки целы. −1.5: полоса Д не выносит вперёд бэкенд-only 4.3/4.4 и разведку 3.1; −1: блок на вершине файла в 164 КБ (`lint_doc_size.py --json`: FILE_TOO_BIG 164.1, SECTION_TOO_BIG 66.4) — долг назван, срока нет |
| согласованность двух планов | **6.5** | Сошлись: форма `ref`, владелец правила (1.0), место клиента, 2.5b ↔ Ф1. Разошлись: литерал `variant` («thumbnail» vs «thumb»), форма колбэка (`FileResult` в GUI-потоке vs `(bytes\|None, str\|None)` в потоке пула), `Handle` vs `Cancel`, `ctx.connection(name)` — метод `BootContext`, не `WidgetContext` |

## Арбитраж решений авторов

**gui-constructor**
- Рантайм = одно подключение, флаги рестарта/стопа у хоста — согласен (`app.py:1125` пишет флаг в процесс).
- `pack_loader` в gui-constructor 1.4 — согласен: загрузчик один для встроенного GUI и клиента.
- Ф5 frontend-constructor → Task 2.4 — согласен.
- Редактор слоёв остаётся в `line-sim-layer-editor`, здесь скелет `sim.*` + помощник ревизии — согласен.
- FrameHub 50/200 мс — изменить форму, не число: предварительные; в Task 1.1 замер `create_tabs` (`app.py:871`) и применения дисплеев как якорь.

**dataset-annotation**
- SQLite-индекс + картинки по sha256, YOLO только экспорт — согласен.
- **Процесс `dataset` в `base.yaml` — изменить на подключаемый фрагмент.** `backend/topology/base.yaml:31-36`: «вписанный сюда процесс платят ВСЕ сборки. Замерено 2026-08-23 — раздул golden-снимки на 375 строк каждый и удвоил состав hello_world»; механизм — `observability_sink.yaml:1-20`, `app.yaml:25-35`. Форма: `backend/topology/dataset.yaml` + строка в `app.yaml`. Хаб и `service_module` отвергнуты верно.
- `dataset_<глагол>` плагинными командами — согласен (`device_hub/plugin.py:86-100`).
- HTTP loopback в процессе `dataset`, fail-closed, клиент во фреймворке — согласен (`socket_channel.py:75`, `socket_client.py:184`, прецедент `mjpeg_sink/plugin.py:72`); условие — единая форма с gui-constructor.
- Захват плагином с кольцом сырых кадров — согласен; «кадры брака нигде не хранятся» подтверждено (`schemas.py:27-46`, `robot_control/plugin.py:186-192`, `recorder.py:2-19`).
- Compare-and-swap на снимок — согласен.
- `AnnotationPorts` + адаптер-секция, закат после Ф1 — согласен с условием: имена сравнять с `WidgetContext` сейчас; `qt_files.py` — в sunset 2.5b.
- Сплит по sha256 ключа группы — согласен.
- Экспорт YOLO + папки + манифест + zip, обратный импорт — согласен; `ml_train/data.py:288-292`, `model_spec.py:17`, `import ultralytics` → `ModuleNotFoundError`, `pyproject.toml:312` только комментарий.

## Находки

1. **MEDIUM — `dataset` в `base.yaml` против решения репозитория** (см. арбитраж).
2. **MEDIUM — форма канала файлов расходится между планами** (см. баллы).
3. **MEDIUM — dataset Task 2.1 противоречит своему решению:** `phase-2:47-50` — правило грепным тестом, но FILES `:54` содержит `.sentrux/rules.toml`, инъекция `:70` ждёт удаления исключения `*/gui/*`, которого синтаксис не даёт.
4. **LOW — ссылки `constructor-layers.md:N` в обоих планах смещены на +2** (двухстрочная плашка в том же коммите).
5. **LOW — канон тестера не назван** для gui-constructor Task 1.0 и dataset Task 2.5.
6. **LOW — числа:** `getattr/setattr(process` = 5 (план: 6); «22 вхождения `apps/pult`» в записи решения — было 27, стало 4.
7. **LOW — планы не в ledger** (`plans_ledger.py status --check` → `WARN MISSING_ROW`); 0/0 задач — ограничение парсера (`plans_ledger.py:321`).
8. **LOW — `QUEUE.md`** 164 КБ / секция 66 КБ; долг без срока и владельца.

Сошлось без находок: `apps/pult` 27 → 4; 80 относительных ссылок в 16 файлах — 0 битых; `insert_many` построчный `execute` (`base_repository.py:88-93`); `BackendHarness` (`harness.py:313`); greenfield-пути не существуют; `ensure_subscription` без счётчика ссылок — авторы оговаривают.

## До approve / в ходе исполнения

**До approve (правки текста):**
1. dataset: `base.yaml` → фрагмент `backend/topology/dataset.yaml` + строка в `app.yaml`; пункт про golden-снимки снять.
2. Один абзац «Канал файлов» одинаковым текстом в `design-connection-context.md` §3.4 и dataset Task 2.1: `variant ∈ {thumb, full}`; `RemoteFileSource.fetch → (bytes|None, err|None)` в потоке пула, `FileChannel.fetch → FileResult` в GUI-потоке; члены `WidgetContext`; `qt_files.py` — в sunset 2.5b.
3. dataset Task 2.1: убрать `.sentrux/rules.toml` из FILES и инъекцию про sentrux.

**В ходе исполнения:** ссылки `constructor-layers.md:N` (+2); 6 → 5 и 22 → 27; слово о тестере в 1.0 и 2.5; замер в 1.1 как якорь для 200 мс; ledger-строки при approve; `QUEUE.md` — история в `_archive`.

## Порядок — что переставить

1. Полоса Д: после Д1 — сразу 4.3 + 4.4, затем Д2 (петля «импорт → zip в облако → обратный импорт» раньше холста).
2. Разведка Step 1 задачи 3.1 (`investigator`, только чтение) — во время Д1: её ответы определяют поля схемы 1.1.
3. Полоса И без изменений; назвать политику заполнителей: 2.3 и 4.1 — в паузах цепочки Senior+ 1.2 → 1.5 → 2.1 → 2.2.
4. gui-service 1b.2b вперёд И2 не двигать.

## Что оставлено открытым и что ненадёжно в оценке

- Ничего не запускалось живьём; веер кадров, 50/200 мс, `restoreState` не мерились; `sentrux check .` не запускался.
- Ledger 0/0 — вывод из регулярки `plans_ledger.py:321`.
- `insert_many`: построчный `execute` виден, коммит адаптера на каждый — не прочитан.
- Fork-safety `SQLManager` в `start()` плагина `dataset`, WAL с двумя писателями на Orin — не проверялись.
- Платят ли `examples/minimal_app` и `apps/line_sim` за процесс в `base.yaml` — не проверялось; вывод не меняется.
- Статусы «где мы» в блоке QUEUE по git не пересверялись.
- Баллы — суждение, не замер; qex не использовался.
