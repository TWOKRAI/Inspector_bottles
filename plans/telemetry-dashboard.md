# План: telemetry-dashboard — интерактивный дашборд телеметрии на PyQtGraph

- **Slug:** telemetry-dashboard
- **Дата:** 2026-07-17
- **Ветка:** feat/telemetry-dashboard (от feat/telemetry-coherence)
- **Статус:** DRAFT
- **Продолжает:** [`telemetry-publish-control.md`](telemetry-publish-control.md) (Ф4.1 GUI-контролы),
  [`gui-telemetry-read-model.md`](gui-telemetry-read-model.md) (read-model)

---

## Context

После Ф4.1 (управляемая публикация из GUI) появился запрос на **многосерийный интерактивный
график** — дашборд телеметрии всей системы на вкладке «Все процессы»: серия на процесс,
легенда-тумблеры (скрыть/показать процесс), zoom/pan, live-обновление. Текущий
`TelemetrySparkline` (кастом QPainter) намеренно минимален — для дашборда не годится
(нет интерактива, много серий, downsampling).

**Решение владельца:** стандартизироваться на **PyQtGraph** для ЕДИНООБРАЗИЯ (одна система
графиков вместо кастом+возможный matplotlib). Обоснование: реальный интерактивный кейс,
PyQtGraph — array-рендер (numpy уже есть) + встроенные легенда/zoom/pan/downsampling; matplotlib
для live медленный. Новая зависимость оправдана реальной потребностью (правило проекта соблюдено).

**Конструкторный принцип:** не лепить дашборд руками, а сделать **переиспользуемый компонент во
`frontend_module`** (`TelemetryChart`), строящий график по ДЕКЛАРАТИВНОМУ списку серий (как секция
Ф4.1 строится по `GATED_METRICS`) + read-model. Любое приложение/вкладка получает интерактивный
график даром — framework-first.

**Границы слоёв:** компонент — во `frontend_module` (framework GUI-слой, уже PySide6). Прототип
задаёт лишь список серий/цвета/источник. Импорт-границы: framework НЕ знает прототип
(`mcp__sentrux__check_rules` чист).

---

## Фаза 0 — Зависимость (gate)

### Task 0.1 — Ввести PyQtGraph в зависимости
**Level:** — · **Assignee:** владелец (install) + developer (pyproject) · **Layer:** infra
**Goal:** pyqtgraph доступен в проектном .venv, зафиксирован в pyproject/lock.
**Steps:**
1. Владелец запускает `uv add pyqtgraph` (на pip/uv у агента deny — [[feedback_package_install_by_user]]).
   Ляжет в секцию «Data / plotting» pyproject рядом с matplotlib/plotly.
2. Смоук-импорт: `python -c "import pyqtgraph; import numpy; print(pyqtgraph.__version__)"`.
3. Проверить, что pyqtgraph видит PySide6 backend (`pyqtgraph.Qt` резолвит PySide6, не PyQt).
**Acceptance:**
- [ ] `import pyqtgraph` в проектном .venv, версия печатается
- [ ] pyproject содержит pyqtgraph; `uv.lock` обновлён
**Out of scope:** GL-ускорение (`pyqtgraph.setConfigOption('useOpenGL')` — по необходимости позже).

---

## Фаза 1 — Переиспользуемый компонент TelemetryChart (framework)

### Task 1.1 — `TelemetryChart` во frontend_module (конструкторный, декларативный)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** generic-виджет многосерийного live-графика: список серий → PlotWidget с легендой-тумблерами,
zoom/pan, live-обновлением; ничего не знает о конкретных метриках/процессах.
**Files:** `multiprocess_framework/modules/frontend_module/widgets/telemetry_chart.py` (новый),
`interfaces.py`, README/STATUS, tests (правило проекта №2).
**Steps:**
1. API (Dict-at-Boundary дружелюбный, конструкторный):
   - `SeriesSpec`: `{key, label, color?, y_axis?}` — декларативное описание серии.
   - `TelemetryChart(series: list[SeriesSpec], *, x_window_sec, downsample=True)`:
     `pg.PlotWidget` с `addLegend`, `showGrid`, `setDownsampling(auto=True)`, `setClipToView(True)`.
   - `set_series_data(key, points: list[tuple[ts, value]])` — обновить одну серию (setData).
   - `set_visible(key, bool)` — скрыть/показать серию (легенда-тумблер зовёт это же).
   - легенда с чекбоксами → `set_visible` (клик по элементу легенды переключает кривую).
2. Live-режим: метод `update_from(read_model, mapping)` ИЛИ внешний драйвер зовёт `set_series_data`
   (решить teamlead: тонкий компонент — внешний драйвер предпочтительнее, симметрия с VM-паттерном).
