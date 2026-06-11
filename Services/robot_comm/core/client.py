"""RobotClient — клиент робота Delta поверх универсального Services/modbus.

Порт отлаженного на железе ``robot/universal3/pc_full.py`` (класс Robot):
семантика и байты на проводе 1:1, транспорт заменён на ModbusDevice
(``transaction`` = серия записей под одним Lock, abort на первой ошибке).

Инварианты протокола:
- маркер-флаг (job_flag / cfg_flag / draw_flag / vfd_flag) пишется ПОСЛЕДНЕЙ
  операцией каждой транзакции — робот не должен прочитать неполные данные;
- abort-семантика transaction гарантирует, что флаг не ляжет поверх частично
  записанных данных (осознанное отличие от оригинала, см. DECISIONS.md);
- режим переключается только когда робот свободен (Motion-цикл Lua читает
  REG_MODE раз за итерацию).

Клиент сам реализует RegisterTransport — это мост для vfd_comm
(ПК -> робот по TCP, робот -> ПЧ по RS-485).

Ошибки I/O — ``ModbusDriverError`` (единая иерархия транспорта), доменные —
``RobotJobError`` и др. из errors.py.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from Services.modbus import ModbusDevice

from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.core.datatypes import DrawPoint, JobEcho, RobotPosition, Telemetry
from Services.robot_comm.core.registers import (
    DRAW_TYPE_CIRCLE,
    DRAW_TYPE_POLYLINE,
    MODE_CVT,
    MODE_DRAW,
    PTS_MAX,
    REG_PTS_BASE,
    SERVO_OFF,
    SERVO_ON,
    WRITE_CHUNK,
    XY_SCALE,
    build_register_map,
)
from Services.robot_comm.errors import RobotJobError
from Services.robot_comm.interfaces import DeviceTransport

ProgressCallback = Callable[[dict[str, Any]], None]

_MODES = {"cvt": MODE_CVT, "draw": MODE_DRAW}

# Тайминги рисования (из боевого pc_full.py)
DRAW_TIMEOUT_S = 120.0  # максимум на один проход (батч) рисования
_BUSY_RISE_S = 1.0  # ждать установки busy после старта прохода
_POLL_FAST_S = 0.01
_POLL_SLOW_S = 0.05


class RobotClient:
    """Клиент робота: CVT pick-place + рисование + конфиг + телеметрия.

    Lifecycle — модель владельца: создаёт/коннектит/закрывает ТОЛЬКО плагин
    robot_io (публикует в ``runtime``); потребители берут готовый экземпляр.

    Args:
        config:    Параметры подключения/лимиты (RobotConfig).
        transport: Инъекция транспорта для тестов (FakeRobotTransport).
                   По умолчанию — ModbusDevice из config.
        clock/sleep: Инъекция времени для детерминированных тестов рисования.
    """

    def __init__(
        self,
        config: RobotConfig | None = None,
        *,
        transport: DeviceTransport | None = None,
        on_progress: ProgressCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = config or RobotConfig()
        self._map = build_register_map(self._cfg.word_order)
        self._device: DeviceTransport = (
            transport if transport is not None else ModbusDevice(self._cfg.to_modbus_config())
        )
        self._on_progress = on_progress
        self._clock = clock
        self._sleep = sleep

    # ------------------------------------------------------------------ #
    # Соединение / статус
    # ------------------------------------------------------------------ #

    @property
    def config(self) -> RobotConfig:
        """Текущий конфиг клиента."""
        return self._cfg

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение с роботом."""
        return self._device.is_connected

    def connect(self) -> bool:
        """Подключиться к роботу."""
        return self._device.connect()

    def disconnect(self) -> None:
        """Закрыть соединение (graceful — обязан звать владелец в shutdown)."""
        self._device.disconnect()

    def get_status(self) -> dict[str, Any]:
        """Статус транспорта + адрес робота."""
        status = self._device.get_status()
        status["robot"] = self._cfg.describe()
        return status

    # ------------------------------------------------------------------ #
    # RegisterTransport (мост для vfd_comm)
    # ------------------------------------------------------------------ #

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Читать регистры робота (включая mailbox ПЧ — мост)."""
        return self._device.read_registers(address, count)

    def transaction(self, ops: list[tuple]) -> bool:
        """Атомарная серия записей под Lock устройства (мост)."""
        return self._device.transaction(ops)

    # ------------------------------------------------------------------ #
    # Режим
    # ------------------------------------------------------------------ #

    def set_mode(self, mode: str) -> bool:
        """Переключить режим ``cvt`` | ``draw``.

        Переключать ТОЛЬКО когда робот свободен: Lua применяет режим раз за
        итерацию Motion-цикла, при занятом роботе переключение «зависнет».
        """
        if mode not in _MODES:
            raise ValueError(f"mode: ожидается 'cvt' | 'draw', получено {mode!r}")
        return self._write_map({"mode": _MODES[mode]})

    # ------------------------------------------------------------------ #
    # CVT
    # ------------------------------------------------------------------ #

    def read_encoder(self) -> int:
        """Живой энкодер конвейера (DW, word_order из конфига)."""
        return int(self._map.read(self._device, "encoder"))

    def read_enc_raw(self) -> list[int]:
        """Сырые два слова энкодера — для CLI-команды ``cal`` (подбор word order)."""
        entry = self._map.entry("encoder")
        return self._device.read_registers(entry.address, 2)  # type: ignore[union-attr]

    def is_free(self) -> bool:
        """Свободен ли робот (1 = ждёт задание)."""
        return self._map.read(self._device, "free") == 1

    def job_accepted(self) -> bool:
        """Принял ли робот задание: job_flag сброшен в 0."""
        return self._map.read(self._device, "job_flag") == 0

    def send_job(self, x_mm: float, y_mm: float, e_capture: int) -> bool:
        """Отправить CVT-задание: X, Y, E_capture(DW), маркер — одной транзакцией.

        Raises:
            RobotJobError: координата вне ±xy_limit_mm (предел s16 при scale=10).
        """
        limit = self._cfg.xy_limit_mm
        if abs(x_mm) > limit or abs(y_mm) > limit:
            raise RobotJobError(f"Координата вне ±{limit} мм: X={x_mm}, Y={y_mm}")
        return self._write_map(
            {
                "job_x": x_mm,
                "job_y": y_mm,
                "job_ecap": e_capture,
                "job_flag": 1,  # маркер — последним
            }
        )

    def read_echo(self) -> JobEcho:
        """Эхо последнего принятого задания (блок 0x1120)."""
        data = self._map.read(self._device, "echo")
        return JobEcho(**data)  # type: ignore[arg-type]

    def stop(self, mode: int) -> bool:
        """Стоп робота: 1=домой+остаться в цикле, 2=домой+выход, 3=на месте."""
        if mode not in (1, 2, 3):
            raise ValueError(f"stop: режим 1|2|3, получено {mode!r}")
        return self._write_map({"stop": mode})

    def set_servo(self, on: bool) -> bool:
        """Серво ON/OFF (Lua: 1=on, 2=off)."""
        return self._write_map({"servo": SERVO_ON if on else SERVO_OFF})

    # ------------------------------------------------------------------ #
    # Телеметрия
    # ------------------------------------------------------------------ #

    def read_telemetry(self) -> Telemetry:
        """Полная телеметрия (блок 0x1130, 11 слов)."""
        data = dict(self._map.read(self._device, "telemetry"))
        data["moving"] = data["moving"] == 1
        data["servo"] = data["servo"] == 1
        for key in ("spd_pct", "belt_mm_s", "hand", "heartbeat", "miss_count"):
            data[key] = int(data[key])
        return Telemetry(**data)

    def read_position(self) -> RobotPosition:
        """Текущая поза инструмента — главное для калибровки."""
        return self.read_telemetry().position

    # ------------------------------------------------------------------ #
    # Конфиг робота (read-modify-write всего блока + маркер)
    # ------------------------------------------------------------------ #

    def get_config(self) -> dict[str, Any]:
        """Прочитать конфиг-блок (speed, home_*, pick_z, place_*, grip_ms, zone_*)."""
        return dict(self._map.read(self._device, "config"))

    def set_config(self, **fields: float) -> bool:
        """Записать поля конфига: читаем блок, меняем поля, пишем блок + маркер.

        Raises:
            KeyError: неизвестное имя поля (валидно только из CONFIG_FIELDS).
        """
        current = self.get_config()
        for name in fields:
            if name not in current:
                raise KeyError(f"Неизвестный параметр конфига: {name!r}; есть: {sorted(current)}")
        current.update(fields)
        return self._write_map({"config": current, "cfg_flag": 1})

    # Тонкие обёртки (REPL-команды spd/home/place/zpick/zone/grip — 1:1)
    def set_speed(self, pct: int) -> bool:
        """Скорость движения, % (1..100)."""
        if not 1 <= pct <= 100:
            raise ValueError(f"speed: 1..100, получено {pct}")
        return self.set_config(speed=pct)

    def set_home(self, x: float, y: float, z: float) -> bool:
        """Домашняя позиция."""
        return self.set_config(home_x=x, home_y=y, home_z=z)

    def set_place(self, x: float, y: float, z: float) -> bool:
        """Позиция укладки."""
        return self.set_config(place_x=x, place_y=y, place_z=z)

    def set_pick_z(self, z: float) -> bool:
        """Высота захвата."""
        return self.set_config(pick_z=z)

    def set_zone(self, r_max: float, r_min: float | None = None) -> bool:
        """Рабочая зона (макс/мин радиус)."""
        fields: dict[str, float] = {"zone_max": r_max}
        if r_min is not None:
            fields["zone_min"] = r_min
        return self.set_config(**fields)

    def set_grip_time(self, sec: float) -> bool:
        """Время удержания схвата, сек (хранится в мс)."""
        return self.set_config(grip_ms=round(sec * 1000))

    # ------------------------------------------------------------------ #
    # Рисование
    # ------------------------------------------------------------------ #

    def set_pen(self, down_mm: float, up_mm: float) -> bool:
        """Высоты пера: опущено/поднято (Z, мм)."""
        return self._write_map({"pen_down": down_mm, "pen_up": up_mm})

    def set_draw_speed(self, pct: int) -> bool:
        """Скорость рисования, % (клампится в 1..100 как в оригинале)."""
        return self._write_map({"draw_spd": max(1, min(100, pct))})

    def set_overlap(self, mm: float) -> bool:
        """Скругление углов (PASS), мм."""
        return self._write_map({"overlap": max(0.1, mm)})

    def draw_busy(self) -> bool:
        """Идёт ли рисование."""
        return self._map.read(self._device, "draw_busy") == 1

    def draw_progress(self) -> int:
        """Индекс текущей точки прохода."""
        return int(self._map.read(self._device, "draw_prog"))

    def draw_abort(self) -> bool:
        """Прервать рисование (перо вверх, домой)."""
        return self._write_map({"draw_abort": 1})

    def draw_circle(self, cx: float, cy: float, r: float, timeout: float = DRAW_TIMEOUT_S) -> bool:
        """Круг родным MCircle робота: центр + радиус, одной командой (гладко)."""
        ok = self._write_map(
            {
                "circ_cx": cx,
                "circ_cy": cy,
                "circ_r": r,
                "draw_type": DRAW_TYPE_CIRCLE,
                "draw_flag": 1,  # маркер — последним
            }
        )
        if not ok:
            return False
        return self._wait_draw_done(timeout)

    def draw(self, points: list[DrawPoint] | list[tuple], timeout: float = DRAW_TIMEOUT_S) -> bool:
        """Полилиния: точки пачками по PTS_MAX, каждая пачка — отдельный проход.

        Два уровня чанкования (оба обязательны, робот не тянет большие блоки):
        - WRITE_CHUNK=30 регистров на один write_registers при заливке буфера;
        - PTS_MAX=100 точек на проход, между пачками — ожидание завершения.
        """
        pts = [p if isinstance(p, DrawPoint) else DrawPoint(*p) for p in points]
        if not pts:
            raise RobotJobError("Пустой путь рисования")
        total = len(pts)
        for start in range(0, total, PTS_MAX):
            batch = pts[start : start + PTS_MAX]
            self._emit_progress(
                {"stage": "batch", "batch": start // PTS_MAX + 1, "done": start + len(batch), "total": total}
            )
            if not self._run_batch(batch, timeout):
                return False
        self._emit_progress({"stage": "done", "total": total})
        return True

    # --- внутреннее рисование ---

    def _upload_points(self, pts: list[DrawPoint]) -> bool:
        """Залить точки в буфер чанками по WRITE_CHUNK регистров."""
        regs: list[int] = []
        for p in pts:
            regs += [
                round(p.x_mm * XY_SCALE) & 0xFFFF,
                round(p.y_mm * XY_SCALE) & 0xFFFF,
                1 if p.pen else 0,
            ]
        for offset in range(0, len(regs), WRITE_CHUNK):
            chunk = regs[offset : offset + WRITE_CHUNK]
            if not self._device.transaction([("wm", REG_PTS_BASE + offset, chunk)]):
                return False
        return True

    def _run_batch(self, batch: list[DrawPoint], timeout: float) -> bool:
        """Один проход: залить буфер, запустить, дождаться завершения."""
        if not self._upload_points(batch):
            return False
        ok = self._write_map(
            {
                "draw_type": DRAW_TYPE_POLYLINE,
                "draw_count": len(batch),
                "draw_flag": 1,  # маркер — последним
            }
        )
        if not ok:
            return False
        return self._wait_draw_done(timeout)

    def _wait_draw_done(self, timeout: float) -> bool:
        """Дождаться завершения прохода: busy должен подняться, затем упасть."""
        t0 = self._clock()
        while self._clock() - t0 < _BUSY_RISE_S and not self.draw_busy():
            self._sleep(_POLL_FAST_S)
        t0 = self._clock()
        while self._clock() - t0 < timeout:
            if self.draw_busy() is False:
                return True
            self._sleep(_POLL_SLOW_S)
        self._emit_progress({"stage": "timeout", "timeout_s": timeout})
        return False

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    def _write_map(self, values: dict[str, Any]) -> bool:
        """Записать значения по карте одной транзакцией (порядок ключей сохраняется)."""
        return self._device.transaction(self._map.write_ops(values))

    def _emit_progress(self, payload: dict[str, Any]) -> None:
        if self._on_progress is not None:
            self._on_progress(payload)
