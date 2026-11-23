"""VfdClient — управление ПЧ INVT GD20 поверх RegisterTransport.

Транспорт-агностик: клиент не знает, КАК доставляются регистры —
- сегодня: мост через робота (`RobotClient` из runtime robot_comm);
- завтра: прямой RS-485 (`ModbusDevice(transport=rtu)`) — другой transport и
  карта DIRECT_MAP, без правки этого клиента.

Семантика моста (порт vfd_* из ``robot/universal3/pc_full.py``):
- команды — атомарные транзакции в mailbox: данные -> VFD_FLAG ПОСЛЕДНИМ;
- Lua робота ретранслирует на RS-485 и зеркалит статус в 0x1210+;
- **зеркало обновляется ТОЛЬКО при обработке VFD_FLAG** (ограничение текущего
  Lua, ревью п.1) — поэтому опрос статуса идёт через ``poll()``: пульс флага
  без смены команды (Lua кэширует last_cmd/last_freq — лишних записей на
  RS-485 не будет) + контроль роста heartbeat моста.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from Services.modbus.core.register_map import RegisterMap

from Services.vfd_comm.core.config import VfdConfig
from Services.vfd_comm.core.datatypes import VFDStatus
from Services.vfd_comm.core.registers import BRIDGE_MAP
from Services.vfd_comm.errors import VfdBridgeStaleError, VfdFrequencyError

if TYPE_CHECKING:
    from Services.modbus.interfaces import RegisterTransport


class VfdClient:
    """Клиент ПЧ: run/set_freq/stop/reset_fault + poll-опрос зеркала.

    Args:
        transport: Любой RegisterTransport (RobotClient — мост, ModbusDevice — прямое).
        config:    Доменные лимиты ПЧ.
        register_map: Карта (дефолт — мост BRIDGE_MAP; для прямого RTU — DIRECT_MAP
            с другим клиентским кодом команд, см. registers.py).
    """

    def __init__(
        self,
        transport: "RegisterTransport",
        config: VfdConfig | None = None,
        *,
        register_map: RegisterMap = BRIDGE_MAP,
        last_freq: float | None = None,
    ) -> None:
        self._t = transport
        self._cfg = config or VfdConfig()
        self._map = register_map
        self._last_heartbeat: int | None = None
        self._stale_polls = 0
        # Последняя успешно записанная частота > 0: пуск без частоты стартует на ней, а не на default_freq_hz
        # (иначе «Лента пуск» затирает скорость, заданную оператором). ``last_freq`` — начальное значение
        # (драйвер переносит память через пересоздание клиента при реконнекте).
        # Ноль и меньше в начальную память не берём: как и в ``run()``/``set_freq()``, память — только частота > 0.
        self._last_freq: float | None = last_freq if last_freq is not None and last_freq > 0 else None
        # Порядок захвата: _freq_lock -> замок транспорта (обратного порядка нет, _write замка клиента не берёт).
        self._freq_lock = threading.Lock()

    @property
    def config(self) -> VfdConfig:
        """Текущий конфиг."""
        return self._cfg

    @property
    def last_freq(self) -> float | None:
        """Последняя успешно записанная частота > 0 (None — ещё не задавали)."""
        return self._last_freq

    @property
    def is_connected(self) -> bool:
        """Жив ли транспорт (соединение с роботом/устройством)."""
        return self._t.is_connected

    # ------------------------------------------------------------------ #
    # Команды (атомарно, VFD_FLAG последним)
    # ------------------------------------------------------------------ #

    def run(self, freq_hz: float | None = None, reverse: bool = False) -> bool:
        """Запустить: частота + направление + RUN + маркер одной транзакцией.

        Без ``freq_hz`` — последняя заданная частота (``run``/``set_freq``), при её отсутствии — ``default_freq_hz``.
        """
        # Запись на провод и запоминание — под одним замком: память совпадает с последней командой на проводе.
        with self._freq_lock:
            fallback = self._last_freq if self._last_freq is not None else self._cfg.default_freq_hz
            freq = self._validate_freq(freq_hz if freq_hz is not None else fallback)
            ok = self._write(
                {
                    "cmd_freq": freq,
                    "cmd_dir": 1 if reverse else 0,
                    "cmd_run": 1,
                    "flag": 1,  # маркер — последним
                }
            )
            if ok and freq > 0:  # ноль на провод уходит, но «последней заданной» не становится
                self._last_freq = freq
            return ok

    def set_freq(self, freq_hz: float) -> bool:
        """Сменить частоту на ходу (запоминается для следующего ``run()`` без частоты)."""
        freq = self._validate_freq(freq_hz)
        with self._freq_lock:
            ok = self._write({"cmd_freq": freq, "flag": 1})
            if ok and freq > 0:
                self._last_freq = freq
            return ok

    def stop(self) -> bool:
        """Остановить вращение (память последней частоты сохраняется: пуск после стопа — на той же скорости)."""
        return self._write({"cmd_run": 0, "flag": 1})

    def reset_fault(self) -> bool:
        """Сбросить аварию (RUN снимается, RESET-импульс).

        После успешной записи память последней частоты сбрасывается: после аварии пуск без частоты идёт на
        ``default_freq_hz``, а не на чужой «последней». Неудачная запись (False/исключение) память не трогает.
        """
        with self._freq_lock:
            ok = self._write({"cmd_run": 0, "cmd_reset": 1, "flag": 1})
            if ok:
                self._last_freq = None
            return ok

    # ------------------------------------------------------------------ #
    # Статус
    # ------------------------------------------------------------------ #

    def read_status(self) -> VFDStatus:
        """Прочитать зеркало статуса КАК ЕСТЬ (без пульса — может быть заморожено).

        Для периодического опроса используйте ``poll()``.
        """
        data = dict(self._map.read(self._t, "status"))
        return VFDStatus(
            running=data.pop("running") == 1,
            **{k: (int(v) if k not in ("out_freq_hz", "current_a", "dcbus_v") else float(v)) for k, v in data.items()},
        )

    def poll(self) -> VFDStatus:
        """Опрос для мостового подключения: пульс VFD_FLAG + чтение зеркала.

        Пульс заставляет Lua выполнить vfd_poll_publish (обновить зеркало и
        heartbeat); смены команды не происходит — Lua кэширует last_cmd/
        last_freq, на RS-485 уходят только чтения статуса.
        """
        self._write({"flag": 1})
        status = self.read_status()
        self._track_heartbeat(status)
        return status

    def ensure_alive(self) -> None:
        """Проверить живость моста по динамике heartbeat (звать после poll()).

        Raises:
            VfdBridgeStaleError: heartbeat не растёт stale_polls_limit опросов
                подряд — Lua-мост или RS-485 не отвечают.
        """
        if self._stale_polls >= self._cfg.stale_polls_limit:
            raise VfdBridgeStaleError(
                f"Зеркало ПЧ заморожено {self._stale_polls} опросов подряд "
                f"(heartbeat={self._last_heartbeat}): робот/RS-485 не отвечает"
            )

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _write(self, values: dict) -> bool:
        return self._t.transaction(self._map.write_ops(values))

    def _validate_freq(self, freq_hz: float) -> float:
        if not self._cfg.freq_min_hz <= freq_hz <= self._cfg.freq_max_hz:
            raise VfdFrequencyError(
                f"Частота {freq_hz} Гц вне диапазона {self._cfg.freq_min_hz}..{self._cfg.freq_max_hz} Гц"
            )
        return freq_hz

    def _track_heartbeat(self, status: VFDStatus) -> None:
        if status.heartbeat is None:
            return
        if self._last_heartbeat is not None and status.heartbeat == self._last_heartbeat:
            self._stale_polls += 1
        else:
            self._stale_polls = 0
        self._last_heartbeat = status.heartbeat
