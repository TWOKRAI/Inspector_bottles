# Заметки: pickle-баг SharedResourcesManager (перенос из корневого README)

> **Происхождение:** этот файл — исходное содержимое корневого `README.md`
> (кодировка UTF-16LE, 27 строк рабочих заметок про pickle-ошибку
> `SharedResourcesManager`). Заметки НЕ были документацией проекта, поэтому в рамках
> задачи NEW-8 (волна В0) корневой `README.md` переписан как настоящий README, а эти
> заметки сохранены здесь без потери содержания.

---

## 2. Где возникает ошибка pickle

Ошибка: `Can't pickle local object 'SharedResourcesManager.__getattr__.<locals>.<lambda>'`

Причина:

- `SharedResourcesManager` наследует `BaseManager` и `ObservableMixin`.
- В `BaseManager.__getattr__` и `SharedResourcesManager.__getattr__` для некоторых
  атрибутов возвращается `lambda *a, **kw: None`.
- Локальные `lambda` нельзя сериализовать через pickle.
- На Windows используется `spawn`, поэтому все аргументы `Process` сериализуются.
- При `process.start()` pickle пытается сериализовать `shared_resources` и натыкается
  на эту lambda.

Почему первый уровень (`ProcessManagerProcess`) может работать, а второй
(`process_test_1`) — нет: после инициализации `ProcessManagerProcess` объект
`shared_resources` мог измениться (добавлены очереди, вызовы `__getattr__` и т.п.), и при
повторной сериализации pickle находит ссылку на lambda.

## 3. Где создаются ресурсы сейчас

| Компонент | Где создаётся | Где хранится |
|-----------|---------------|--------------|
| `SharedResourcesManager` | `ProcessManagerBootstrap` (главный процесс) | Передаётся в `ProcessManagerProcess` |
| `ProcessStateRegistry` | Внутри `SharedResourcesManager` | `process_state_registry` |
| Очереди (`Queue`) | `ProcessManagerCore` → `QueueRegistry.create_and_register_queues()` | `ProcessStateRegistry` → `ProcessData.queues_dict` |
| События (`Event`) | `EventManager` | `ProcessData._events_dict` |
| Конфиг процесса | `proc_config` dict | `ProcessData.custom['process_config']` |

Очереди создаются в `ProcessManagerProcess` (через `QueueRegistry`), а не в главном
процессе. Конфиг (`queues: {system: {maxsize: 100}, ...}`) приходит в
`ProcessManagerCore.create_process()` и там используется.

## 4. Идея (как она была понята)

Главный процесс:

1. Создаёт `SharedResourcesManager` один раз.
2. Читает конфиги процессов (очереди, события, память — как текст/словарь).
3. Создаёт все `Queue`, `Event`, shared memory в `shared_resources`.
4. Формирует «address map» — общий словарь с именами/адресами.
5. Передаёт каждому процессу только этот map (не весь `SharedResourcesManager`).

## 5. Вопросы для уточнения

1. **Где должен жить главный процесс?** Сейчас главный — это скрипт, который создаёт
   Bootstrap и запускает `ProcessManagerProcess`. `ProcessManagerProcess` — первый дочерний
   процесс. Имеется в виду:
   - A) Всё создавать в скрипте до запуска `ProcessManagerProcess`?
   - B) `ProcessManagerProcess` считать «главным» и создавать ресурсы в нём, а
     `process_test_1`/`process_b` — только получать map?
2. **Формат «address map».** `Queue` и `Event` можно передавать между процессами (они
   pickle-able). Что именно должно быть в map:
   - A) Ссылки на `Queue`/`Event` (объекты) — чтобы процесс мог `queue.put()` / `event.set()`?
   - B) Только имена/идентификаторы — тогда дочерний процесс должен как-то подключаться к
     уже созданным объектам (на Windows это сложнее)?
3. **Маршрутизация.** Сейчас `RouterManager` использует `shared_resources` для доступа к
   очередям. Если передавать только map с `Queue`/`Event`, `RouterManager` в дочернем
   процессе должен работать с этим map, а не с `SharedResourcesManager`. Готовы ли менять
   `RouterManager` под такую модель?
4. **`ProcessData` и config.** Сейчас config процесса берётся из
   `shared_resources.get_process_data(name)`. Если `shared_resources` не передавать, config
   нужно класть в map. Подходит ли формат
   `{process_name: {queues: {...}, events: {...}, config: {...}}}`?
5. **Минимальный фикс vs архитектурный рефакторинг:**
   - Вариант A: Заменить lambda в `__getattr__` на модульную функцию-заглушку (например,
     `def _noop(*a, **kw): return None`) — быстрое исправление pickle.
   - Вариант B: Реализовать архитектуру (`SharedResourcesManager` только в главном, передача
     только map).

   Какой вариант приоритетнее на этом этапе?
