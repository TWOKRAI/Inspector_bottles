RobotControlPlugin — управление отбраковкой по результатам детекции

Category: processing
Inputs:   frame (image/bgr), detections (list[dict])
Outputs:  frame (image/bgr), inspection_result (dict)

Описание:
  Анализирует detections, фильтрует по min_defect_area,
  принимает решение reject/pass. Ведёт статистику.

Вердикт как документ (Ф8.7, ADR-PM-029):
  Решение об отбраковке уходит документом в плоскость документов
  (ctx.write_document, kind="verdict"), а не строкой в журнал: файлы логов
  ротируются за 7 суток, вердикт о браке спрашивают годами.
  Пишется на ФРОНТЕ решения pass→reject — одна отбраковка даёт один документ,
  а не по документу на каждый кадр брака (append синхронный: медиана 3.6 мс,
  max 928 мс при бюджете кадра 16-40 мс).
  Плоскость не настроена или запись отказала — линия работает по-прежнему,
  потеря видна в get_stats.verdicts_unwritten, причина названа один раз.

Широкая запись о единице (Ф4, ADR-PM-036):
  На КАЖДУЮ единицу пишется одна широкая запись (ctx.write_event, род
  "inspection"): вердикт, счётчики единицы, ROI дефектов (первые 8, остальные
  посчитаны в roi_omitted), defect_area_max и порог min_defect_area — в ОДНОЙ
  строке плоскости логов, находимой поиском по trace_id.
  Решительность записи совпадает с фронтом вердикта: на переходе pass→reject
  она идёт мимо отбора (decisive=True), остальные прорежены настройкой
  observability.events (по умолчанию поток не пишется вовсе).
  confidence в записи НЕТ: у площадного детектора вероятностной модели нет по
  построению, и решение выносит порог — он и едет.
  trace_id едет и в вердикт-документе — по нему две записи сходятся.

Маркер not_inspected (Task 4.7d-4):
  Под политикой переполнения overflow: every кадр, который не успели проверить,
  заменяется лёгким маркером (inspection_status="not_inspected", overflow_marker=True,
  reason, source, trace_id). Плагин принимает его (accepts_markers = True) и решает по
  регистру not_inspected_action: reject (по умолчанию, «непроверенное = брак») или pass.
  inspection_result маркера: action, reason="not_inspected", origin (причина маркера),
  source. Выключенный плагин пропускает маркер (action=pass, reason=disabled).
  Задержка reject_delay_ms применяется только к reject-маркеру.
  Маркер считается ТОЛЬКО в total_not_inspected: total_inspected и total_rejected не
  растут, вердикт-документ не пишется, фронт решения не меняется.
  Широкая запись — одна на маркер, не решающая, текст "<action>: не проверен
  (<origin>@<source>)" — находим поиском по тексту.

Задержка и устаревшие маркеры (ADR-174, вердикт CTO 4.7d):
  reject_delay_ms при reject-маркере отрабатывается КАЖДЫЙ раз, как на обычном браке.
  После стоянки исполнителя в голове накапливаются тысячи маркеров (20 тыс. x 100 мс
  ~ 33 мин отбраковки давно ушедших бутылок); старить маркеры по capture_ts плагин
  пока не умеет - вопрос владельцу в docs/claude/OPEN_QUESTIONS.md, запись
  "4.7d: отбраковщик отрабатывает задержку на каждый маркер".
  Маркер с source=inspector при строке журнала у того же trace_id - надгробие кадра
  (осмотрен, копия кадра испорчена), а не второй исход: исход кадра - широкая запись
  этого плагина. При reject_delay_ms >= ring_depth / fps маркером становится каждый
  брак (риг CTO: кольцо 3, задержка 30 мс - 10 из 10); умолчание 0 - редкая гонка.
  Решение и формулы - multiprocess_framework/DECISIONS.md, ADR-174.

Команды:
  - enable             — включить отбраковку
  - disable            — выключить
  - set_delay          — задержка отбраковки (мс)
  - reset_counters     — обнулить счётчики (фронт решения не трогают)
  - get_stats          — текущая статистика + total_not_inspected, verdicts_written/verdicts_unwritten

Config:
  - enabled (bool, True)
  - min_defect_area (int, 500)
  - reject_delay_ms (int, 0)
  - max_detections_for_reject (int, 0)
  - not_inspected_action (reject|pass, reject) — реакция на маркер not_inspected

Зависимости: нет (только stdlib)
Справочник v1: multiprocess_prototype/services/robot/service.py
