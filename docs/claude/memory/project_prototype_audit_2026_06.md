---
name: project-prototype-audit-2026-06
description: Полный аудит prototype+Services+Plugins (2026-06-13) — справочник находок для агентов
metadata:
  type: project
---

Полный многоагентный аудит `multiprocess_prototype` + `Services` + `Plugins` (~86k LOC, 3 слоя) проведён 2026-06-13. Справочник со стабильными ID находок: [`docs/audits/2026-06-13_prototype-services-plugins-audit.md`](../../audits/2026-06-13_prototype-services-plugins-audit.md). Индекс аудитов: `docs/audits/README.md`.

**Why:** большой read-only аудит дорого повторять; результат нужен как backlog и как карта, на которую агенты ссылаются по ID (H1, M-leak-1, …).

**How to apply:** при работе над улучшениями/багами сначала загляни в справочник по `file:line`/категории; перед «новым багом» проверь раздел «Ложные срабатывания» (4 отклонённых верификацией). Перед действием перечитай актуальный код — мог измениться.

Ключевое:
- Архитектура здорова: **циклов импорта нет** (acyclicity 10000), слои текут вниз, инвариант «плагин не импортирует prototype» соблюдён. Узкое место — **модульность** (god-файлы: presenter.py 1818, factory.py 1190).
- **2 HIGH:** RenameProcess не обновляет `target_process`/`chain_targets` (битая IPC-маршрутизация, `domain/entities/project.py:453-508`); анаморфный resize Hikvision 4:3→16:9 (`Services/hikvision_camera/core/converter.py:97`, см. [[project-hikvision-aspect-ratio]]).
- **Топ-темы medium:** утечки lifecycle (Qt/EventBus-подписки без отписки, ≥6 мест); тихое проглатывание ошибок (~30 `except: pass` без лога — нарушает [[feedback-logger-error-stats-managers]]); races в Plugins/Services; мёртвый код (frontend/actions ActionBus, Services/Operation_crop 858 LOC).
- Покрытие тестами 51.6% файлов.
