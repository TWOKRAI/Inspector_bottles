---
date: 2026-07-07
topic: constructor-master — Ф1+трек F в main, Ф2.1/2.2 закрыты, debug-plane v1 (UI-tap)
machine: macOS
branch: feat/constructor-f2 (актуальна, main влит)
---

## Session goal

Продолжение constructor-master после Ф1: закрытие Ф1 (merge в main), MERGE-GATE F,
старт Ф2, плюс две директивы владельца по ходу: (1) рабочий backend_ctl как приоритет,
(2) лёгкая отладка фронтенда агентами — «нажал кнопку → агент видит», универсально.

## Done (всё в git, дерево чистое кроме app.yaml-артефакта лаунчера)

- **Ф1 ЗАКРЫТ, вмержен в main**. Бонус 1.6 verify-probe нашёл РЕАЛЬНЫЙ баг:
  `driver.set_register` был молчаливым no-op (слал `plugin_name` вместо канона
  `{register, field, value}`; live-тест писал в несуществующее поле `width` и зеленел
  на чужих heartbeat-дельтах). Починено + `register_update` теперь отвечает ack
  (9ef0b12a).
- **MERGE-GATE F закрыт владельцем**, трек F вмержен в main (1cf80006): qt-smoke обоих
  рецептов PASS (все процессы running, gui принимает кадры, 0 traceback — ERRORs
  hardware-gated), контракты вкладок PASS (diff публичного API пуст), pytest 2932 PASS.
  **Критерий modularity ≥ +250 признан некалиброванным** (5650 ≈ baseline 5652):
  метрика cross-module рёбер не видит разрез god-файлов внутри пакета. Урок в plan.md.
- **Ф2.1 ctx.health** (агент, принят после ревью): схема `processes.<n>.health.*` —
  контракт со сторожевым тестом; report_error/set_status/degraded; публикация через
  heartbeat self-publish; откат `INSPECTOR_HEALTH_LOG_ONLY=1`; команды `health.report/
  status`; ADR-PM-010.
- **Ф2.2 честный breaker закрыт** (агент + мои хвосты): `health/breaker.py`
  (closed/open/half_open, подряд-счётчик отдельно от кумулятивного), report_error
  кормит breaker → open → degraded (breaker-owned снятие), контракт-поле
  `health.breaker`, produce()-breaker в SourceProducer (сон вместо горячего цикла),
  env-пороги 5/30с; ADR-PM-011. Live acceptance: 5×report → open+degraded ✓ (3/3).
- **Task 1.10 UI-tap** (директива владельца, сам): `frontend_module/debug/` —
  UiEventTap (QApplication-фильтр, выключен по умолчанию), команды `ui.tap.subscribe/
  unsubscribe/ping`, доставка путём log-tail (мост 1.1b/relay 1.7) → `ui.event` в
  driver.events(); e2e live ✓.
- **Task 1.11 debug-plane v1** (ревью идеи по запросу владельца, сам): ревью+дизайн в
  `plans/2026-07-06_constructor-master/debug-plane-idea.md`. Три уровня: жест
  (UiEventTap+seq) / **намерение** (CommandSenderTap — перехват ЕДИНСТВЕННОЙ двери
  GUI→бэкенд, ловит клавиатуру/combo/программные вызовы) / эффект (log+state).
  **`driver.debug_session()` — вся плоскость одним вызовом** (+debug_stop); MCP 24
  инструмента. E2e live: единый поток «ui.event(seq) + state.changed» ✓.

## What did NOT work / инциденты

- **Session-limit дважды** (сброс 9:00 и 15:30 МСК) — агенты обрывались; работа
  продолжалась инлайн (1.6, 1.10, 1.11 сделаны владельцем сессии).
- **Инцидент «двух инстансов»**: агент Ф2.2 встал (стойло 600s), реанимация через
  SendMessage создала ВТОРОЙ инстанс, а первый ОЖИЛ — оба писали Ф2.2 параллельно в
  одном дереве. Выжило благодаря «коммить каждый шаг»; второй инстанс корректно
  остановился, обнаружив коллизию. **Правило: перед реанимацией проверять, не ожил ли
  оригинал (вахта на mtime файлов его зоны).** Хвосты добил владелец сессии: фикс
  флака `_collect_health_deltas` (обрыв по первому errors терял last_error-дельту —
  leaf-wise публикация = отдельные дельты), live-acceptance breaker, ADR-PM-011.
- `.claude/agent-memory/teamlead/feedback_live_harness_tests.md`, на который ссылались
  промпты, агент не нашёл (память агента живёт per-agent); уроки продублированы в ТЗ.
- multiprocessing spawn не работает из stdin-скриптов (`FileNotFoundError <stdin>`) —
  live-пробники писать в файл (scratchpad), не heredoc.

## Key decisions made

- MERGE-GATE F: merge одобрен владельцем при 3/4 критериев; урок про метрику в plan.md.
- Debug-plane: намерение ловится перехватом двери CommandSender, НЕ расширением
  Qt-ловли (комбинаторика виджетов — тупик). ActionBusTap, мульти-подписчики,
  автоустановка в «рыбу» — v2 (см. debug-plane-idea.md).
- app.yaml — артефакт лаунчера (указатель активного рецепта), в коммиты не берём.

## Next step

1. **Ф2.3** (S): discovery `debug`→WARNING + failed-list; ObservableMixin `pass` →
   лог+счётчик. Затем **волны C 2.4∥2.5** (~30 сайтов `ctx.health.report_error`,
   плагины Plugins/) — примитив и breaker готовы, сайтам достаточно one-liner'а.
2. Ф2.6 опц (JSONL-sink). После Ф2 — Ф3 (Supervisor v2, жёсткий порядок 3.1/3.2/3.5
   до 3.8).
3. Померить FPS на железе — hardware-gated с Ф0 (телефон/Hikvision).
4. Идеи на будущее: v2 debug-plane (ActionBusTap, capability-манифест пресетов),
   перенос RouterPushChannel в router-слой.

## Files/refs

- Ветки: main (Ф0+Ф1+трек F), feat/constructor-f2 (Ф2.1, 2.2, 1.10, 1.11 — HEAD abfea5a9).
- Дизайны: debug-plane-idea.md, capability-manifest-idea.md, app-template-idea.md.
- ADR: PM-010 (health), PM-011 (breaker).
- Память: docs/claude/memory/project_constructor_master_progress.md (+локальная копия).
