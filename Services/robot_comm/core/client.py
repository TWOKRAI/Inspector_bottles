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
from Services.robot_comm.core.datatypes import (
    DrawPoint,
    JobEcho,
    RobotPosition,
    Telemetry,
    split_draw_passes,
)
from Services.robot_comm.core.registers import (
    DRAW_TYPE_CIRCLE,
    DRAW_TYPE_POLYLINE,
    MODE_CVT,
    MODE_DRAW,
    MODE_MANUAL,
    MODE_RETURN,
    MODE_TOOLCHANGE,
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

_MODES = {
    "cvt": MODE_CVT,
    "draw": MODE_DRAW,
    "manual": MODE_MANUAL,
    "return": MODE_RETURN,
    "toolchange": MODE_TOOLCHANGE,
}

# Тайминги возврата (handshake как у рисования)
RETURN_TIMEOUT_S = 30.0  # максимум на одну букву (подвод + захват + траектория + домой)
_RET_ACCEPT_S = 3.0  # ждать приёма (ret_flag → 0)
_RET_BUSY_RISE_S = 5.0  # ждать старта (ret_busy → 1)

# Тайминги рисования (handshake прошивки cvt_universal_full.lua)
DRAW_TIMEOUT_S = 120.0  # максимум на завершение прохода (рисование + перо вверх + домой)
_ACCEPT_S = 3.0  # ждать приёма задания прошивкой (REG_DRAW_FLAG → 0); Motion-цикл ~0.02с
_BUSY_RISE_S = 10.0  # ждать старта прохода (подготовка пула distinct-точек в прошивке)
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
        on_data: Callable[[dict], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = config or RobotConfig()
        self._map = build_register_map(self._cfg.word_order)
        # on_data — хук wire-обмена (TX/RX) от ModbusDevice; используется драйвером
        # для публикации io_peek (панель «Вход/Выход» на странице устройства).
        self._device: DeviceTransport = (
            transport if transport is not None else ModbusDevice(self._cfg.to_modbus_config(), on_data=on_data)
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
        """Переключить режим ``cvt`` | ``draw`` | ``manual`` | ``return`` | ``toolchange``.

        Переключать ТОЛЬКО когда робот свободен: Lua применяет режим раз за
        итерацию Motion-цикла, при занятом роботе переключение «зависнет».
        """
        if mode not in _MODES:
            raise ValueError(f"mode: ожидается один из {sorted(_MODES)}, получено {mode!r}")
        return self._write_map({"mode": _MODES[mode]})

    # ------------------------------------------------------------------ #
    # MANUAL (ручной jog по Modbus)
    # ------------------------------------------------------------------ #

    def jog(
        self,
        dx_mm: float,
        dy_mm: float,
        speed_pct: int | None = None,
        *,
        absolute: bool = False,
    ) -> bool:
        """Ручной ход робота: смещение dX/dY (мм) при скорости speed_pct (Override %).

        Пишет mode=MANUAL + dx/dy/abs/spd и поднимает man_flag (маркер — последним).
        Lua в MODE=2 выполняет один MovL и сбрасывает man_flag. ``absolute=True`` —
        ехать в координату (X=dx, Y=dy), иначе смещение от текущей позы. Ход одной
        команды Lua обрезает до 200 мм (защита). Звать ТОЛЬКО когда робот свободен.

        Raises:
            RobotJobError: |dx|/|dy| вне предела s16 при scale=10.
        """
        limit = self._cfg.xy_limit_mm
        if abs(dx_mm) > limit or abs(dy_mm) > limit:
            raise RobotJobError(f"Ход вне ±{limit} мм: dX={dx_mm}, dY={dy_mm}")
        writes: dict[str, Any] = {
            "mode": MODE_MANUAL,
            "man_abs": 1 if absolute else 0,
            "man_dx": dx_mm,
            "man_dy": dy_mm,
        }
        if speed_pct is not None:
            writes["man_spd"] = int(speed_pct)
        writes["man_flag"] = 1  # маркер — последним
        return self._write_map(writes)

    def manual_busy(self) -> bool:
        """Идёт ли ручной ход (man_busy=1)."""
        return self._map.read(self._device, "man_busy") == 1

    def jog_abort(self) -> bool:
        """Прервать ручной ход (man_abort=1)."""
        return self._write_map({"man_abort": 1})

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

    def send_job(
        self,
        x_mm: float,
        y_mm: float,
        e_capture: int,
        place: tuple[float, float, float, float] | None = None,
        *,
        z_mm: float = 0.0,
    ) -> bool:
        """Отправить CVT-задание: X, Y, E_capture(DW) [+ Z захвата] [+ поза укладки], маркер — одной транзакцией.

        ``z_mm`` — глубина захвата на picke (Z, мм). 0 → ``job_z`` НЕ пишем, прошивка берёт
        дефолт Z_PICK (обратная совместимость; на проводе байт-в-байт как раньше). ≠0 → пишем
        ``job_z``; прошивка опускается на эту глубину и сбрасывает регистр после задания.

        ``place=(x, y, z, rz)`` — поза УКЛАДКИ (мм): робот кладёт диск в (x, y, z) под
        АБСОЛЮТНЫМ R=rz и возвращает R после (place_flag=1). ``rz`` уже абсолютный — драйвер
        опросил реальный R инструмента (телеметрия) и сложил с доворотом. Забор остаётся по
        (x_mm, y_mm) с трекингом ленты. Без ``place`` — старое поведение (укладка в фикс.
        config-место, place_flag не трогаем) → обратная совместимость.

        Raises:
            RobotJobError: координата съёма ИЛИ укладки вне ±xy_limit_mm (предел s16 при scale=10).
        """
        limit = self._cfg.xy_limit_mm
        if abs(x_mm) > limit or abs(y_mm) > limit:
            raise RobotJobError(f"Координата вне ±{limit} мм: X={x_mm}, Y={y_mm}")
        writes: dict[str, Any] = {"job_x": x_mm, "job_y": y_mm, "job_ecap": e_capture}
        if z_mm != 0.0:
            writes["job_z"] = z_mm  # глубина захвата; 0 → не трогаем, прошивка берёт Z_PICK
        if place is not None:
            px, py, pz, prz = place
            if abs(px) > limit or abs(py) > limit:
                raise RobotJobError(f"Координата укладки вне ±{limit} мм: X={px}, Y={py}")
            writes.update({"place_x": px, "place_y": py, "place_z": pz, "place_rz": prz, "place_flag": 1})
        writes["job_flag"] = 1  # маркер — последним
        return self._write_map(writes)

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
    # RETURN (возврат буквы на ленту, MODE=3)
    # ------------------------------------------------------------------ #

    def return_accepted(self) -> bool:
        """Прошивка подхватила задание возврата: ret_flag сброшен в 0."""
        return self._map.read(self._device, "ret_flag") == 0

    def return_busy(self) -> bool:
        """Идёт ли возврат (ret_busy=1)."""
        return self._map.read(self._device, "ret_busy") == 1

    def do_return(self, x_mm: float, y_mm: float, z_mm: float, timeout: float = RETURN_TIMEOUT_S) -> bool:
        """Вернуть одну букву на ленту: координата СЛОТА (x,y,z) + маркер, ждать завершения.

        Робот в MODE=3 берёт диск из (x,y,z), линейно поднимает/сдвигает/опускает
        (смещения — константы Lua) и роняет на ленту. Координату забора пишем, маркер
        ret_flag — последним (как job_flag/draw_flag). Звать ТОЛЬКО когда робот свободен
        и в режиме return (переключает драйвер). Handshake — как у рисования.

        Raises:
            RobotJobError: координата вне ±xy_limit_mm (предел s16 при scale=10).
        """
        limit = self._cfg.xy_limit_mm
        if abs(x_mm) > limit or abs(y_mm) > limit:
            raise RobotJobError(f"Координата возврата вне ±{limit} мм: X={x_mm}, Y={y_mm}")
        ok = self._write_map({"ret_x": x_mm, "ret_y": y_mm, "ret_z": z_mm, "ret_flag": 1})  # маркер — последним
        if not ok:
            return False
        return self._wait_return_done(timeout)

    def _wait_return_done(self, timeout: float) -> bool:
        """Дождаться завершения возврата: ret_flag→0 (приём) → ret_busy↑ (старт) → ret_busy↓ (готово).

        Контракт идентичен рисованию (см. _wait_draw_done): следующую букву нельзя слать,
        пока текущая не завершена, иначе перезапись координат на лету.
        """
        if not self._poll_until(self.return_accepted, _RET_ACCEPT_S, _POLL_FAST_S):
            self._emit_progress({"stage": "return_not_accepted"})
            return False
        if not self._poll_until(self.return_busy, _RET_BUSY_RISE_S, _POLL_FAST_S):
            self._emit_progress({"stage": "return_no_busy_rise"})
            return False
        if not self._poll_until(lambda: self.return_busy() is False, timeout, _POLL_SLOW_S):
            self._emit_progress({"stage": "return_timeout", "timeout_s": timeout})
            return False
        return True

    # ------------------------------------------------------------------ #
    # TOOLCHANGE (смена инструмента, MODE=4)
    # ------------------------------------------------------------------ #

    # Тайминги смены инструмента (handshake как у RETURN)
    _TOOL_TIMEOUT_S = 30.0  # максимум на всю смену (снять + надеть + домой)
    _TOOL_ACCEPT_S = 3.0  # ждать приёма (tool_flag → 0)
    _TOOL_BUSY_RISE_S = 5.0  # ждать старта (tool_busy → 1)

    def tool_accepted(self) -> bool:
        """Прошивка подхватила задание смены: tool_flag сброшен в 0."""
        return self._map.read(self._device, "tool_flag") == 0

    def tool_busy(self) -> bool:
        """Идёт ли смена инструмента (tool_busy=1)."""
        return self._map.read(self._device, "tool_busy") == 1

    def tool_current(self) -> int:
        """Текущий инструмент (зеркало REG_TOOL_CUR)."""
        return int(self._map.read(self._device, "tool_cur"))

    def do_toolchange(self, target: int, timeout: float | None = None) -> bool:
        """Сменить инструмент: target (0=снять/1/2) + маркер, ждать завершения.

        Робот в MODE=4 едет в гнездо текущего инструмента, снимает, едет в гнездо
        целевого, надевает, возвращается домой. Handshake — как у RETURN/DRAW.
        Звать ТОЛЬКО когда робот свободен и в режиме toolchange (переключает драйвер).

        Raises:
            ValueError: target вне допустимого диапазона 0..2.
        """
        if target not in (0, 1, 2):
            raise ValueError(f"toolchange target: 0|1|2, получено {target!r}")
        ok = self._write_map({"tool_target": target, "tool_flag": 1})  # маркер — последним
        if not ok:
            return False
        return self._wait_toolchange_done(timeout or self._TOOL_TIMEOUT_S)

    def _wait_toolchange_done(self, timeout: float) -> bool:
        """Дождаться завершения смены: tool_flag→0 → tool_busy↑ → tool_busy↓."""
        if not self._poll_until(self.tool_accepted, self._TOOL_ACCEPT_S, _POLL_FAST_S):
            self._emit_progress({"stage": "toolchange_not_accepted"})
            return False
        if not self._poll_until(self.tool_busy, self._TOOL_BUSY_RISE_S, _POLL_FAST_S):
            self._emit_progress({"stage": "toolchange_no_busy_rise"})
            return False
        if not self._poll_until(lambda: self.tool_busy() is False, timeout, _POLL_SLOW_S):
            self._emit_progress({"stage": "toolchange_timeout", "timeout_s": timeout})
            return False
        return True

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

    def draw_accepted(self) -> bool:
        """Прошивка подхватила задание рисования: REG_DRAW_FLAG сброшен в 0.

        Motion-цикл (cvt_universal_full.lua) читает REG_DRAW_FLAG==1 и СРАЗУ пишет 0 —
        надёжный сигнал приёма (как job_accepted для CVT), не зависящий от тайминга
        подъёма busy (между приёмом и busy=1 прошивка готовит пул точек).
        """
        return self._map.read(self._device, "draw_flag") == 0

    def draw_progress(self) -> int:
        """Индекс текущей точки прохода."""
        return int(self._map.read(self._device, "draw_prog"))

    def draw_abort(self) -> bool:
        """Прервать рисование (перо вверх, домой)."""
        return self._write_map({"draw_abort": 1})

    def draw_home_after(self, home: bool = True) -> bool:
        """Пометить, что после текущего/ближайшего прохода робот едет домой.

        Используется для Стопа: ставим перед draw_abort, чтобы прерванный проход в
        финале (execute_path) поднял перо +1 см и заехал домой существующей веткой
        REG_DRAW_HOME (в DRAW-режиме Mirror НЕ опрашивает REG_STOP — отдельной
        команды «домой» нет, переиспользуем финал прохода).
        """
        return self._write_map({"draw_home": 1 if home else 0})

    def draw_flush(self) -> bool:
        """Сбросить из памяти робота задание рисования (маркеры/счётчики).

        Запрос владельца на Стоп: «выбросить из памяти точки». Буфер точек 0x1420
        перезаписывается на каждом проходе, поэтому «сброс» = обнулить управляющие
        регистры, чтобы не осталось взведённого draw_flag/незакрытого count и
        следующий старт начинался с чистого листа.

        ВАЖНО: draw_abort НЕ трогаем — его взвёл вызывающий (Стоп) и его обязана
        потребить и САМА обнулить прошивка/sim (финал прохода или idle-ветка DRAW).
        Обнуление здесь могло бы отменить ещё не обработанный аборт.
        """
        return self._write_map({"draw_flag": 0, "draw_count": 0, "draw_prog": 0, "draw_done_n": 0})

    def draw_circle(self, cx: float, cy: float, r: float, timeout: float = DRAW_TIMEOUT_S) -> bool:
        """Круг родным MCircle робота: центр + радиус, одной командой (гладко)."""
        ok = self._write_map(
            {
                "circ_cx": cx,
                "circ_cy": cy,
                "circ_r": r,
                "draw_type": DRAW_TYPE_CIRCLE,
                "draw_home": 1,  # круг = единственный проход → подъём + домой в конце
                "draw_flag": 1,  # маркер — последним
            }
        )
        if not ok:
            return False
        return self._wait_draw_done(timeout)

    def draw(
        self,
        points: list[DrawPoint] | list[tuple],
        timeout: float = DRAW_TIMEOUT_S,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> bool:
        """Полилиния: весь путь рисуется ПОЛНОСТЬЮ, проходами ≤ PTS_MAX точек.

        ``should_abort``: опц. колбэк, проверяется ПЕРЕД каждым проходом. Вернул True —
        рисование прекращается, оставшиеся проходы НЕ отправляются. Нужно для «Стоп»:
        без этого прерывается лишь текущий проход (REG_DRAW_ABORT в прошивке), а
        остальные всё равно уходят роботу.

        Сколько бы точек ни было (хоть 400) — рисунок отрисовывается весь. Два уровня
        чанкования (оба обязательны, робот не тянет большие блоки):
        - проход ≤ PTS_MAX точек = буфер робота на один проход. split_draw_passes
          режет ТОЛЬКО на границах штрихов (перо вверх) — проход не обрывается посреди
          штриха, иначе после заезда домой робот чертил бы линию «от дома» и линии
          терялись бы. Между проходами — ожидание завершения (_run_batch);
        - WRITE_CHUNK=30 регистров (10 точек) на один write при заливке буфера прохода.
        """
        pts = [p if isinstance(p, DrawPoint) else DrawPoint(*p) for p in points]
        if not pts:
            raise RobotJobError("Пустой путь рисования")
        # Размер прохода — конфигурируемый (мельче = больше пакетов, каждый с обратной
        # связью). Зажимаем в [3, PTS_MAX]: PTS_MAX — потолок буфера прошивки; нижний
        # предел 3 нужен для overlap-возобновления длинного штриха (подвод + сегмент).
        limit = max(3, min(int(self._cfg.draw_pass_size), PTS_MAX))
        passes = split_draw_passes(pts, limit)
        total = len(pts)
        for n, batch in enumerate(passes, start=1):
            if should_abort is not None and should_abort():
                self._emit_progress({"stage": "aborted", "pass": n, "passes": len(passes)})
                return False
            self._emit_progress({"stage": "batch", "pass": n, "passes": len(passes), "size": len(batch)})
            # home=True только на ПОСЛЕДНЕМ проходе: робот поднимается +1 см и едет домой в
            # конце рисунка; между проходами он ждёт на месте (перо вверх).
            if not self._run_batch(batch, timeout, home=(n == len(passes))):
                return False
        self._emit_progress({"stage": "done", "passes": len(passes), "total": total})
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

    def _run_batch(self, batch: list[DrawPoint], timeout: float, *, home: bool = False) -> bool:
        """Один проход: залить буфер, запустить, дождаться завершения, СВЕРИТЬ факт.

        ``home``: True на последнем проходе рисунка — прошивка после прохода поднимает перо
        +1 см и едет домой. Между проходами (home=False) робот ждёт на месте (перо вверх).

        Read-back ACK (draw_verify): прошивка пишет в ``draw_done_n`` реально выполненное
        число точек (пост-усечённое — execute_path молча уменьшает count при коротком
        чтении буфера). Если оно != размеру пачки → проход перезаливаем и повторяем до
        ``draw_retry`` раз; устойчивое расхождение → False (рисунок прерывается, точки
        НЕ теряются молча).

        ВНИМАНИЕ (честно): расхождение бывает лишь при сбое шины (короткое чтение). Повтор
        перезаливает ВСЮ пачку и рисует её ЗАНОВО, т.е. уже выполненный префикс будет
        ОБВЕДЁН ПОВТОРНО (overdraw) — лучше обведённая линия, чем потерянный сегмент. Это
        безопасно по буферу (_wait_draw_done гарантирует завершение предыдущей попытки) и
        бывает только на деградировавшем транспорте; на нормальном пути verify==count и
        повтора нет. Факт повтора виден в on_progress (stage=verify_mismatch).
        """
        attempts = (1 + max(0, int(self._cfg.draw_retry))) if self._cfg.draw_verify else 1
        for attempt in range(1, attempts + 1):
            if not self._upload_points(batch):
                return False
            ok = self._write_map(
                {
                    "draw_type": DRAW_TYPE_POLYLINE,
                    "draw_count": len(batch),
                    "draw_home": 1 if home else 0,
                    "draw_flag": 1,  # маркер — последним
                }
            )
            if not ok:
                return False
            if not self._wait_draw_done(timeout):
                return False
            if not self._cfg.draw_verify:
                return True
            executed = int(self._map.read(self._device, "draw_done_n"))
            if executed == len(batch):
                return True
            self._emit_progress(
                {"stage": "verify_mismatch", "expected": len(batch), "executed": executed, "attempt": attempt}
            )
        self._emit_progress({"stage": "verify_failed", "expected": len(batch)})
        return False

    def _wait_draw_done(self, timeout: float) -> bool:
        """Дождаться завершения прохода по handshake прошивки (flag → busy↑ → busy↓).

        Контракт cvt_universal_full.lua (Motion/execute_path):
          1. Motion читает REG_DRAW_FLAG==1 и СРАЗУ сбрасывает в 0 — приём задания;
          2. execute_path готовит пул distinct-точек, затем REG_DRAW_BUSY=1 — старт;
          3. рисует проход, поднимает перо, едет домой и лишь ПОСЛЕ — REG_DRAW_BUSY=0.
        Поэтому надёжно: ждём сброс flag (приём) → подъём busy (старт, подготовка пула
        может занять >1с) → падение busy (проход + перо вверх + домой завершены).

        КРИТИЧНО: следующий проход нельзя заливать в буфер REG_PTS_BASE, пока этот не
        завершён, иначе перезапись буфера на лету — робот рисует мешанину старого и
        нового пути. Возврат True ТОЛЬКО после полного завершения прохода это гарантирует.
        Прежняя версия ждала подъём busy лишь 1с и при медленном старте ОШИБОЧНО
        считала проход завершённым (терялись проходы + портился буфер).
        """
        # 1) Приём задания: прошивка сбросила draw_flag в 0.
        if not self._poll_until(self.draw_accepted, _ACCEPT_S, _POLL_FAST_S):
            self._emit_progress({"stage": "not_accepted"})
            return False
        # 2) Старт прохода: busy поднялся (после подготовки пула точек).
        if not self._poll_until(self.draw_busy, _BUSY_RISE_S, _POLL_FAST_S):
            self._emit_progress({"stage": "no_busy_rise"})
            return False
        # 3) Завершение: busy упал (рисование + перо вверх + заезд домой завершены).
        if not self._poll_until(lambda: self.draw_busy() is False, timeout, _POLL_SLOW_S):
            self._emit_progress({"stage": "timeout", "timeout_s": timeout})
            return False
        return True

    def _poll_until(self, condition: Callable[[], bool], timeout: float, step: float) -> bool:
        """Поллить ``condition`` до ``timeout`` с шагом ``step`` (по инъектируемым часам)."""
        t0 = self._clock()
        while self._clock() - t0 < timeout:
            if condition():
                return True
            self._sleep(step)
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
