"""Ошибки сервиса robot_comm.

Транспортные ошибки (обрыв, таймаут, exception-ответ) приходят из
``Services.modbus`` как ``ModbusDriverError`` и НЕ оборачиваются — единая
иерархия транспорта на все сервисы устройств. Здесь — только доменные ошибки
уровня робота.
"""

from __future__ import annotations


class RobotCommError(Exception):
    """Базовая доменная ошибка robot_comm."""


class RobotNotConnectedError(RobotCommError):
    """Клиент робота не подключён.

    Возникает, когда операция требует подключённого RobotClient, но процесс
    devices ещё не установил соединение (device_connect не вызван или failed).
    """


class RobotJobError(RobotCommError):
    """Ошибка постановки/исполнения CVT-задания (координата вне лимита и т.п.)."""


# --- протокол v2 (RobotClientV2). Тексты — без входных значений: значения лежат в полях. ---


class WrongFirmware(RobotCommError):
    """В 0x1040 нет протокола v2 (пустое пространство, прошивка v1 или иная версия).

    Поле ``proto_ver`` — прочитанное ``TLM_PROTO_VER`` (0, если регистр пуст).
    """

    def __init__(self, proto_ver: int) -> None:
        super().__init__("Прошивка робота не поддерживает протокол v2")
        self.proto_ver = proto_ver


class RobotNak(RobotCommError):
    """Робот отклонил команду mailbox (``RES_STATUS`` = NAK).

    ``errno`` — код ``ERR``; ``reason`` — код ``REASON`` (E_RANGE / E_SC_RECORD) или None;
    ``text`` — текст для оператора; ``index`` — индекс точки сценария (E_SC_RECORD) или None;
    ``rvals`` — первые ``RES_RVALC`` значений ответа.
    """

    def __init__(self, errno: int, reason: int | None, text: str, index: int | None, rvals: tuple[int, ...]) -> None:
        super().__init__(text)
        self.errno = errno
        self.reason = reason
        self.text = text
        self.index = index
        self.rvals = rvals


class RobotCommandError(RobotCommError):
    """Принятая роботом команда оборвана ошибкой (асинхронное событие ``ERR_*``).

    ``errno`` — None, когда событие перекрыто другим и код не известен.
    """

    def __init__(self, seq: int, errno: int | None, text: str) -> None:
        super().__init__(text)
        self.seq = seq
        self.errno = errno
        self.text = text


class RobotAborted(RobotCommandError):
    """Команда прервана стопом (``E_ABORTED``) или принята роботом уже после стопа (О5)."""


class RobotTimeout(RobotCommError):
    """Робот не ответил за таймаут. ``stage`` ∈ {"response", "done", "stop_echo"}."""

    def __init__(self, stage: str, seq: int | None = None) -> None:
        super().__init__(f"Робот не ответил вовремя (этап {stage})")
        self.stage = stage
        self.seq = seq


class RobotSyncError(RobotCommError):
    """Зеркало параметров ``PMIR`` после записи не совпало с ожидаемым значением."""

    def __init__(self, param_id: int, expected: int, actual: int) -> None:
        super().__init__("Зеркало параметров робота не совпало с записанным")
        self.param_id = param_id
        self.expected = expected
        self.actual = actual


# --- хранилище данных робота (RobotDataStore, T5.2). Тексты — без входных значений: значения лежат в полях. ---


class RobotStoreError(RobotCommError):
    """Базовая ошибка хранилища данных робота."""


class RevisionConflict(RobotStoreError):
    """Файл на диске изменён с момента чтения: ``base_rev`` не равна текущей ревизии.

    ``current_rev`` — ревизия байтов на диске сейчас (None, если файла нет).
    """

    def __init__(self, current_rev: str | None) -> None:
        super().__init__("Данные робота изменены с момента чтения")
        self.current_rev = current_rev


class InvalidStoreKey(RobotStoreError, ValueError):
    """Недопустимый ключ хранилища: ``device_id``, имя программы или имя документа.

    ``key`` — отвергнутое значение (любого типа).
    """

    def __init__(self, key: object) -> None:
        super().__init__("Недопустимое имя данных робота")
        self.key = key


class StoreDocumentInvalid(RobotStoreError):
    """Файл данных не разбирается как YAML-словарь (или тело записи не словарь/не сериализуется).

    ``rev`` — ревизия байтов повреждённого файла (по ней можно сознательно перезаписать);
    None — когда отвергнуто тело записи и файл не читался.
    """

    def __init__(self, rev: str | None) -> None:
        super().__init__("Файл данных робота не YAML-словарь")
        self.rev = rev


class RobotDataInvalid(RobotStoreError):
    """Содержимое документа робота не прошло проверку формата (``robot_data``, T5.3b).

    ``rev`` — ревизия байтов файла, который не прошёл проверку (по ней можно сознательно перезаписать);
    None — когда отвергнут вход вызывающего (``overrides``, тело на запись) и файл не читался.
    Текст постоянный, без входных значений.
    """

    def __init__(self, rev: str | None) -> None:
        super().__init__("Данные робота не прошли проверку")
        self.rev = rev


class RobotWatchdogDisabled(RobotDataInvalid):
    """Параметр ``P_WDG_TIMEOUT_MS = 0`` (сторож выключен) отвергнут как продуктовое правило (T5.3c, DESIGN 8).

    Сторож — единственная защита от недосягаемого робота: при 0 клиент не знает периода пульса. Таблица протокола
    0 допускает, поэтому правило стоит в ``robot_data`` (один раз для файла, ``overrides`` и записи). Текст постоянный,
    без входных значений; ``rev`` — как у ``RobotDataInvalid``.
    """

    def __init__(self, rev: str | None) -> None:
        RobotStoreError.__init__(self, "Сторож робота нельзя выключить: P_WDG_TIMEOUT_MS = 0")
        self.rev = rev
