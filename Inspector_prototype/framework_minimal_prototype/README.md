# framework_minimal_prototype

Минимальное приложение на базе [multiprocess_framework](../multiprocess_framework): отдельный «пустой» прототип для пошаговой отладки фреймворка и демонстрации типового запуска процессов.

## Назначение

- Проверять полный путь **SystemLauncher → ProcessManagerProcess → дочерний процесс** без GUI, регистров и бизнес-логики Inspector.
- Использовать как основу для постепенного усложнения (второй процесс, очереди, команды и т.д.).

## Что делает сейчас

Запускается **один** дочерний процесс `counter`, наследник `ProcessModule`. В `run()` после `super().run()` он раз в секунду печатает в stdout числа от 1 до 10, затем выставляет `stop_process`, чтобы раннер завершил цикл и вызвал `shutdown()`.

## Схема

```mermaid
flowchart LR
  main[main.py]
  launcher[SystemLauncher]
  pm[ProcessManagerProcess]
  cnt[CounterProcess]
  main --> launcher
  launcher --> pm
  pm --> cnt
```

## Структура

| Путь | Роль |
|------|------|
| [main.py](main.py) | Точка входа: `sys.path`, `SystemLauncher`, `add_process(*process(CounterConfig()))`, `run()` |
| [backend/processes/counter_process.py](backend/processes/counter_process.py) | `CounterProcess` — логика счётчика |
| [backend/configs/counter_config.py](backend/configs/counter_config.py) | `CounterConfig` — имя процесса и `class_path` |
| [backend/configs/base_config.py](backend/configs/base_config.py), [proc_assembly.py](backend/configs/proc_assembly.py), [managers_schema_lite.py](backend/configs/managers_schema_lite.py) | Сборка `proc_dict` по образцу `multiprocess_prototype_v2` |

Фреймворк импортируется только из `multiprocess_framework.modules.*`.

## Запуск

Из корня репозитория:

```bash
python Inspector_prototype/framework_minimal_prototype/main.py
```

Каталог логов по умолчанию: `framework_minimal_prototype/logs`. Переопределение: переменная окружения `INSPECTOR_LOG_DIR` (как в v2).

## Примечания

- Дочерний процесс проходит полную инициализацию `ProcessModule` (менеджеры, очереди и т.д.) — это тяжелее «голого» `multiprocessing.Process`, но соответствует реальному использованию фреймворка.
- В консоли или логах оркестратора при отладке могут появляться сообщения об ошибках внутри **ProcessManager** (мониторинг, приоритеты и т.п.); они не относятся к коду счётчика и зависят от версии фреймворка.

## Дальше

Имеет смысл по мере необходимости добавлять второй процесс, обмен сообщениями, сокращённый набор менеджеров или сценарии остановки — без раздувания этого пакета до полного Inspector.
