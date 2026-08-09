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

Команды:
  - enable             — включить отбраковку
  - disable            — выключить
  - set_delay          — задержка отбраковки (мс)
  - reset_counters     — обнулить счётчики (фронт решения не трогают)
  - get_stats          — текущая статистика + verdicts_written/verdicts_unwritten

Config:
  - enabled (bool, True)
  - min_defect_area (int, 500)
  - reject_delay_ms (int, 0)
  - max_detections_for_reject (int, 0)

Зависимости: нет (только stdlib)
Справочник v1: multiprocess_prototype/services/robot/service.py
