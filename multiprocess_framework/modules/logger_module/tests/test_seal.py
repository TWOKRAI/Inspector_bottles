# -*- coding: utf-8 -*-
"""2.V1 — пломба: номер записи доезжает до диска, и по нему видно потерю.

План: plans/observability-unified-routing.md, задача 2.V1.

Проверяется АРТЕФАКТ, а не счётчик. Смысл задачи ровно в том, чтобы вердикт
«потеряно/не потеряно» не опирался на самоотчёт логгера: в Ф0.9 счётчик
``errors_to_floor`` означал «передано», а не «записано», и такому счётчику
верили. Поэтому все проверки здесь читают файлы с диска и считают арифметику
на номерах.

Свойства ломаются по отдельности — каждое своей инъекцией (список в плане):

  * номер ставится ровно один раз на прошедшую гейт запись;
  * отклонённая гейтом номера НЕ получает — иначе дырка означала бы «или
    потеря, или штатный отказ», и проверяющему пришлось бы спрашивать счётчики;
  * номер доезжает до файла НЕЗАВИСИМО от ``config.format`` — формат операбелен
    и сохраняется в рецептах, поле в нём ослепило бы проверку молча;
  * обе плоскости процесса (логи и ошибки) нумеруются сквозно;
  * батчевый путь номер не теряет;
  * пол ошибок несёт номер полем ``seq``.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from scripts.observability_seal import check_seal
from scripts.observability_seal.seal_check import SEAL_RE, UNSEALED_RE

from multiprocess_framework.modules.error_module.configs.error_manager_config import ErrorManagerConfig
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    SEAL_ABSENT,
    SEAL_LINE_RE,
    SealFormatter,
)
from multiprocess_framework.modules.logger_module.core.error_floor import (
    FLOOR_FILE_NAME,
    reset_error_floors,
)
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    reset_error_floors()
    yield
    reset_error_floors()


class _FakeProcess:
    def __init__(self, name: str) -> None:
        self.name = name


def _config(tmp_path: Path, *, batching: bool = False, fmt: str | None = None) -> LoggerManagerConfig:
    channel = LoggerChannelSchema(
        name="system_file",
        type="file",
        enabled=True,
        file_path="system.log",
        rotate=False,
    )
    if fmt is not None:
        channel.format = fmt
    return LoggerManagerConfig(
        app_name="seal",
        log_directory=str(tmp_path),
        enable_batching=batching,
        modules={},
        channels={"system_file": channel},
        scopes={
            "SYSTEM": LoggerScopeSchema(channels=["system_file"]),
            "BUSINESS": LoggerScopeSchema(channels=["system_file"]),
            "DEBUG": LoggerScopeSchema(channels=["system_file"]),
        },
    )


def _seqs(path: Path) -> List[int]:
    """Номера из файла в порядке строк — буквальным разбором префикса."""
    out: List[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SEAL_LINE_RE_COMPILED.match(line)
        if match:
            out.append(int(match.group(1)))
    return out


SEAL_LINE_RE_COMPILED = re.compile(SEAL_LINE_RE)


# =============================================================================
# Номер на диске
# =============================================================================


def test_every_accepted_record_carries_its_own_number(tmp_path: Path) -> None:
    logger = LoggerManager(config=_config(tmp_path))
    try:
        for i in range(5):
            logger.info(f"запись {i}")
    finally:
        logger.shutdown()

    seqs = _seqs(tmp_path / "system.log")
    assert len(seqs) >= 5
    # Литерал, а не производная от seqs: тест, выводящий ожидание из
    # проверяемого, согласится с любым ответом, включая «ничего».
    assert seqs[:5] == [seqs[0] + k for k in range(5)]
    assert len(set(seqs)) == len(seqs), "номер выдан дважды"


def test_gate_rejected_record_consumes_no_number(tmp_path: Path) -> None:
    """Отклонённая гейтом не тратит номер — иначе дырка перестала бы означать потерю.

    ``DEBUG``-скоуп в конфиге выключен, поэтому ``logger.debug`` до приёмников
    не доходит. Если бы номер выдавался ДО гейта, между двумя соседними
    ``info`` в файле образовался бы разрыв — и проверяющий назвал бы штатный
    отказ потерей.
    """
    logger = LoggerManager(config=_config(tmp_path))
    try:
        logger.info("до")
        for _ in range(10):
            logger.debug("отклонённая гейтом")
        logger.info("после")
    finally:
        logger.shutdown()

    seqs = _seqs(tmp_path / "system.log")
    assert seqs[1] == seqs[0] + 1, f"гейт съел номера: {seqs[:2]}"


def test_seal_survives_a_format_without_any_of_our_fields(tmp_path: Path) -> None:
    """Формат канала операбелен из конфига — пломба не имеет права от него зависеть.

    Будь пломба полем ``%(seq)s``, сохранённого рецепта со старым форматом
    хватило бы, чтобы проверяющий ослеп на этом канале и не сказал ни слова.
    """
    logger = LoggerManager(config=_config(tmp_path, fmt="%(message)s"))
    try:
        logger.info("голый формат")
    finally:
        logger.shutdown()

    lines = (tmp_path / "system.log").read_text(encoding="utf-8").splitlines()
    assert SEAL_LINE_RE_COMPILED.match(lines[0]), lines[0]
    assert lines[0].endswith("голый формат")


def test_batched_path_keeps_the_number(tmp_path: Path) -> None:
    """Батч-буфер сериализует запись в dict — номер обязан пережить круг."""
    logger = LoggerManager(config=_config(tmp_path, batching=True))
    try:
        for i in range(20):
            logger.info(f"батч {i}")
        logger.flush()
    finally:
        logger.shutdown()

    seqs = _seqs(tmp_path / "system.log")
    assert len(seqs) >= 20
    assert seqs[:20] == [seqs[0] + k for k in range(20)]


def test_record_built_bypassing_the_emission_point_is_marked_absent(tmp_path: Path) -> None:
    """Запись без номера помечается ``#-``, а не пишется голой.

    «Пломбы нет» обязано отличаться от «строку не разобрали»: иначе запись,
    построенная мимо ``LoggerCore.log``, выглядела бы для проверяющего как
    мусор и молча выпала из учёта.
    """
    formatter = SealFormatter("%(message)s")
    import logging

    record = logging.LogRecord("m", logging.INFO, "", 0, "мимо точки эмиссии", (), None)
    text = formatter.format(record)
    assert text.startswith(SEAL_ABSENT)
    assert UNSEALED_RE.match(text)
    assert not SEAL_RE.match(text)


# =============================================================================
# Две плоскости — одна нумерация
# =============================================================================


def test_both_planes_of_one_process_share_the_sequence(tmp_path: Path) -> None:
    """Логи и ошибки — братья через ``LoggerCore``; номер сквозной на процесс.

    Номер по экземпляру дал бы две независимые последовательности, и потеря на
    стыке (запись ушла в плоскость ошибок и пропала) не была бы видна ни в
    одной из них.
    """
    logger = LoggerManager(config=_config(tmp_path))
    errors = ErrorManager(
        config=ErrorManagerConfig(
            app_name="seal",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
        process=_FakeProcess("seal_probe"),
    )
    errors.initialize()
    try:
        logger.info("лог 1")
        errors.error("ошибка 1")
        logger.info("лог 2")
        errors.error("ошибка 2")
    finally:
        errors.shutdown()
        logger.shutdown()

    report = check_seal([tmp_path])
    assert report.verifiable, report.render()
    # Обе плоскости в одном каталоге: их номера обязаны сложиться в один
    # непрерывный отрезок, а не в две независимые лесенки.
    #
    # Проверяется ``ok``, а не только ``holes``: пломба-константа (``seq=1``
    # у всех) дырок не даёт — min и max совпадают, — и первая редакция теста
    # была под неё зелёной. Дубликаты как раз и отличают сквозную нумерацию от
    # заглушки. Поймано слом-инъекцией B1.
    assert report.duplicates == {}, report.render()
    assert report.ok, report.render()


def test_floor_record_carries_the_number(tmp_path: Path) -> None:
    """Пол ошибок пишет запись целиком — номер обязан быть полем ``seq``.

    Именно на полу проверка нужнее всего: туда запись попадает, когда штатный
    маршрут уже не сработал.
    """
    errors = ErrorManager(
        config=ErrorManagerConfig(
            app_name="seal",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
        process=_FakeProcess("floor_probe"),
    )
    errors.initialize()
    try:
        for name in list(errors._channel_registry.names()):
            errors._channel_registry.unregister(name)
        errors.error("некуда писать")
    finally:
        errors.shutdown()

    floors = list(tmp_path.rglob(FLOOR_FILE_NAME))
    assert floors, "пол не создан — проверять нечего"
    payload = json.loads(floors[0].read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(payload.get("seq"), int) and payload["seq"] > 0, payload


# =============================================================================
# Опасности механизма (тесты автора)
# =============================================================================


def test_concurrent_emitters_never_share_a_number(tmp_path: Path) -> None:
    """Гонка: 8 потоков × 60 записей — 480 РАЗНЫХ номеров, без дублей.

    ``next()`` на ``itertools.count`` атомарен под GIL; замена его на
    ``self._n += 1`` выдала бы двум потокам один номер, и проверяющий увидел бы
    дубликат вместо дырки — то есть потеря маскировалась бы «лишней» записью.
    """
    logger = LoggerManager(config=_config(tmp_path))
    threads = [threading.Thread(target=lambda k=k: [logger.info(f"t{k}-{i}") for i in range(60)]) for k in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive(), "эмитент завис — тест обязан падать, а не висеть"
    finally:
        logger.shutdown()

    seqs = _seqs(tmp_path / "system.log")
    # Литерал ПЕРВЫМ, и это не перестраховка: первая редакция звала ``max(seqs)``
    # внутри list comprehension, а на пустом списке условие не вычисляется вовсе —
    # тест оставался зелёным, когда пломба до файла не доезжала СОВСЕМ.
    # Поймано слом-инъекцией B4, глазом не видно.
    assert len(seqs) >= 8 * 60, f"пломб на диске {len(seqs)}, а записей было 480"
    assert len(set(seqs)) == len(seqs), "два потока получили один номер"


def test_precondition_default_scopes_all_reach_a_file_channel() -> None:
    """Предусловие проверяющего, проверенное, а не заявленное.

    2.V1 доказывает потерю только пока у каждой прошедшей гейт записи есть
    файловый приёмник. Скоуп, у которого в списке одна консоль, сделал бы
    штатное поведение неотличимым от потери. Здесь это свойство дефолтного
    конфига закреплено — сместится конфиг, тест назовёт скоуп.
    """
    config = LoggerManagerConfig()
    file_channels = {name for name, channel in config.channels.items() if channel.type == "file" and channel.enabled}
    for scope_name, scope in config.scopes.items():
        # Ф8.1: выключателя у скоупа больше нет — проверяются ВСЕ группы.
        # Раньше выключенный DEBUG пропускался, и предусловие про него молчало.
        targets = set(scope.channels) or set(config.channels)
        assert targets & file_channels, f"скоуп {scope_name} не пишет ни в один файл"


def test_script_and_framework_agree_on_the_prefix() -> None:
    """Регулярка проверяющего и префикс фреймворка — одно и то же.

    Проверяющий намеренно не импортирует фреймворк (иначе это согласие двух
    моих компонентов, а не проверка). Цена независимости — две константы,
    которые могут разъехаться молча; тест их и сводит.
    """
    assert SEAL_RE.pattern == SEAL_LINE_RE
    assert UNSEALED_RE.match(SEAL_ABSENT)


# =============================================================================
# Приёмка 2.V1: слом — выбросить каждую 10-ю запись в канале
# =============================================================================


def test_verifier_names_the_exact_dropped_numbers(tmp_path: Path) -> None:
    """Слом-инъекция приёмки: канал молча теряет каждую 10-ю запись.

    Ни один счётчик логгера при этом не шевелится — канал отвечает «принял».
    Ровно этот класс («тихая потеря») человек ищет днями. Проверяющий обязан
    назвать ТОЧНЫЕ номера, а не «что-то не сходится».
    """
    logger = LoggerManager(config=_config(tmp_path))
    channel = logger._channel_registry.get("system_file")
    original_write = channel.write
    dropped: List[int] = []
    seen = {"n": 0}

    def lossy_write(record: Dict[str, Any]) -> Dict[str, Any]:
        seen["n"] += 1
        if seen["n"] % 10 == 0:
            dropped.append(int(record.get("seq") or 0))
            return {"status": "success", "channel": "system_file"}  # соврал, что записал
        return original_write(record)

    channel.write = lossy_write  # type: ignore[method-assign]
    try:
        for i in range(100):
            logger.info(f"запись {i}")
    finally:
        channel.write = original_write  # type: ignore[method-assign]
        logger.shutdown()

    assert len(dropped) == 10, dropped
    report = check_seal([tmp_path])
    assert report.verifiable, report.render()
    assert report.holes == sorted(dropped), report.render()
    assert report.exit_code == 1


def test_verifier_is_green_on_the_same_scenario_without_the_break(tmp_path: Path) -> None:
    """Контроль к слому: без инъекции тот же сценарий даёт ноль дырок.

    Без этой пары «дырки найдены» ничего не стоило бы: проверяющий, который
    ругается всегда, неотличим от сломанного.
    """
    logger = LoggerManager(config=_config(tmp_path))
    try:
        for i in range(100):
            logger.info(f"запись {i}")
    finally:
        logger.shutdown()

    report = check_seal([tmp_path])
    assert report.verifiable, report.render()
    assert report.holes == [], report.render()
    assert report.exit_code == 0
