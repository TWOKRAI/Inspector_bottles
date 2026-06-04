# План: Frame-trace конверт — пер-сегментная трассировка кадра

- **Slug:** frame-trace-envelope
- **Дата:** 2026-06-04
- **Статус:** Task 1+2 DONE (48caea37), Task 3 (GUI-разбивка) DONE, Task 4 (терминология) DONE
- **Ветка:** feat/comm-system-target-architecture (продолжение телеметрии)
- **Родитель:** [`telemetry-self-publish-redesign.md`](telemetry-self-publish-redesign.md) (capture_ts = первое поле trace, коммит 08160b3d)

> **Идея владельца (2026-06-04):** через все плагины едет словарь-метаданные, который
> от плагина к плагину пополняется. Каждый участок (плагин + роутер/транспорт)
> записывает **время отправки и приёма** → в конце цепочки читаем полную разбивку:
> сколько ушло на передачу между участками и сколько на обработку в каждом плагине.
> НЕ просто сумма — структурированный лог.

---

## Что уже есть (фундамент)

- `item["capture_ts"]` штампуется в `SourceProducer` (08160b3d), едет через всю цепочку
  (плагины сохраняют `{**item}`, `DataReceiver._build_item` копирует `data`), на дисплее
  считается сквозная задержка. Это t0 будущего trace.
- Проверено: `item`-словарь переживает весь путь (hsv_mask/contour_finder/contour_draw
  делают `{**item, ...}`; SHM-middleware трогает только `frame`).

## Схема trace

`item["trace"]` — список сегментов (упорядочен по ходу кадра). Два вида:

```python
# Транспорт между узлами (роутер/IPC):
{"kind": "transport", "from": "camera_0", "to": "detector", "ms": 1.8}
# Обработка внутри узла (по плагинам или суммарно по узлу):
{"kind": "process", "node": "detector", "plugin": "hsv_mask", "ms": 0.6}
```

Плюс заголовок: `item["capture_ts"]` (t0). Время — `time.time()` (wall, кросс-процессно
сравнимо на одной машине). Длительность считается на приёме (`now - t_send`) и при
обработке (`t_out - t_in`).

## Точки инструментовки (framework, generic — без правок каждого плагина)

| Узел | Действие |
|------|----------|
| `SourceProducer` | init `trace=[]`, `capture_ts` (есть); перед send: `item["_t_send"]=time.time()`, `item["_from"]=name` |
| `DataReceiver` (каждый consumer) | на приёме: transport-span `{from:_from, to:name, ms:now-_t_send}`; `_t_recv=now` |
| `PipelineExecutor._execute_chain` | обернуть КАЖДЫЙ `plugin.process()` таймером → process-span `{node, plugin, ms}` |
| `PipelineExecutor._send_results` | перед send: `_t_send=time.time()`, `_from=name` |
| GUI (`_on_frame_received`) | финальный transport-span; `item["trace"]` — готовый таймлайн |

`_t_send`/`_from` — временные служебные поля (перезаписываются на каждом hop); `trace` —
накопительный.

## Визуализация «прочитать что там»

Варианты (выбрать при согласовании):
- **A. Лог-дамп:** каждый N-й кадр писать `trace` в лог процесса (дёшево, для отладки).
- **B. State-панель:** последний/средний trace → разбивка по сегментам в детальном виде
  (таблица «участок · мс»). Публикация агрегата в дерево (per-segment среднее).
- **C. Отдельный trace-виджет:** waterfall-диаграмма сегментов (дороже).

Рекомендация: **A + B** (лог для отладки + таблица сегментов в GUI).

## Накладные расходы и риски

- **Overhead:** список trace растёт на ~1 запись/hop; `time.time()` дёшев. Включать
  через флаг (env `INSPECTOR_FRAME_TRACE=1` или config) — не платить в проде по умолчанию.
- **Clock skew:** `time.time()` ок на одной машине; распределённо нужен NTP (отметить).
- **Fan-in/fan-out:** `region_split` (1→N), `stitcher`/merge (N→1) ломают линейный trace —
  v1 поддерживает линейную цепочку; merge — отдельная задача (какой trace наследовать).
- **Размер IPC:** trace в `data` едет по IPC; ограничить длину/детализацию.

## Задачи

### Task 1 — Trace в framework-раннерах (backend) — DONE 48caea37
**Файлы:** `frame_trace.py` (новый), `source_producer.py`, `data_receiver.py`, `pipeline_executor.py`, `generic_process.py`.
**Acceptance:** [x] в логе виден полный `trace` с transport + process-спанами по плагинам.

### Task 2 — Чтение/дамп на выходе (GUI) + флаг — DONE 48caea37
**Файлы:** `app.py` (frame callback), флаг `INSPECTOR_FRAME_TRACE`.
**Acceptance:** [x] при `INSPECTOR_FRAME_TRACE=1` каждый 30-й кадр печатает полный таймлайн.
Реальный замер: capture 0.28 / transport→detector 1.58 / hsv_mask 0.70 / contour_finder 0.14 /
transport→painter 1.03 / contour_draw 0.003 / transport→gui 4.08 мс (итого ~7.8 мс). Вывод:
время уходит в IPC-передачу, не в CV-обработку.

### Task 3 — GUI-разбивка по сегментам (вариант B) — DONE
**Level:** Middle+ **Файлы:** `main_window.py` (аккумулятор `record_trace_spans`/
`reset_trace_segments`), `app.py` (накопление в `_on_frame_received` + публикация
`system.trace_segments` раз в секунду), `_panels.py` (`AllProcessesPanel._build_trace_panel`
+ `_on_trace_segments` через `bind_fanout`).
**Acceptance:** [x] qt-mcp live: таблица «Участок · Тип · Среднее, мс» в «Все процессы»
со строкой «Итого», скрыта без `INSPECTOR_FRAME_TRACE=1`. Замер: contour_finder 5.43 /
camera→detector 2.09 / detector→painter 2.80 / hsv_mask 1.36 / contour_draw 1.87 мс.

### Task 4 — Терминология телеметрии (попутно) — DONE
**Why:** «FPS» корректен только для кадров (цепочка/источник); процесс-обработчик
не производит кадры. Разделили: частота → «Циклов/с» (среднее за секунду),
время → «Время цикла» (мс, индикатор узкого места).
**Файлы:** `cycle_metrics.py` (`effective_hz` = оконное среднее за 1 с вместо
мгновенного 1/interval), `process_card.py` (`_METRIC_KEYS`), `presenter.py`,
`_panels.py` (карточки + «Средняя частота» вместо «Средний FPS»).
**Acceptance:** [x] qt-mcp live: карточки показывают «Циклов/с»/«Время цикла»,
health — «Средняя частота»; «FPS цепочки»/«Задержка цепочки» сохранены (реальные кадры).

## Out of scope (v1)
- Fan-in merge trace, распределённые часы (NTP), waterfall-виджет (вариант C).
