"""``robot_driver_v2.texts`` (T5.3f f2).

Purpose:
    Постоянные драйвера робота Delta v2: сроки, тексты отказов, ответы «занято», счётчик номеров потоков.

Stability: lite
"""

from __future__ import annotations

import itertools
import threading

from Services.robot_comm.core.protocol_v2 import CONSTANTS, REG, STOP_LEVEL

__all__ = [
    "TEXT_BAD_DO",
    "TEXT_BAD_JOB_ARGS",
    "TEXT_BAD_RANGE",
    "TEXT_BAD_RETURN_ARGS",
    "TEXT_BAD_STOP_LEVEL",
    "TEXT_EPOCH_NOT_WRITTEN",
    "TEXT_LEASE_LOST",
    "TEXT_NO_ECHO_WINDOW",
    "TEXT_NO_PROGRAM",
    "TEXT_NO_SPAWN",
    "TEXT_NO_STORE",
    "TEXT_PARAM_DIVERGED",
    "TEXT_PARAM_NO_REPLY",
    "TEXT_SCOPE_CLOSED",
    "TEXT_SPAWN_FAILED",
    "TEXT_SPAWN_NAME_BUSY",
    "TEXT_STOPPING",
    "TEXT_STOP_UNCONFIRMED",
    "TEXT_SYNCING",
    "TEXT_THREAD_SURVIVED",
    "TEXT_UNKNOWN_PARAM",
    "TEXT_WDG_INTERVAL",
    "_BUSY_JOB",
    "_BUSY_JOG",
    "_BUSY_PROGRAM",
    "_BUSY_REPLIES",
    "_CLIENT_KEYS",
    "_DO_CHANNELS",
    "_HOLD_WINDOW_S",
    "_HUB_POLL_DEFAULT_S",
    "_JOB_QUEUE_MAXLEN",
    "_LEASE_JOIN_S",
    "_LEASE_PERIOD_FALLBACK_S",
    "_NOT_CONNECTED",
    "_ON_CONNECT_DEADLINE_S",
    "_ON_CONNECT_POLL_S",
    "_OPERATOR_ECHO_BUDGET_S",
    "_PROCESS_STOP_DEFAULT_S",
    "_PROGRAM_JOIN_S",
    "_RECONNECT_THROTTLE_SEC",
    "_STOP_NAMES",
    "_THREAD_SEQ",
    "_THREAD_SEQ_LOCK",
    "_TLM_BASE",
    "_TLM_COUNT",
    "_WIRE_MAX",
    "_WIRE_SCALE",
    "_next_thread_k",
]


# Минимальный интервал между попытками переподключения, с (как v1, robot_driver.py:29)
_RECONNECT_THROTTLE_SEC = 2.0
# Окно удержания jog: подтверждений GUI нет дольше — драйвер сам шлёт стоп (Л3, Д3)
_HOLD_WINDOW_S = 0.2
# Дедлайн подтверждения действий при подключении по телеметрии (SERVO / DO_SET — instant, без wait_done)
_ON_CONNECT_DEADLINE_S = 2.0
_ON_CONNECT_POLL_S = 0.02
# Дедлайн join потока поводка в jog_release и disconnect
_LEASE_JOIN_S = 1.0
# Дедлайн join исполнителя программ в disconnect
_PROGRAM_JOIN_S = 5.0
# Период поводка, если клиент его ещё не знает (до probe), с: треть умолчания P_JOG_LEASE_MS
_LEASE_PERIOD_FALLBACK_S = 0.1
# Интервал тика хаба по умолчанию (Plugins/hub/device_hub/plugin.py:346)
_HUB_POLL_DEFAULT_S = 0.5

# Поля ClientV2Config, которые берутся из entry.params как есть (DESIGN п.2)
_CLIENT_KEYS = (
    "round_step",
    "res_timeout_s",
    "done_timeout_s",
    "longest_gap_s",
    "stop_echo_timeout_s",
    "soft_echo_timeout_s",
)
_DO_CHANNELS = range(1, 17)

