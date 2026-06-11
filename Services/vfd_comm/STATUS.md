# vfd_comm — статус

**Дата:** 2026-06-11 · **Статус:** ✅ Фаза 2 готова (клиент моста + закладка DIRECT)

## Сделано

- [x] `VfdClient` поверх `RegisterTransport` (порт vfd_* из pc_full.py):
  run/set_freq/stop/reset_fault — атомарно, FLAG последним
- [x] `poll()` — пульс VFD_FLAG как poll-триггер (зеркало обновляется только
  по команде — семантика реального Lua) + `ensure_alive()` по heartbeat
- [x] Карты: BRIDGE_MAP (mailbox робота) + DIRECT_MAP (закладка прямого RTU
  по мануалу GD20, поля heartbeat/comm_errors опциональны)
- [x] `service.py` — карточка каталога без транспорта
- [x] Тесты: 15 (юнит-стаб + интеграция через FakeRobotTransport)

## Не сделано / дальше

- [x] ~~Плагин vfd_control~~ → удалён; логика в `Services/device_hub/drivers/vfd_driver.py`
- [ ] Проверка на железе (run/stop крутит ленту)
- [ ] Lua-улучшения: idle-публикация зеркала (№1), VFD_FLAG в DRAW (№2)
- [ ] Прямой RTU-путь: код команд GD20 поверх DIRECT_MAP — при появлении линии

## Зависимости

`Services.modbus` (RegisterTransport/RegisterMap). robot_comm — НЕ импортируется
(мост связывает плагин). Тесты используют фейк-робота из robot_comm.testing.
