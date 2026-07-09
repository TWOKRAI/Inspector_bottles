---
name: project-observability-store-error-routing
description: "ObservabilityStore (5.20a): ошибки приложения идут в logger_manager (logger.error/ctx.log_error), НЕ в error_manager — store-tap нужен на ОБА; live-boot вскрыл, юниты прятали"
metadata:
  type: feedback
---

Ф5.20a: `ObservabilityStore` (SQLite/WAL) наполняется из drain-петли (log/stats из hub) + store-tap на менеджерах ошибок (kind=error).

**Урок (live-boot region_pipeline через BACKEND_CTL, 2026-07-09):** первый tap повесил только на `error_manager` → стор набрал 60 log / **0 error**, хотя ошибок было полно (камера не открывается headless). Причина: приложение логирует ошибки через **`ctx.log_error`/`logger.error` → logger_manager**, а не `error_manager.track_error`. Пример: `Plugins/sources/capture/plugin.py:222` (`ctx.log_error("не удалось открыть камеру")`). Только `_track_error`/`report_error`/`log_exception` идут в error_manager.

**Фикс:** store-tap (min_level=ERROR) вешать на **ОБА** менеджера — error_manager И logger_manager (разные инстансы, запись попадает ровно в один → без дублей). После фикса live: error=1 (ошибка камеры в сторе). Коммит 1c8814db.

**Why:** вкладка «Ошибки» вживую была бы пустой. Юнит-тесты тестировали только error_manager-путь → зелёные, но скрыли реальный маршрут ошибок. Мораль (как Ф3.7 supervisor): для observability/error-путей нужен live-boot, юнит на «tap сработал» ≠ доказательство покрытия.

**How to apply:** любой перехват логов/ошибок в этом проекте — помнить, что error-записи текут по ДВУМ каналам (logger + error менеджеры). Валидировать через `backend_ctl` live-boot, не только юнитами. [[feedback-backend-ctl-for-agents]] [[project-hardware-recipes-no-headless-boot]]

**Также замечено live:** stats-канал стора пуст — воркерные метрики идут `_publish_metrics_to_tree` (state-дерево, Ф5.7), мимо hub-stats-слота; в стор попадают только явные `ObservableMixin.record_metric`.