3. Downsampling/clip включены — тысячи точек не тормозят; zoom/pan — штатные pyqtgraph.
4. Graceful: пустая серия → просто нет кривой (без падений), как placeholder спарклайна.
**Acceptance:**
- [ ] Тест (pytest-qt): N серий из списка → N кривых + N элементов легенды (генерация по списку)
- [ ] Тест: `set_visible(key, False)` скрывает кривую (`curve.isVisible() is False`), тумблер легенды тоже
- [ ] Тест: `set_series_data` обновляет только свою серию, прочие не тронуты
- [ ] Тест: пустая/односерийная/битые точки — не падает
- [ ] `mcp__sentrux__check_rules` чист (frontend_module не импортирует прототип)
**Out of scope:** сохранение/экспорт графика; несколько Y-осей (задел `y_axis` в SeriesSpec, реализация позже).

---

## Фаза 2 — Дашборд «Все процессы» (прототип)

### Task 2.1 — Системный дашборд телеметрии на вкладке «Все процессы»
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** prototype
**Goal:** в `AllProcessesPanel` — многосерийный график: серия fps на процесс (и/или latency),
легенда-тумблеры скрыть/показать процесс, zoom/pan, live из read-model (ring 10м) + история (1ч/1д).
**Files:** `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py` (AllProcessesPanel),
возможно новый `_system_dashboard.py`, tests.
**Steps:**
1. Собрать `SeriesSpec` на каждый процесс (из topology/read-model), метрика — переключатель fps/latency
   (или обе с разными осями). Цвета — по процессу (стабильная палитра).
2. Встроить `TelemetryChart` в AllProcessesPanel (рядом/вместо health-сводки — решить по компоновке).
3. Драйвер обновления: слот на `TelemetryViewModel.updated` мапит `processes.<P>.state.<metric>` →
   `chart.set_series_data(P, ring_points)`; переключатель диапазона 10м/1ч/1д (ring/БД как у спарклайна).
4. Легенда-тумблеры процессов; zoom/pan штатные.
**Acceptance:**
- [ ] qt-smoke (`feedback_qt_mcp_smoke_verification`): дашборд рисует ≥2 серий, легенда-тумблер
  скрывает процесс, zoom/pan работают, live-обновление идёт
- [ ] Тест: панель собирает SeriesSpec по списку процессов (генерация); скрытие процесса → серия hidden
- [ ] tab-open инвариант зелёный (0 блокирующего IPC); без фриза
**Out of scope:** алерты/пороги на графике; кросс-процессные агрегаты.

---

## Фаза 3 — Миграция спарклайнов на общий компонент (единообразие)

### Task 3.1 — Перевести per-process спарклайны на TelemetryChart
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** prototype
**Goal:** одна система графиков везде — `SingleProcessPanel` fps/latency через `TelemetryChart`
(мини-режим), `TelemetrySparkline` удалён или оставлен тонким адаптером.
**Files:** `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py`,
`.../widgets/telemetry_sparkline.py` (удалить/усечь), tests (обновить `test_history_graph.py` и пр.).
**Steps:**
1. Заменить `TelemetrySparkline` на `TelemetryChart` в `_build_graph_box` (компактный пресет:
   без легенды/осей-подписей, 1-2 серии).
2. Сохранить поведение: 10м ring / 1ч/1д БД, «нет данных» плейсхолдер (pyqtgraph — пустая кривая + label).
3. Удалить мёртвый `TelemetrySparkline` (grep 0 потребителей) либо оставить как thin-alias.
**Acceptance:**
- [ ] Тест: существующие графи-тесты (`test_history_graph.py`) зелёные на новом компоненте
- [ ] grep: `TelemetrySparkline` не используется (или только alias)
- [ ] qt-smoke: панель процесса рисует fps/latency как раньше (визуальный паритет)
**Out of scope:** новый функционал спарклайнов.

---

## Verification (весь план)

1. `import pyqtgraph` в .venv (Фаза 0).
2. `TelemetryChart` тесты + `check_rules` (framework не знает прототип).
3. qt-smoke (`QT_MCP_PROBE=1`, dualcam_synth): дашборд «Все процессы» — многосерийный, легенда-тумблеры,
   zoom/pan, live; панель процесса — спарклайны-паритет.
4. tab-open инвариант зелёный; framework + prototype suite зелёные (эталон: 2 pre-existing Windows app_module).
5. sentrux не хуже baseline.

## Риски

| Риск | Митигация |
|------|-----------|
| pyqtgraph тянет PyQt вместо PySide6 | явно `os.environ['PYQTGRAPH_QT_LIB']='PySide6'` до импорта / проверить `pyqtgraph.Qt` |
| Новая зависимость утяжеляет импорт GUI | pyqtgraph импортить лениво в компоненте; numpy уже есть |
| Много серий × высокая частота фризят | `setDownsampling(auto=True)` + `setClipToView(True)`; обновление off-critical |
| Миграция спарклайнов ломает графи-тесты | Фаза 3 отдельно; характеризация + qt-smoke паритет |
| Легенда-тумблеры путают с Ф4.1 контролами | дашборд = ЧТЕНИЕ (скрыть кривую ≠ выключить публикацию); подписать |

## Порядок

Фазы строго последовательно: 0 (gate install) → 1 (компонент) → 2 (дашборд) → 3 (миграция).
Каждый коммит: `Refs: plans/telemetry-dashboard.md` + trailers `Why:`/`Layer:`.
