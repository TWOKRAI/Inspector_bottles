---
name: project_telemetry_gui_controls
description: GUI-управление телеметрией (Ф4.1 telemetry-publish-control) — шаблонная секция вкл/выкл+частота метрик, cap-aware
metadata:
  type: project
---

**Фаза 4.1 плана telemetry-publish-control ЗАКРЫТА** (b8ee3353) — GUI-контролы управляемой публикации.

Секция `TelemetryControlsSection` (`multiprocess_prototype/frontend/widgets/tabs/processes/_telemetry_controls.py`)
встроена в `SingleProcessPanel` (панель процесса на вкладке «Процессы», после графика).

**Конструкторный принцип (требование владельца):** контролы НЕ хардкодятся per-метрика — строятся
В ЦИКЛЕ по списку метрик (framework `GATED_METRICS` = fps/latency_ms/effective_hz/cycle_duration_ms/shm).
Одна строка на метрику: `[✓ вкл] метка | частота interval_sec | статус`. Новая метрика в `GATED_METRICS`
→ строка появляется автоматически. RU-метки/дефолты интервалов — тонкий конфиг прототипа (`_TELEMETRY_METRIC_LABELS/DEFAULTS`
в `_panels.py`); список метрик — framework (single source of truth).

**Запись** — presenter `apply_telemetry_metric` → `telemetry.broadcast {publish:{metrics:{m:{enabled?,interval_sec?}}},
telemetry_mode:merge, target:<proc>}` через command-result-bridge (RequestRunner off-main — main-thread не
фризится, tab-open инвариант «0 блокирующего IPC» зелёный). Результат несёт `capped_by_throttle`
(Task 1.4 [[project_telemetry_coherence_remediation]]) → показывается в строке жёлтым «⚠ троттл N с» —
«no silent caps» доведено до пользователя. **Чтение статуса** — из `TelemetryViewModel`
([[project_gui_telemetry_read_model]]): process-level fps/latency в readout строки.

**qt-smoke verified** (dualcam_synth, порт 9142): 5 авто-строк отрендерились с RU-метками и дефолтами
(SHM=2.0, прочие 1.0), live-readout (fps 21.4/latency 46.0); выключение тумблера FPS **заморозило его
readout** (gate применён end-to-end), latency продолжил меняться (47.0→46.0) — доказательство, что команда
дошла до детского gate, не тихий дроп; точечность (соседние строки целы); поле частоты гаснет при выключении;
0 ошибок, без фриза. +21 pytest-qt тест.

**Урок:** «контролы по шаблону из списка параметров» ([[feedback_constructor_modularity]]) —
источник списка держать во framework (`GATED_METRICS`), presentation (метки/дефолты) в прототипе;
виджет генерит строки циклом, не знает конкретных метрик. Так любое приложение получает контролы даром.
