# C-60 — отвергнутые формы, затронутые плагины, C-60.b

> Часть брифа [`C-60.md`](C-60.md), вынесена по размеру (ред. 2). Тестеру не передаётся.

## Отвергнутые формы

- **Ф2 — зарегистрировать `plugins` после `workers` (`shutdown` плагина раньше ожиданий).** `shutdown` освобождает
  ресурсы, пока воркеры данных ещё зовут `process()`/`produce()` и операции исполнителя ещё идут (камера отпущена под
  `produce`, `DeviceHubPlugin` отключает драйверы под операцией `device_io`). Меняет поведение всех плагинов и
  `GOLDEN_ORDER`. Против принципа 5 владельца.
- **Ф3 — запись `Stoppable` плагинов в фазе 1 (вызов уже на `stop()` = `cancel()`, `process_module.py:1394-1406`).**
  Фаза 1 по контракту не блокирует (`keyed_executor.py:251`, `lifetime.py:538-561` зовёт `request_stop` записей подряд
  на потоке вызвавшего `stop()`). Плагин, которому надо ждать (стоп роботов `request_stop_all` ждёт потоки до срока,
  `Services/device_hub/manager.py:176-183`), держал бы поток `stop()` и фазу 1 соседних записей; иначе каждому такому
  плагину нужен свой поток — лишний слой. Выигрыш во времени нулевой: раннер зовёт `close_root()` сразу после
  `stop()` (`runner/process_runner.py:191-198`, `:474-481`).
- **Ф4 — править `lifetime.py` (порядок фаз) или `KeyedExecutor` (ждать после `plugins`).** `lifetime.py` —
  `base_manager`, общий для всех областей, вне границы полосы Ф (`plans/lifecycle-stop-ownership.md:456-460`);
  `KeyedExecutor` не единственный ждущий — `workers` ждёт те же потоки раньше (см. сверку п.2). Не чинит.
- **Ф5 — перенести запись `executors`/область исполнителей после `plugins`.** Та же причина: `workers` ждёт первым.

## Затронутые плагины и C-60.b

Инвентарь — Grep `create_worker`, `executor=` вне тестов, 2026-10-28:
- исполнитель процесса — только `DeviceHubPlugin` (`Plugins/hub/device_hub/plugin.py:252-274`, 10 операций
  `device_io`, `Services/device_hub/spi.py:359-426`; исполнитель — `multiprocess_prototype/backend/topology/base.yaml:37-38`).
  Это файловый ввод-вывод данных робота: долгой операции в продукте сегодня нет, симптом латентный.
- свои воркеры (долгая работа в потоке тоже держит `shutdown` до `W`): `Plugins/calibration/camera_robot`,
  `Plugins/hub/device_hub`, `Plugins/io/{database, robot_draw, robot_io, telemetry_sink}`, `Plugins/runtime/worker_pool`,
  `Plugins/sim/robot_host`, `Plugins/sources/heartbeat`, `Plugins/utility/pilot_widgets`, `Services/modbus/plugin`.
- **Поведение не меняется ни у одного плагина:** хук по умолчанию пуст; `request_stop` у классов плагинов нет
  (есть у драйвера `Services/device_hub/drivers/robot_driver_v2/stop.py:34` и протокола `Services/device_hub/spi.py:147`).

**C-60.b (полоса Р2, не здесь; запись для координатора):**
- Место: `Plugins/hub/device_hub/plugin.py:295` (`self._manager.request_stop_all(deadline)` в `shutdown`) → в новый хук
  `request_stop(ctx)`; `shutdown` оставляет повтор (лишнюю запись отсекает защёлка драйвера, `manager.py:136-139`).
- **Хук должен запускать стоп, а не ждать.** `request_stop_all` ждёт потоки стопа до срока (`manager.py:176-183`;
  умолчание срока `_STOP_ALL_DEFAULT_S` = 2,5 с, `manager.py:43`; в `shutdown` хаба срок 3,0 − 0,5 с,
  `plugin.py:54-55`). Перенос как есть: при `W` = 3,0 воркерам останется 0,5 с, при `W` < 2,5 — 0 → выжившие (H2b).
- Приёмка Р2: плагин получает стоп (рассылка стопа роботам начата) до ожидания исполнителя `device_io`; метка/лог
  момента рассылки — в их задаче (у успешного `request_stop_all` строки лога нет).
- Файл — граница Р2 (`plans/lifecycle-stop-ownership.md:462`); робот-файлы не трогаются ни там, ни здесь.
