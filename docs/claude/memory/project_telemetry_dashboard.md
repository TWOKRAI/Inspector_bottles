---
name: project_telemetry_dashboard
description: PyQtGraph как единая система графиков + TelemetryChart (framework) + системный дашборд телеметрии; план telemetry-dashboard ЗАКРЫТ
metadata:
  type: project
---

**План telemetry-dashboard ЗАКРЫТ** (ветка `feat/telemetry-dashboard` от `feat/telemetry-coherence`).
Решение владельца: **стандартизироваться на PyQtGraph** (0.14.0, backend PySide6) для единообразия —
одна система графиков вместо кастом-спарклайна/matplotlib. numpy уже был. Установка: `uv add pyqtgraph`
(агент только выдаёт команду — [[feedback_package_install_by_user]]).

**Переиспользуемый компонент `TelemetryChart`** (`frontend_module/widgets/telemetry_chart.py`, framework-
first) — конструкторный: строит кривые В ЦИКЛЕ по декларативному списку `SeriesSpec` (как секция Ф4.1
по GATED_METRICS). Внешний драйвер гонит точки `set_series_data(key, points)` (тонкий компонент,
симметрия с VM). Фичи (все опциональны, параметрами): легенда-тумблеры (чекбокс на серию → скрыть/
показать), `crosshair`, `compact` (мини), `legend`, `y_label`, `series_points()` (для тестов). Не
импортирует прототип.

**Дашборд «Все процессы»** (`_system_dashboard.py`, прототип): серия на процесс (конструкторно из
списка процессов), переключатель метрики (fps/latency), live из read-model ring
([[project_gui_telemetry_read_model]] `TelemetryViewModel.history`), встроен в AllProcessesPanel.

**Читаемость при разном масштабе** (одна серия ~40, другие ~0 — «непонятен масштаб»): решено
**crosshair + панель значений** (Grafana-style) — наводишь курсор → вертикальная линия + значение
КАЖДОЙ видимой серии в этой точке времени (по убыванию, цветом серии) + подпись оси Y. Урок: время
заголовка = позиция КУРСОРА (x), НЕ ts ближайшей точки серии (иначе рассинхрон при разреженных
данных одной серии). `values_at_x(x)` — pure-хелпер (bisect), тестируемый без мыши. Log-шкала отвергнута
в пользу crosshair.

**Зум колесом** (запрос владельца): time-series — колесо зумит X (время), Y авто-подгоняется под
видимое окно (`setMouseEnabled(x=True,y=False)` + `setAutoVisible(y=True)`) — Grafana-style, заодно
вторично помогает масштабу. Осознанно X-only (не 2D); сброс — двойной клик / «A» pyqtgraph.

**Единообразие**: per-process спарклайны мигрированы на тот же `TelemetryChart` (mini: одиночная серия,
legend=False, интерактивный), кастом `TelemetrySparkline` удалён — одна система графиков везде.

**Грабли qt-mcp**: колёсный жест не скриптуется (нет wheel-tool) — зум проверяется визуально/конфигом,
не автоматом. Выбор процесса в nav-списке — кликать по **viewport** (`qt_scrollarea_viewport`), не по
рамке QListWidget. Всё qt-smoke-verified (dualcam_synth, порт 9142). Урок [[reference_qt_mcp_launch]].