_TLM_BASE = REG["TLM_PROTO_VER"]
_TLM_COUNT = 32  # TLM_PROTO_VER .. TLM_CFG_PENDING + 1 (0x1040..0x105F)
_WIRE_SCALE = CONSTANTS["WIRE_SCALE"]

TEXT_LEASE_LOST = "поводок jog прерван: нет связи с роботом"
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_SCOPE_CLOSED = "область потоков хаба закрыта"
TEXT_SPAWN_NAME_BUSY = "имя потока драйвера занято"
TEXT_SPAWN_FAILED = "поток драйвера не запущен"
TEXT_THREAD_SURVIVED = "поток драйвера не вышел за срок"
TEXT_WDG_INTERVAL = "интервал тика больше четверти таймаута сторожа"
TEXT_NO_SPAWN = "RobotDriverV2 без spawn не запускает потоки"
TEXT_STOP_UNCONFIRMED = "стоп не подтверждён роботом"
TEXT_NO_ECHO_WINDOW = "эхо не читалось (нет окна)"
TEXT_BAD_STOP_LEVEL = "неверный уровень стопа"
# Операции T5.3d d1: постоянные тексты отказов (без входных значений)
TEXT_NO_STORE = "хранилище данных робота не задано"
TEXT_BAD_DO = "канал DO вне 1..16"
TEXT_BAD_RANGE = "значение вне диапазона"
TEXT_UNKNOWN_PARAM = "неизвестный параметр"
TEXT_SYNCING = "идёт синхронизация параметров"
TEXT_NO_PROGRAM = "программа не найдена"
TEXT_EPOCH_NOT_WRITTEN = "параметр не применён: метка не записана"
TEXT_PARAM_DIVERGED = "параметр робота расходится с файлом"
# Запись значения параметра не получила ответа (не NAK): исход у робота неизвестен, значение возвращается из файла
TEXT_PARAM_NO_REPLY = "параметр не применён: робот не ответил"
# Ожидание эха стопа оператора: от входа в обработчик до t0 + 0,8 с (0,2 с запаса из бюджета О9 в 1,0 с)
_OPERATOR_ECHO_BUDGET_S = 0.8
_STOP_NAMES = {level: name for name, level in STOP_LEVEL.items()}
# Срок стопа процесса, если request_stop() позван без срока (отдельный драйвер, не плагин), с
_PROCESS_STOP_DEFAULT_S = 2.5
_BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}
_BUSY_JOG = {"status": "error", "message": "робот в режиме jog"}
_BUSY_JOB = {"status": "error", "message": "робот выполняет задание"}
_NOT_CONNECTED = {"status": "error", "message": "нет связи с роботом"}
# Ответы «захват занят» исполнителя: возврат из очереди при таком ответе идёт обратно в её начало (DESIGN п.6)
_BUSY_REPLIES = (_BUSY_PROGRAM, _BUSY_JOG, _BUSY_JOB)
# Тексты отказа постановки — постоянные, без входного значения (R8)
TEXT_BAD_JOB_ARGS = "неверные аргументы задания"
TEXT_BAD_RETURN_ARGS = "неверные аргументы возврата"
# Глубина очередей заданий и возвратов по умолчанию (паритет v1)
_JOB_QUEUE_MAXLEN = 256
# Предел координаты на проводе: |v| * WIRE_SCALE <= W_MAX (R8)
_WIRE_MAX = CONSTANTS["W_MAX"]

# Один счётчик номеров потоков на модуль (поводок и исполнитель, все экземпляры): имя потока уникально в области
_THREAD_SEQ = itertools.count(1)
_THREAD_SEQ_LOCK = threading.Lock()


def _next_thread_k() -> int:
    """Следующий номер потока; замок — чтобы гарантия не зависела от атомарности ``next()`` в сборке CPython."""
    with _THREAD_SEQ_LOCK:
        return next(_THREAD_SEQ)
