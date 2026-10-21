# Отчёт: C-11 — логгер `line_source` через `logger_module` (полоса Р2, 2026-10-21)

Сессия: inspector-bottles-a9. Ветка `fix/robot-v2-c11-logger` (`d1166b1ba`), слияние в main `a178e0b64` по «да» владельца.

## Что сделано

`Services/robot_comm/gui/line_source.py:45`: `logging.getLogger(__name__)` заменён на `get_std_logger(__name__)`
из `multiprocess_framework.modules.logger_module`, по правилу проекта 6. Это тот же приём, что T5.3c (`store.py:49`).
Задача solo-trivial: 1 файл, 2 строки.

## Числа

| проверка | до | после |
|---|---|---|
| `logger_module/tests/test_std_logger_guard.py` | 1 failed / 65 passed / 2 skipped | 66 passed / 2 skipped (ветка и main после слияния) |
| `Services/robot_comm/tests` | — | 1577 passed / 5 skipped / 2 xpassed (141 с) |
| `multiprocess_prototype/backend/tests` | — | 155 passed / 1 failed: `test_build_matches_snapshot[hikvision_letter_robot]` — C-16 по реестру |
| `scripts/validate.py` | 3 FAIL (C-13) | те же 3 FAIL (C-13), новых нет |
| `sentrux check .` (ревьюер) | — | 41 правило, все проходят |

Ревью Sonnet: APPROVED. Ревьюер проверил запуском, что `_log.warning(fmt, arg)` в `LineLink.close` доходит до `logger_module`
и с менеджером, и без него (репро во временной папке сессии).

## Что осталось открытым

- Теста на `LineLink.close` с отказом `unsubscribe` в репозитории нет: доставку записи подтвердило только репро ревьюера.
- G4 «threads without scope path» в `test_t38_line_view_acceptance.py`: 4 на ветке, 3 на main. Поток создаёт тестовый хост
  (`socket-ch-inbound-backend_ctl`), не правка. Разброс повторами не мерили — это наблюдение, не замер.
- Полный framework suite не гоняли: только радиус (сторожа `logger_module`, `robot_comm`, бэкенд прототипа, `validate.py`).
- Строку C-11 в `plans/queue/defects.md` закрывает координатор.
