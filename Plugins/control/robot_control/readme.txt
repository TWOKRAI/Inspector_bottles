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
  Привод ставится только для reject-маркера (pass-маркер в очередь не ставится).
  Маркер считается ТОЛЬКО в total_not_inspected: total_inspected и total_rejected не
  растут, вердикт-документ не пишется, фронт решения не меняется.
  Широкая запись — одна на маркер, не решающая, текст "<action>: не проверен
  (<origin>@<source>)" — находим поиском по тексту.

Контракт привода (Task 5.2, ADR-PM-051): конвейер не ждёт механизма.
  В process() нет сна. Решение reject ставит цель в планировщик процесса
  (ctx.scheduler, один на процесс, воркер "actuation"):
    fire_at = capture_ts + transit_ms, окно до last_capture_ts + transit_ms.
  Значение actuation в широкой записи (рядом fire_at и transit_ms):
    scheduled   - цель поставлена, выстрелит воркер;
    missed      - окно закрылось раньше чем actuation_tolerance_ms назад: не стреляет,
                  считается в actuation_missed_items (по count, не по записям);
    unscheduled - у единицы нет capture_ts: не ставится, actuation_unscheduled_items;
    immediate   - transit 0 (умолчание): выстрел сразу на решении, планировщика нет;
    none        - pass (и pass-маркер): привода нет.
  Вердикт-документ пишется на РЕШЕНИИ; выстрел пишет только счётчики.
  Запись о разрыве (5.3: count, first/last_capture_ts, trace_ids, reasons, sources) -
  ОДНА постановка на окно, total_not_inspected += count; широкая запись несёт count и
  список trace_ids (trace_id пуст). Маркер старой формы - count = 1.
  Это снимает проблему ADR-174 «задержка на каждый маркер»: устаревшие маркеры
  больше не держат линию, а уходят в missed.
  Маркер с source=inspector при строке журнала у того же trace_id - надгробие кадра
  (осмотрен, копия кадра испорчена), а не второй исход: исход кадра - широкая запись
  этого плагина.

Команды:
  - enable             — включить отбраковку
  - disable            — выключить
  - set_delay          — УСТАРЕЛА: пишет transit_ms (мс), WARNING в журнал
  - reset_counters     — обнулить счётчики (фронт решения не трогают)
  - get_stats          — текущая статистика + total_not_inspected, verdicts_written/verdicts_unwritten,
                         actuation_fired_items, actuation_missed_items, actuation_unscheduled_items
                         (свои), actuation_late_fires, actuation_unfired_on_stop_items (счёт
                         планировщика ПРОЦЕССА: он один на процесс)

Config:
  - enabled (bool, True)
  - min_defect_area (int, 500)
  - transit_ms (int, 0) — путь изделия от кадра до толкателя, мс; 0 — привод сразу
  - actuation_tolerance_ms (int, 20) — допуск окна: позже — missed / late_fires
  - reject_delay_ms (int, 0) — УСТАРЕЛ: алиас transit_ms (действует при transit_ms = 0),
    ненулевое значение даёт один WARNING на экземпляр плагина
  - max_detections_for_reject (int, 0)
  - not_inspected_action (reject|pass, reject) — реакция на маркер not_inspected

Зависимости: нет (только stdlib)
Справочник v1: multiprocess_prototype/services/robot/service.py
