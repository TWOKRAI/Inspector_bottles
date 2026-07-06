---
description: Run the Debugger agent (Sonnet) — diagnose failing tests, regressions, puzzling errors
---

Запусти агента **debugger** (Sonnet) для диагностики проблемы.

Входные данные: $ARGUMENTS — описание бага, команда воспроизведения, или путь к failing-тесту.

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи проблему: `/dev:debug <описание>` или `/dev:debug pytest <путь>::<тест>`
   > Например: `/dev:debug pytest tests/test_router.py::test_channel_dispatch`

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
/dev:debug pytest tests/unit/test_models.py::test_spec_from_dict
/dev:debug после merge main упал test_workspace_flow
/dev:debug AttributeError в gui/toolbar_router.py при загрузке проекта
```

## Когда НЕ вызывать

- Очевидная опечатка → просто правь сам
- Задача ещё не реализована → это не debug, а implement
- Нужен полный рефакторинг → это teamlead, не debugger

## Автоматическая активация

`/dev:pipeline` автоматически вызывает debugger при FAIL от tester (итерации 1 и 2). Ручной `/dev:debug` нужен когда цикл `/dev:pipeline` не запущен, или Director хочет диагностику вне пайплайна.
