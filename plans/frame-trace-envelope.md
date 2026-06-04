# План: Frame-trace конверт — пер-сегментная трассировка кадра

- **Slug:** frame-trace-envelope
- **Дата:** 2026-06-04
- **Статус:** DRAFT — на согласование
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

### Task 1 — Trace в framework-раннерах (backend)
**Level:** Senior **Файлы:** `source_producer.py`, `data_receiver.py`, `pipeline_executor.py`
**Goal:** наполнять `item["trace"]` транспорт- и process-спанами (per-plugin) под флагом.
**Acceptance:** в логе детектора виден `trace` с transport(camera→detector) + process(hsv_mask/contour_finder).

### Task 2 — Чтение/дамп на выходе (GUI) + флаг
**Level:** Middle+ **Файлы:** `app.py` (frame callback), env/config флаг.
**Acceptance:** при `INSPECTOR_FRAME_TRACE=1` каждый N-й кадр печатает полный таймлайн.

### Task 3 — GUI-разбивка по сегментам (вариант B)
**Level:** Middle+ **Файлы:** `_panels.py` (детальный вид), агрегатор сегментов.
**Acceptance:** qt-mcp: таблица «участок · среднее мс» по последним кадрам.

## Out of scope (v1)
- Fan-in merge trace, распределённые часы (NTP), waterfall-виджет (вариант C).
