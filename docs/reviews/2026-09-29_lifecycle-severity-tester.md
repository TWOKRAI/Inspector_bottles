# Тестер: уровень записи `stop summary:` (условие CTO, lifecycle-stop-ownership)

Файл: `multiprocess_framework/modules/process_manager_module/tests/test_stop_summary_severity.py` (24 теста, не закоммичен).

## Что пинится
- INFO: все дети чистые (1/2/5 детей).
- WARNING: reported=False с нулями (литерал CTO); released>0; buffered_dropped>0; оба вместе.
- Один плохой среди трёх чистых, каждый из 3 видов x позиции first/middle/last (9 тестов).
- Граница: 1 released -> WARNING, 1 dropped -> WARNING, 0/0/reported=True -> INFO.
- Ровно одна запись на вызов при любой тяжести; текст начинается с `stop summary:`;
  `extra.stop_summary` == литеральный словарь по каждому ребёнку (и на INFO тоже); `module == "ProcessManager"`.
- exit_report бросает -> `_publish_stop_summary` не бросает наружу.

## Граница наблюдения
Настоящий путь: `ObservableMixin.__init__(pm, managers={"logger": LoggerManager})` -> `LoggerManager` -> приёмник
`memory` (канал на SYSTEM и BUSINESS); читается `tail()`, поле `level` — литералы `"WARNING"`/`"INFO"`.
Мок `_log_warning` отвергнут: шпион на имя метода остаётся зелёным при выборе уровня через `_log(level=...)`.
Подставные: PM без `__init__` (`__new__` + patch, плюс `pm.name`), реестр с одним `exit_report`.

## Запуски
3 прогона: `24 passed in 0.12s` x3.

## Самопроверка на невакуумность (вне дерева, плагин в scratchpad, код не тронут)
Подмена `ObservableMixin._log_checked` для сообщений `stop summary:`:
- всё в "info": 15 failed, 9 passed (ожидалось 15 = 3 одиночных + 9 + смесь + оба + граница);
- всё в "warning": 4 failed (3 INFO-параметра + граница), 20 passed.
Это не заменяет break-injection лида по самому правилу в теле метода.

## Чего не читал / что утекло
Тело `_publish_stop_summary` (3468-3505) не читал. Утечки, честно:
1. Traceback пробного запуска (AttributeError: нет `name`) показал две строки тела: вызов
   `self._log_warning(msg, stop_summary=summary)` и что на пути есть `except`, зовущий `_log_error`.
   Условие выбора уровня не показано.
2. `grep -l "__new__"` по каталогу tests перечислил имя `test_stop_summary_hazards.py`; содержимое не открывал.
Существующие тесты про stop_summary не читал.

## Интерпретации
- «Один PM log record» = одна запись, дошедшая до приёмника за вызов (все скоупы канала).
- «Не бросает» проверил только для exit_report, бросающего RuntimeError; контракт не говорит, что публиковать при этом.

## Открыто / ненадёжно
- Пустой `stop_results` не покрыт: контракт молчит (INFO с пустым контекстом? запись вообще?).
- `stop_results` со значением False (выживший) не покрыт: в тестах везде True; зависит ли уровень от него — не проверял.
- Не проверен путь, когда логгер бросает: `_call_manager_result` глотает, но это уровень ObservableMixin, а не метода.
- Формат текста сообщения (числа, список не-отчитавшихся) намеренно не пинится.
- Зелёный прогон сам по себе не доказывает уровень: доказательство — break-injection лида по флипу условия в теле.
- Побочно: случайно создал пустую папку `C:\tmp_x` (опечатка в mkdir); удалить не смог (защита), удалите вручную.
