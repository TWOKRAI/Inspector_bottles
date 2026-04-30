---
description: Запустить Debugger-агента (Sonnet) — диагностика падающих тестов, регрессий, непонятных ошибок
---

Запусти агента **debugger** (Sonnet) для диагностики проблемы.

Входные данные: $ARGUMENTS — описание бага, команда воспроизведения, или путь к failing-тесту.

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи проблему: `/debug <описание>` или `/debug pytest <путь>::<тест>`
   > Например: `/debug pytest tests/test_router.py::test_channel_dispatch`

2. **Собери контекст**
   - Последние коммиты: `git log -5 --oneline`
   - Последние изменения: `git diff HEAD~1` (если регрессия)
   - Если есть failing-тест: `pytest <путь> -v -x --tb=short` (короткий трейс)

3. **Вызови debugger**
   ```
   Agent(subagent_type: "debugger", prompt: "<описание + собранный контекст>")
   ```

4. **Обработай результат**
   - Если **FIXED** → debugger сам всё починил и закоммитил
   - Если **ROOT CAUSE FOUND** (без фикса) → передай диагноз нужному агенту:
     - Уровень Junior/Middle → `developer` (Sonnet)
     - Уровень Senior+ → `teamlead` (Opus)
   - Если **не воспроизвёлся** → сообщи пользователю, что нужен точный сценарий

## Типовые вызовы

```
/debug pytest tests/unit/test_models.py::test_spec_from_dict
/debug после merge main упал test_workspace_flow
/debug AttributeError в gui/toolbar_router.py при загрузке проекта
```

## Когда НЕ вызывать

- Очевидная опечатка → просто правь сам
- Задача ещё не реализована → это не debug, а implement
- Нужен полный рефакторинг → это teamlead, не debugger

## Автоматическая активация

`/pipeline` автоматически вызывает debugger при FAIL от tester (итерации 1 и 2). Ручной `/debug` нужен когда цикл `/pipeline` не запущен, или Director хочет диагностику вне пайплайна.
