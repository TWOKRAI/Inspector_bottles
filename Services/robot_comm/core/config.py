"""Конфиг сервиса robot_comm.

SRP: только транспорт + доменные лимиты робота. Калибровочные параметры
(belt_vector, factor_mm) живут в калибровке, НЕ здесь — клиент робота не
должен знать про конвейер и камеры.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from Services.modbus import ModbusConfig, TransportType

from Services.robot_comm.core.registers import PTS_MAX, ROBOT_UNIT_ID, XY_LIMIT_MM


@dataclass(slots=True)
class RobotConfig:
    """Параметры подключения и лимиты робота Delta.

    Attributes:
        host:        IP робота (Modbus-TCP server на роботе).
        port:        TCP-порт (стандартный 502).
        unit_id:     Modbus device_id робота (u3: 2).
        timeout_sec: Таймаут операции. Держим МАЛЫМ (~0.5-1 с): transaction
                     держит Lock устройства на время I/O — при обрыве большой
                     таймаут заморозит feeder/телеметрию/GUI.
        retries:     Повторы на операцию. 1 — retry внутри серии запрещён
                     семантикой transaction (атомарность), повторяет владелец.
        word_order:  Порядок слов DW (энкодер/E_capture). Подбор на железе —
                     CLI-команда ``cal`` (первое, что проверяют при «мусорном»
                     энкодере). НЕ хардкодить.
        xy_limit_mm: Предел |X|,|Y| для send_job (s16 при scale=10).
        lift_mm:     Подъём пера над Z рисования (высота переезда).
        draw_pass_size: Точек в одном проходе рисования (батч). Меньше = больше
                     пакетов, каждый верифицируется обратной связью → меньше риск
                     потери. Зажимается в [2, PTS_MAX]; PTS_MAX — потолок буфера
                     прошивки (НЕ поднимать). Дефолт PTS_MAX = старое поведение;
                     рецепт может задать мельче (devices[].params.draw_pass_size).
        draw_verify: После каждого прохода читать draw_done_n (реально выполнено
                     точек) и сверять с размером пачки. Расхождение = тихое усечение
                     в прошивке → повтор/аборт, точки не теряются молча.
        draw_retry:  Сколько раз повторить проход при расхождении verify до аборта.
    """

    host: str = "192.168.1.7"
    port: int = 502
    unit_id: int = ROBOT_UNIT_ID
    timeout_sec: float = 1.0
    retries: int = 1
    word_order: str = "little"
    xy_limit_mm: float = XY_LIMIT_MM
    lift_mm: float = 10.0
    draw_pass_size: int = PTS_MAX
    draw_verify: bool = True
    draw_retry: int = 1

    # ------------------------------------------------------------------ #
    # Dict at Boundary
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RobotConfig":
        """Создать из dict, игнорируя посторонние ключи."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_modbus_config(self) -> ModbusConfig:
        """Транспортный конфиг для ModbusDevice (всегда TCP — робот так подключён)."""
        return ModbusConfig(
            transport=TransportType.TCP,
            host=self.host,
            port=self.port,
            unit_id=self.unit_id,
            timeout_sec=self.timeout_sec,
            retries=self.retries,
            word_order=self.word_order,
        )

    def describe(self) -> str:
        """Человекочитаемый адрес робота (для логов/UI)."""
        return f"robot@tcp://{self.host}:{self.port}#unit{self.unit_id}"
