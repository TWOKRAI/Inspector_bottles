# Аудит фундамента — схемы (2026-10-26)

Схемы к описи [docs/reports/2026-10-26_foundation-audit-inventory.md](../../reports/2026-10-26_foundation-audit-inventory.md). Снимок на HEAD `71bfc55fe`: при изменении кода он устаревает.

| файл | что | откуда данные |
|---|---|---|
| [system-containers.mmd](system-containers.mmd) | процессы системы (C4 L2): PM, GUI, дети по рецепту, процесс `devices` с драйверами Services, `backend_ctl`, устройства | карта (уровень 2), опись 1б — [Services](../../reports/2026-10-26_foundation-audit-1b-services.md), [backend_ctl](../../reports/2026-10-26_foundation-audit-1b-backend-ctl-libs.md) |
| [module-deps.mmd](module-deps.mmd) | связи 27 модулей по контурам (C4 L3), рёбра от 3 импортов, подпись «всего / вглубь» | ast-разбор импортов; полная таблица — [docs/maps/framework-core.md](../../maps/framework-core.md) |
| [class-hierarchy.mmd](class-hierarchy.mmd) | наследование: `BaseManager` и `ChannelRoutingManager` | graphify, рёбра `inherits` |
| [paths-lifecycle-message-log.mmd](paths-lifecycle-message-log.mmd) | три сквозных пути по звеньям; серый пунктир — звено только пересылает вызов | опись, раздел 2.2 (сверено по коду) |
| [restart-counters.mmd](restart-counters.mmd) | какое событие двигает какой из четырёх счётчиков рестарта | опись, раздел 2.3 L1 (сверено по коду) |
| [index.html](index.html) | все пять схем на одной странице (Mermaid 11.4.1 с CDN, нужен интернет) | собрано из `.mmd` этой папки |

Правят `.mmd`, затем пересобирают `index.html`: исходники вставлены в страницу с HTML-экранированием.

Рендер не проверен. Внешний валидатор Mermaid не разрешён, Chrome не ответил. При первом открытии `index.html` посмотреть консоль: синтаксическую ошибку Mermaid показывает вместо схемы.

Следующий шаг (кандидат в очередь, бриф CTO, вопрос 15): модель C4-как-код (LikeC4) с drill-down и тегами контуров, плюс сторож «модель = импорты». Эти схемы — промежуточный снимок до неё.
