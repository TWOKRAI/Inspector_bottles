# TCP-симулятор робота Delta (universal3)

Modbus-TCP slave с поведением `cvt_universal_full.lua` — для разработки и
тестирования рецептов **без физического робота**.

## Быстрый старт

```bash
# Терминал 1: поднять симулятор (127.0.0.1:5021, unit 2)
python -m Services.robot_comm.server

# Терминал 2: запустить рецепт (после правки host/port в YAML, см. ниже)
python multiprocess_prototype/run.py hikvision_letter_robot
```

## Как направить рецепт на симулятор

В файле рецепта (например `multiprocess_prototype/recipes/hikvision_letter_robot.yaml`)
секция `devices:` содержит транспорт робота. Для работы с симулятором замените
`host` и `port`:

```yaml
devices:
  robot_main:
    driver: robot
    transport:
      type: tcp
      host: 127.0.0.1       # было 192.168.1.7
      port: 5021             # было 502
      unit_id: 2
```

## Параметры CLI

```
python -m Services.robot_comm.server [--host HOST] [--port PORT] [--unit UNIT]
```

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `--host` | `127.0.0.1` | Адрес слушателя |
| `--port` | `5021` | Порт Modbus-TCP |
| `--unit` | `2` | Modbus unit_id робота |

Для доступа с другой машины (например телефон-пульт через Wi-Fi):
```bash
python -m Services.robot_comm.server --host 0.0.0.0 --port 502
```

## Эмулируемые режимы

| Режим | MODE | Статус | Описание |
|-------|------|--------|----------|
| CVT (pick-place) | 0 | Полностью | Задание + трекинг ленты по энкодеру + поза укладки |
| DRAW (рисование) | 1 | Полностью | Полилиния + окружность, батчи, abort |
| MANUAL (jog) | 2 | Только регистры | Клиент пишет, sim не двигает (ручной jog для калибровки) |
| RETURN (возврат) | 3 | Полностью | Забор из слота + handshake |
| TOOLCHANGE (смена) | 4 | Полностью | target + handshake + обновление tool_cur |

Дополнительно: зеркало ПЧ (VFD bridge 0x1200/0x1210), энкодер (растущий),
телеметрия с heartbeat.

## Зависимости

Требуется `pymodbus` (extra `[modbus]`):
```bash
pip install '.[modbus]'
```

Без pymodbus пакет `robot_comm` работает (FakeRobotTransport для тестов),
но TCP-сервер не поднимется.

## Архитектура

```
SimRobotServer
  +-- pymodbus StartTcpServer  (Modbus-TCP slave, поток server)
  +-- RobotSimCore             (конечный автомат, чистая логика)
  +-- ticker-поток             (tick() каждые 10мс = Motion-цикл)
```

`RobotSimCore.attach()` привязывает ядро к живому списку регистров сервера
(GIL-безопасная мутация); клиент видит изменения немедленно.
