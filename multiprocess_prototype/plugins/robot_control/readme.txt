RobotControlPlugin — управление отбраковкой по результатам детекции

Category: processing
Inputs:   frame (image/bgr), detections (list[dict])
Outputs:  frame (image/bgr), inspection_result (dict)

Описание:
  Анализирует detections, фильтрует по min_defect_area,
  принимает решение reject/pass. Ведёт статистику.

Команды:
  - enable             — включить отбраковку
  - disable            — выключить
  - set_delay          — задержка отбраковки (мс)
  - reset_counters     — обнулить счётчики
  - get_stats          — текущая статистика

Config:
  - enabled (bool, True)
  - min_defect_area (int, 500)
  - reject_delay_ms (int, 0)
  - max_detections_for_reject (int, 0)

Зависимости: нет (только stdlib)
Справочник v1: multiprocess_prototype/services/robot/service.py
