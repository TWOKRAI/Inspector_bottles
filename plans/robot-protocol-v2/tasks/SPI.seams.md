# SPI хаба — SPI.f (швы `_client` в тестах) и SPI.g (затвор переподключения)

Бриф — `tasks/SPI.md`. Каждая — отдельный бриф-запуск (файлов больше 6). База main `9b6645546`.

## SPI.f — внедрение клиента вместо `drv._client` (решение лида В3)

Факт: `git grep -nE '\._client\b' -- Services/device_hub/tests Plugins/hub/device_hub/tests` → 59; вне задачи 16
(`test_robot_driver.py` 13, `test_vfd_driver.py` 3 — свои клиенты v1/ПЧ); в задаче 43 (6 присваиваний `._client =`,
остальное — чтения для подмены `client.run_chunks` / `client.cmd` и проверок).

Почему не просто `client=`: драйвер создаёт клиент один раз в `connect` (`robot_driver_v2/driver.py:338-339`:
`if self._client is None: self._client = RobotClientV2(self._transport, self._cfg)`), а `self._cfg` строит конструктор из
`entry.params` по закрытому списку `_CLIENT_KEYS` (:150-153). С `client=` тест дублировал бы это отображение или брал
умолчания и расходился с боевой сборкой. Шов — класс (фабрика), а не экземпляр. (Обёртка журналом, :335-337, в тестах не
ставится — транспорт внедрён.) Поэтому шов — **фабрика**:

`_RobotDriverCore.__init__(…, client_factory: Callable[[Any, ClientV2Config], RobotClientV2] | None = None)`; в
`connect`: `self._client = (self._client_factory or RobotClientV2)(self._transport, self._cfg)`. Тест передаёт фабрику,
которая создаёт клиент (настоящий или подменный) и сохраняет ссылку у себя; чтения `drv._client` заменяются этой ссылкой.
Публичного свойства `client` нет. `DeviceManager` фабрику не передаёт (прод без изменений).

Риск (стадия 0 р.2): 25 вызовов `get_driver(` в тестах двух каталогов получают драйвер у менеджера и фабрику передать не
могут. Путь — `register_driver_factory("robot", …)` (как `test_c29_probe.py:86`, `test_robot_v2_commands_acceptance.py:456`),
но сборке драйвера нужны `spawn` и `store` менеджера. **Правило для teamlead:** если без приватного имени не выходит —
стоп и вопрос лиду; приватное не вводить.

Файлы (13 тестовых + 2): `driver.py` (параметр, докстринг), `README.md` пакета; тесты по списку `git grep` выше (среди них
слепые приёмочные тесты стопа: `test_c29_disconnect_acceptance.py`, `test_robot_v2_t53g_blind.py`,
`test_robot_v2_t53h_blind.py`, `Plugins/hub/device_hub/tests/test_t53r2_stop_hazards.py`); `test_no_private_driver_state.py`
— ключ `_client` из `_SEAMS` убрать, `_SCANNED_FILES` — литерал.

Критерии:
- `git grep -nE '\._client\b' -- Services/device_hub/tests Plugins/hub/device_hub/tests` → ровно 16 строк, все в
  `test_robot_driver.py` и `test_vfd_driver.py`.
- AST-дифф по каждому изменённому тестовому файлу: множество `ast.dump` узлов `Assert` и множество литералов-констант
  внутри них — до и после равны (скрипт в scratchpad, вывод — в отчёт). Пусто = тесты проверяют то же.
- Число собранных тестов (`pytest --collect-only -q`) до и после равно.
- После — выборочные инъекции лида по 3 свойствам стопа (один стоп на выключение, SOFT при «Отключить» после A3,
  отказ jog в окне C-29); прогноз пишет лид.

## SPI.g — затвор `_reconnect_due` (решение лида В6), последней подзадачей

Три копии (`robot_driver.py:548-552`, `vfd_driver.py:264-268`, `robot_driver_v2/driver.py:499-505`) различаются телом:
v1 и ПЧ возвращают `False` / снимок, v2 идёт под `_param_lock` с повторной проверкой `desired_connected` (T5.3h) и
закрытием хвоста. Общая часть одна — затвор: «прочитать часы, сравнить с меткой, поставить метку».

В базу: атрибут класса `RECONNECT_THROTTLE_S: ClassVar[float]` и метод `_reconnect_due(self) -> bool` (часы
`self._clock`, метка `self._last_reconnect`). Подклассы задают свои значения (v1 2,0 — `robot_driver.py:29`; ПЧ 3,0 —
`vfd_driver.py:19`; v2 — `texts._RECONNECT_THROTTLE_SEC`) и начальную метку (ПЧ `-inf`, `vfd_driver.py:63`; v1, v2 `0.0`).
`_record_reconnect` остаётся у вызывающего (как сейчас). Тело `_attempt_reconnect` / `_ensure_connected` v2 не двигать.
Имена швов `_last_reconnect` (5), `_reconnect_attempts` (6) — остаются (в базе). Гварды: `test_robot_v2_t53g_*`,
`test_robot_v2_t53h_*`, `test_c29_*`, `test_reconnect_exhausted_notice.py`, `test_vfd_driver.py`, `test_robot_driver.py`;
стенд S0–S3 (ADR-DH-011). Критерий: интервалы и начальные метки — литералы в тесте, по классу.
