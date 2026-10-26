"""SPI хаба: контракт драйвера устройства и описания операций (``OpSpec``), из которых строятся команды плагина.

Purpose:
    Явный контракт драйвера вместо ``getattr`` / ``hasattr``: ``DeviceDriver`` и ``StopAwareDriver`` (``Protocol``,
    статический контракт; во время работы ``isinstance`` по ним не вызывается — умолчания даёт ``BaseDeviceDriver``,
    стоп — флаг ``stop_aware``). ``OpSpec`` описывает одну операцию драйвера, ``OpSource`` — набор операций одного
    префикса команд; ``command_table`` сводит источники в таблицу «имя команды -> (источник, операция)».
    Каталоги: ``ROBOT_V2_OPS`` (17), ``ROBOT_V1_OPS`` (27), ``ROBOT_DATA_OPS`` (10 офлайн-операций), ``VFD_OPS`` (5).
    Драйвер объявляет свои операции ссылкой ``OP_SPECS = <каталог>``; команды плагина строятся из ``OP_SPECS`` классов
    драйверов таблицы видов (``Services/device_hub/kinds.py``: ``command_sources``, ``DEFAULT_SOURCES``), не из
    кортежей этого модуля напрямую. Флаги ``immediate`` — по коду драйверов
    (``plans/robot-protocol-v2/tasks/SPI.framework.md``, таблица с file:line).
    Импорт — только stdlib, драйверы не импортируются (их модули импортируют этот): модуль импортирует класс плагина,
    а класс плагина — GUI.
    Контракт-тесты — ``Services/device_hub/tests/test_spi_contract.py`` (отступление от ``module-contract``: каталога
    ``tests/contract/`` в репозитории нет).

Public API:
    ``OpSpec``, ``OpSource``, ``command_table``, ``DeviceDriver``, ``StopAwareDriver``, ``ROBOT_V2_OPS``,
    ``ROBOT_V1_OPS``, ``ROBOT_DATA_OPS``, ``VFD_OPS``.

Stability: lite
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol

__all__ = [
    "ROBOT_DATA_OPS",
    "ROBOT_V1_OPS",
    "ROBOT_V2_OPS",
    "VFD_OPS",
    "DeviceDriver",
    "OpSource",
    "OpSpec",
    "StopAwareDriver",
    "command_table",
]


@dataclass(frozen=True, slots=True)
class OpSpec:
    """Описание одной операции драйвера; команда плагина — ``f"{prefix}_{name}"``.

    ``executor`` и ``immediate`` вместе — ``ValueError`` при создании: «никогда не в очередь» исключает исполнителя.
    """

    name: str  # имя операции драйвера
    description: str = ""  # текст каталога; "" — описание не пишется
    args_schema: tuple[str, ...] = ()  # ключи аргументов кроме key_from; "?" в конце — необязательный; только описание
    needs_link: bool = True  # True: manager.call (отказ «не подключено»); False: driver.call без связи
    executor: str | None = None  # имя исполнителя процесса
    immediate: bool = False  # никогда не в очередь исполнителя

    def __post_init__(self) -> None:
        if self.executor is not None and self.immediate:
            raise ValueError(f"операция {self.name!r}: executor и immediate вместе недопустимы")


@dataclass(frozen=True, slots=True)
class OpSource:
    """Набор операций одного префикса команд: вид устройства и путь исполнения (драйвер или данные)."""

    prefix: str  # "robot" | "vfd"
    kind: str  # ожидаемый entry.kind
    route: Literal["driver", "data"]
    ops: tuple[OpSpec, ...]
    key_from: str = "device_id"


def command_table(sources: Sequence[OpSource]) -> dict[str, tuple[OpSource, OpSpec]]:
    """Таблица команд: ``f"{prefix}_{name}"`` -> (источник, операция), в порядке источников и операций.

    Pre: ``sources`` — последовательность ``OpSource``.
    Post: каждое имя команды — одна строка; одноимённая операция из второго источника, равная первой по всем полям
        ``OpSpec`` и пришедшая из источника того же вида, пути и ключа, строки не добавляет (первая остаётся).
    Raises: ``ValueError`` — одно имя команды из двух мест с неравными ``OpSpec`` (``description``, ``args_schema``,
        ``needs_link``, ``executor``, ``immediate``) или с разными ``kind`` / ``route`` / ``key_from`` источника.
    """
    table: dict[str, tuple[OpSource, OpSpec]] = {}
    for source in sources:
        for spec in source.ops:
            name = f"{source.prefix}_{spec.name}"
            seen = table.get(name)
            if seen is None:
                table[name] = (source, spec)
                continue
            first_source, first_spec = seen
            if first_spec != spec:
                raise ValueError(f"команда {name!r}: два описания операции не равны: {first_spec!r} и {spec!r}")
            if (first_source.kind, first_source.route, first_source.key_from) != (
                source.kind,
                source.route,
                source.key_from,
            ):
                raise ValueError(f"команда {name!r}: источники различаются видом, путём или ключом")
    return table


class DeviceDriver(Protocol):
    """Контракт драйвера устройства хаба (статический; умолчания — ``BaseDeviceDriver``)."""

    kind: str
    entry: Any
    protocol: Any
    desired_connected: bool
    reconnect_exhausted: bool
    OP_SPECS: ClassVar[tuple[OpSpec, ...]]
    stop_aware: ClassVar[bool]  # драйвер получает стоп фазы 1 остановки (request_stop)
    transport: Any  # транспорт регистров или None
    disconnect_pending: bool  # C-29
    stop_unconfirmed: bool
    stop_unconfirmed_text: str | None
    last_io: dict | None

    @property
    def is_connected(self) -> bool: ...

    @property
    def stats(self) -> dict[str, Any]: ...

    def connect(self) -> bool: ...

    def disconnect(self) -> None: ...

    def tick(self, stop_event: Any = None) -> dict | None: ...

    def call(self, op: str, args: dict) -> dict: ...

    def reset_reconnect(self) -> None: ...

    def request_disconnect(self) -> None:
        """«Отключить» нажато; без ввода-вывода."""
        ...

    def set_degraded(self) -> bool:
        """Носитель моста отключён; True — драйвер перешёл в деградацию."""
        ...


class StopAwareDriver(DeviceDriver, Protocol):
    """Драйвер со стопом фазы 1 остановки процесса (``stop_aware`` истинно)."""

    def request_stop(self, deadline: float | None = None) -> None: ...


# --------------------------------------------------------------------------------------------------
# Каталоги операций. Описания и ``args_schema`` — тексты каталога команд (T5.3c, SPI.c2): у каждой из 55 операций.
# ``args_schema`` — ключи аргументов кроме ``device_id``; "?" в конце — необязательный (по коду драйверов).
# --------------------------------------------------------------------------------------------------

# Общие операции робота v1 и v2: объявлены один раз, входят в оба кортежа одним объектом
_ABORT = OpSpec(  # v2 ops.py:73-78 (_operator_stop); v1 robot_driver.py:603-606
    name="abort",
    description="Стоп робота: {device_id, mode: 1|2|3}.",
    args_schema=("mode?",),
    immediate=True,
)
_ENQUEUE_JOB = OpSpec(
    name="enqueue_job",
    description="Поставить CVT-задание: {device_id, x_mm, y_mm, e_capture?}.",
    args_schema=("x_mm", "y_mm", "z_mm?", "e_capture?", "place_x?", "place_y?", "place_z?", "place_rz?"),
)
_GET_TELEMETRY = OpSpec(name="get_telemetry", description="Телеметрия робота.")
_RETURN_JOB = OpSpec(
    name="return_job",
    description="Возврат буквы на ленту: {device_id, x_mm, y_mm, z_mm} (координата слота).",
    args_schema=("x_mm", "y_mm", "z_mm?"),
)
_SHARED_ROBOT_OPS: tuple[OpSpec, ...] = (_ABORT, _ENQUEUE_JOB, _GET_TELEMETRY, _RETURN_JOB)

# 17 ключей robot_driver_v2/ops.py (OPS), в том же порядке
ROBOT_V2_OPS: tuple[OpSpec, ...] = (
    OpSpec(
        name="jog_hold",
        description="Робот v2: удержание jog {device_id, dir: 1..8, spd: 1..100}",
        args_schema=("dir", "spd"),
        immediate=True,
    ),
    OpSpec(name="jog_release", description="Робот v2: отпустить jog {device_id}", immediate=True),
    _GET_TELEMETRY,
    _ENQUEUE_JOB,
    _RETURN_JOB,
    _ABORT,
    OpSpec(
        name="exchange_log_get",
        description="Журнал обмена драйвера: {device_id, since_seq?, limit?}. Работает и при разрыве связи (T5.6).",
        args_schema=("since_seq?", "limit?"),
        needs_link=False,
    ),
    OpSpec(
        name="exchange_log_set",
        description="Ручки журнала обмена: {device_id, enabled?, periodic?, clear?} (T5.6).",
        args_schema=("enabled?", "periodic?", "clear?"),
        needs_link=False,
    ),
    OpSpec(
        name="stop",
        description="Робот v2: стоп {device_id, level: SOFT|HARD|HALT}",
        args_schema=("level",),
        immediate=True,
    ),
    OpSpec(name="servo", description="Робот v2: серво {device_id, on: bool}", args_schema=("on",)),
    OpSpec(
        name="do_set",
        description="Робот v2: дискретный выход {device_id, ch: 1..16, on: bool}",
        args_schema=("ch", "on"),
    ),
    OpSpec(
        name="jog_step",
        description="Робот v2: шаг jog {device_id, dx, dy, dz?, drz?, spd: 1..100}",
        args_schema=("dx", "dy", "dz?", "drz?", "spd"),
    ),
    OpSpec(
        name="point_capture",
        description="Робот v2: запомнить текущую позу как точку {device_id, name, base_rev}",
        args_schema=("name", "base_rev"),
    ),
    OpSpec(
        name="param_set",
        description="Робот v2: записать параметр {device_id, name, value, base_rev}",
        args_schema=("name", "value", "base_rev"),
    ),
    OpSpec(name="param_apply", description="Робот v2: применить параметры класса reinit {device_id}"),
    OpSpec(
        name="program_run",
        description="Робот v2: запустить программу {device_id, name}",
        args_schema=("name",),
    ),
    OpSpec(name="program_abort", description="Робот v2: прервать программу {device_id}", immediate=True),
)

# 27 ключей RobotDriver._OPS (robot_driver.py): 16 «старых» и 11 draw_*, в том же порядке
ROBOT_V1_OPS: tuple[OpSpec, ...] = (
    OpSpec(
        name="send_test_job",
        description="Тестовое CVT-задание: {device_id, x, y}.",
        args_schema=("x", "y", "z?"),
    ),
    _ABORT,
    OpSpec(
        name="set_mode",
        description="Режим робота: {device_id, mode: cvt|draw|manual}.",
        args_schema=("mode?",),
    ),
    OpSpec(
        name="jog",
        description="Ручной ход: {device_id, dx, dy, spd?, absolute?} — смещение мм + Override %.",
        args_schema=("dx?", "dy?", "spd?", "absolute?"),
    ),
    OpSpec(
        name="jog_abort",
        description="Прервать ручной ход: {device_id}.",
        immediate=True,  # robot_driver.py:624-627
    ),
    OpSpec(
        name="set_servo",
        description="Серво: {device_id, on: bool}.",
        args_schema=("on?",),
        immediate=True,  # robot_driver.py:629-632, решение лида
    ),
    OpSpec(
        name="set_robot_config",
        description="Конфиг робота: {device_id, ...fields}.",
        args_schema=("...fields",),
    ),
    OpSpec(name="get_robot_config", description="Прочитать конфиг-блок робота."),
    _GET_TELEMETRY,
    OpSpec(name="read_echo", description="Эхо последнего задания."),
    OpSpec(
        name="set_manual_mode",
        description="Ручной режим: {device_id, on: bool}.",
        args_schema=("on?",),
    ),
    OpSpec(
        name="clear_queue",
        description="Очистить очередь заданий.",
        immediate=True,  # robot_driver.py:663-666
    ),
    _ENQUEUE_JOB,
    _RETURN_JOB,
    OpSpec(
        name="set_encoder_offset",
        description="Подстройка компенсации конвейера: {device_id, lead_mm} (мм вдоль ленты, знаковое).",
        args_schema=("lead_mm?",),
    ),
    OpSpec(
        name="toolchange",
        description="Смена инструмента: {device_id, target: 0|1|2, timeout?}.",
        args_schema=("target?", "timeout?"),
    ),
    OpSpec(
        name="draw_polyline",
        description="Нарисовать полилинию: {device_id, points, ...}.",
        args_schema=("points", "z?"),
    ),
    OpSpec(
        name="draw_circle",
        description="Нарисовать окружность: {device_id, cx, cy, r}.",
        args_schema=("cx", "cy", "r", "z?"),
    ),
    OpSpec(
        name="draw_square",
        description="Нарисовать квадрат по двум углам: {device_id, x1, y1, x2, y2, z?}.",
        args_schema=("x1", "y1", "x2", "y2", "z?"),
    ),
    OpSpec(
        name="draw_set_pen",
        description="Установить перо: {device_id, down?, up?} (мм, можно одно из двух).",
        args_schema=("down?", "up?"),
    ),
    OpSpec(
        name="draw_set_speed",
        description="Установить скорость рисования (перо по бумаге): {device_id, pct}.",
        args_schema=("pct",),
    ),
    OpSpec(
        name="draw_set_travel",
        description="Установить скорость переезда (перо вверх): {device_id, pct}.",
        args_schema=("pct",),
    ),
    OpSpec(
        name="draw_set_accel",
        description="Установить ускорение рисования: {device_id, accel} (мм/с²).",
        args_schema=("accel",),
    ),
    OpSpec(
        name="draw_set_pass_size",
        description="Установить размер пачки рисования: {device_id, n} (точек на проход).",
        args_schema=("n",),
    ),
    OpSpec(
        name="draw_set_overlap",
        description="Установить overlap: {device_id, mm}.",
        args_schema=("mm",),
    ),
    OpSpec(
        name="draw_abort",
        description="Прервать рисование: {device_id}.",
        immediate=True,  # robot_driver.py:804-839
    ),
    OpSpec(name="draw_progress", description="Прогресс рисования: {device_id}."),
)

# 10 офлайн-операций данных робота v2 (RobotDataStore): связь не нужна; файловый ввод-вывод — на исполнителе
# процесса device_io (SPI.d2), ключ порядка — device_id
ROBOT_DATA_OPS: tuple[OpSpec, ...] = (
    OpSpec(
        name="param_get_all",
        description="Робот v2: все параметры из файла {device_id} -> params{raw, value}, epoch, rev",
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="point_list",
        description="Робот v2: список точек {device_id} -> points, rev",
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="point_save",
        description="Робот v2: сохранить точку {device_id, point{name, x, y, z, rz, hand, frame?}, base_rev}",
        args_schema=("point", "base_rev"),
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="point_delete",
        description="Робот v2: удалить точку {device_id, name, base_rev}",
        args_schema=("name", "base_rev"),
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="frame_list",
        description="Робот v2: список систем координат {device_id} -> frames, rev",
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="frame_teach",
        description="Робот v2: обучить СК по трём точкам {device_id, name, origin, on_x, in_plane, base_rev}",
        args_schema=("name", "origin", "on_x", "in_plane", "base_rev"),
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="program_list",
        description="Робот v2: имена программ {device_id} -> programs",
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="program_get",
        description="Робот v2: прочитать программу {device_id, name} -> program, rev",
        args_schema=("name",),
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="program_save",
        description="Робот v2: сохранить программу {device_id, program{name, steps}, base_rev}",
        args_schema=("program", "base_rev"),
        needs_link=False,
        executor="device_io",
    ),
    OpSpec(
        name="program_delete",
        description="Робот v2: удалить программу {device_id, name, base_rev}",
        args_schema=("name", "base_rev"),
        needs_link=False,
        executor="device_io",
    ),
)

# 5 ключей VfdDriver._OPS (vfd_driver.py), в том же порядке
VFD_OPS: tuple[OpSpec, ...] = (
    OpSpec(
        name="run", description="Пуск ПЧ: {device_id, direction?, freq_hz?}.", args_schema=("direction?", "freq_hz?")
    ),
    OpSpec(name="set_freq", description="Установить частоту: {device_id, freq_hz}.", args_schema=("freq_hz",)),
    OpSpec(name="stop", description="Стоп ПЧ: {device_id}.", immediate=True),  # vfd_driver.py:226-229
    OpSpec(name="reset_fault", description="Сброс аварии ПЧ: {device_id}."),
    OpSpec(name="get_status", description="Статус ПЧ: {device_id}."),
)
