# -*- coding: utf-8 -*-
"""Task 1.2 — опасности САМОГО механизма журнала лаунчера (тесты автора).

Приёмочные тесты задачи живут отдельно
(``test_launcher_startup_observability_acceptance.py``, независимый тестер) и
судят КОНТРАКТ: строка в файле, трасса в ``errors.log``, счётчик равен 1. Здесь —
то, что видно только автору механизма: что именно в НЁМ может сломаться, если
знать, как он построен.

Механизм построен так: журнал лаунчера (``LoggerManager`` + ``ErrorManager`` в
``{база}/launcher/``) поднимается **лениво, на первой записи**
(:meth:`SystemLauncher._ensure_observability`), а уборка SHM растит собственный
счётчик отказов, который живёт на объекте лаунчера и виден через ``get_stats()``.
Отсюда список опасностей — по одной на конструктивное решение:

1. **Порядок.** Первая же запись обязана доехать. Ленивый подъём означает, что
   между «объект создан» и «журнал есть» существует окно, и если запись сделана
   в нём, она теряется. Проверяется буквально первой записью.
2. **Ровно один подъём.** Ленивая инициализация без флага поднимала бы менеджер
   на КАЖДОЙ записи; второй ``LoggerManager`` перебивает процессный синглтон и
   двигает эпоху наблюдаемости, то есть отвязывает чужие фасады. Наблюдаемое
   следствие — число собственных строк менеджера о старте в файле; ожидание
   написано литералом (ровно 1), а не выведено из кода.
3. **Мёртвый журнал не имеет права ни сорвать старт, ни съесть счётчик.** Каталог
   логов может быть неписуемым (место, права, путь занят файлом). Это ровно тот
   случай, где «наблюдаемость сломалась» обязано остаться отдельным фактом от
   «уборка сломалась»: счётчик отказов уборки обязан вырасти даже тогда, когда
   записать о них некуда.
4. **Счётчик считает ОТКАЗ, а не вызов.** Пара: на успешной уборке он остаётся
   нулём (ложноположительная половина), на двух подряд отказах равен двум
   (ложноотрицательная).
5. **Число сегментов — настоящее.** Уборка реального висящего сегмента обязана
   дать ровно 1, отсутствие висящих — ровно 0. Без этой пары «очищено N» — это
   константа, согласная с любым ответом.
6. **Закрытие идемпотентно.** ``stop()`` зовут и повторно, и на не поднятом
   журнале.

Все обращения к журналу идут через :func:`_within_deadline` — подъём менеджера
открывает файлы и стартует поток подметальщика, и тест, который вместо падения
ПОВИСНЕТ, хуже отсутствующего.
"""

from __future__ import annotations

import re
import threading
import uuid
from multiprocessing import shared_memory
from typing import Any, Callable, Dict, List

import pytest

from ..launcher.system_launcher import SystemLauncher

_DEADLINE_SEC = 30.0


def _within_deadline(fn: Callable[[], Any], what: str) -> Any:
    """Выполнить ``fn`` в демон-потоке с пределом ожидания.

    Правило проекта: тест, который может заблокироваться, обязан падать по
    таймауту, а не висеть — повисший тест прячет регрессию за пределом ожидания
    прогонщика. Результат и исключение переносятся в вызывающий поток, поэтому
    обычный ``assert`` внутри ``fn`` остаётся видимым.
    """
    box: Dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносим в основной поток
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True, name=f"hazard-{what}")
    thread.start()
    thread.join(_DEADLINE_SEC)
    assert not thread.is_alive(), f"{what} не завершилось за {_DEADLINE_SEC}с — механизм заблокировался"
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.fixture
def launchers() -> Any:
    """Лаунчеры теста, закрываемые после него.

    Журнал лаунчера держит открытые файлы и поток подметальщика; без закрытия
    они переживают тест и на Windows не дают удалить ``tmp_path``.
    """
    created: List[SystemLauncher] = []

    def _make() -> SystemLauncher:
        launcher = SystemLauncher()
        created.append(launcher)
        return launcher

    yield _make

    for launcher in created:
        launcher._shutdown_observability()


@pytest.fixture
def log_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Изолировать базу логов И PID-реестр на ``tmp_path``.

    Обе ручки каждой пары: ``MULTIPROCESS_*`` сильнее ``INSPECTOR_*`` в резолве,
    и унаследованная из окружения сильная ручка молча перебила бы слабую. Реестр
    изолируется по той же причине, что в приёмочном файле: реап реестра ПО
    УМОЛЧАНИЮ убил бы процессы вручную запущенного стенда (Н-8).
    """
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path))
    pid_file = str(tmp_path / "hazard_pid_registry.jsonl")
    monkeypatch.setenv("MULTIPROCESS_PID_FILE", pid_file)
    monkeypatch.setenv("INSPECTOR_PID_FILE", pid_file)
    return tmp_path


def _system_log(root: Any) -> str:
    path = root / "launcher" / "system.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _failing_cleanup(marker: str) -> Callable[..., None]:
    def _raise(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError(marker)

    return _raise


class TestOrderingAndSingleRaise:
    """Опасности 1 и 2: окно до подъёма журнала и повторный подъём."""

    def test_the_very_first_record_reaches_the_file(self, log_root: Any, launchers: Any) -> None:
        """Первая же запись лаунчера обязана лежать в файле.

        Ленивый подъём означает окно «объект есть, журнала нет». Если бы подъём
        стоял ПОСЛЕ записи (или только в ``start()``), эта строка исчезла бы —
        и исчезла бы именно первая, то есть самая нужная в разборе «почему
        система не поднялась».
        """
        launcher = launchers()
        marker = f"первая запись {uuid.uuid4().hex[:8]}"
        _within_deadline(lambda: launcher._log_info(marker), "первая запись")

        assert marker in _system_log(log_root), (
            f"первая запись лаунчера не доехала до {log_root / 'launcher' / 'system.log'}"
        )

    def test_journal_is_raised_exactly_once_for_many_records(self, log_root: Any, launchers: Any) -> None:
        """Пять записей — ОДИН подъём журнала.

        Наблюдаемое следствие второго подъёма — вторая собственная строка
        менеджера ``LoggerManager initialized`` в том же файле (её пишет
        ``LoggerCore.initialize``). Ожидание — литерал 1, а не «столько же,
        сколько насчитает код».
        """
        launcher = launchers()

        def _emit() -> None:
            for i in range(5):
                launcher._log_info(f"запись {i}")

        _within_deadline(_emit, "пять записей")

        content = _system_log(log_root)
        starts = len(re.findall(r"LoggerManager initialized", content))
        assert starts == 1, f"журнал поднялся {starts} раз(а) вместо одного:\n{content}"
        for i in range(5):
            assert content.count(f"запись {i}") == 1, f"'запись {i}' в файле не ровно один раз:\n{content}"


class TestCounterSurvivesADeadJournal:
    """Опасность 3: неписуемый каталог логов не отменяет ни старт, ни учёт."""

    def test_failure_is_counted_even_when_the_journal_cannot_be_raised(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, launchers: Any
    ) -> None:
        """Каталог логов занят ФАЙЛОМ → журнала нет, а счётчик отказов растёт.

        Это разделение двух фактов: «уборка сломалась» и «записать об этом
        некуда» — разные отказы, и второй не имеет права поглотить первый.
        Иначе на машине с неписуемым каталогом система выглядела бы здоровой
        ровно в том случае, когда здоровья меньше всего.
        """
        blocked = tmp_path / "occupied"
        blocked.write_text("это файл, а не каталог", encoding="utf-8")
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(blocked))
        monkeypatch.setenv("INSPECTOR_LOG_DIR", str(blocked))
        monkeypatch.setenv("MULTIPROCESS_PID_FILE", str(tmp_path / "pid.jsonl"))
        monkeypatch.setenv("INSPECTOR_PID_FILE", str(tmp_path / "pid.jsonl"))
        monkeypatch.setattr(
            "multiprocess_framework.modules.shared_resources_module.memory.platform.cleanup_known_shm_at_startup",
            _failing_cleanup("сбой при неписуемом каталоге"),
        )

        launcher = launchers()
        _within_deadline(
            lambda: launcher._cleanup_shm_at_startup({"p": {"memory": {"names": {"x": (1, 1, 1)}, "coll": 1}}}),
            "уборка при мёртвом журнале",
        )

        assert launcher._logger_manager is None, "журнал не должен был подняться на неписуемом каталоге"
        assert launcher.get_stats()["startup"]["shm_cleanup_failures"] == 1


class TestFailureCounterIsAPair:
    """Опасность 4: счётчик считает ОТКАЗ, а не вызов."""

    def test_successful_cleanup_leaves_the_counter_at_zero(self, log_root: Any, launchers: Any) -> None:
        """Ложноположительная половина: событие не случилось — счётчик не растёт."""
        launcher = launchers()
        absent = {"p": {"memory": {"names": {"нет_такого": (1, 1, 1)}, "coll": 1}}}
        _within_deadline(lambda: launcher._cleanup_shm_at_startup(absent), "успешная уборка")

        stats = launcher.get_stats()["startup"]
        assert stats["shm_cleanup_failures"] == 0
        assert stats["shm_cleanup_segments"] == 0

    def test_two_failures_in_a_row_give_two(self, log_root: Any, launchers: Any, monkeypatch: Any) -> None:
        """Ложноотрицательная половина: два отказа — счётчик 2, а не «1» и не «True».

        Число, а не флаг: разовый сбой и залипший отличаются только повтором, и
        флаг стирает эту разницу — ровно на ней принимают решение «чинить сейчас
        или посмотреть завтра».
        """
        monkeypatch.setattr(
            "multiprocess_framework.modules.shared_resources_module.memory.platform.cleanup_known_shm_at_startup",
            _failing_cleanup("повторный сбой уборки"),
        )
        launcher = launchers()
        config = {"p": {"memory": {"names": {"x": (1, 1, 1)}, "coll": 1}}}

        def _twice() -> None:
            launcher._cleanup_shm_at_startup(config)
            launcher._cleanup_shm_at_startup(config)

        _within_deadline(_twice, "два отказа уборки")

        assert launcher.get_stats()["startup"]["shm_cleanup_failures"] == 2


class TestSegmentCountIsReal:
    """Опасность 5: «очищено N» — измеренное число, а не украшение строки."""

    def test_one_leaked_segment_is_reported_as_one(self, log_root: Any, launchers: Any) -> None:
        """Реальный висящий сегмент → ровно 1 и в счётчике, и в строке журнала.

        Пара к :meth:`TestFailureCounterIsAPair.test_successful_cleanup_leaves_the_counter_at_zero`
        (там тот же вызов даёт ровно 0). Без пары строка «очищено N» согласна с
        любым ответом, включая «уборка не работает вовсе».
        """
        region = f"hz{uuid.uuid4().hex[:8]}"
        leaked = shared_memory.SharedMemory(name=f"{region}_0", create=True, size=64)
        launcher = launchers()
        try:
            _within_deadline(
                lambda: launcher._cleanup_shm_at_startup({"p": {"memory": {"names": {region: (1, 1, 1)}, "coll": 1}}}),
                "уборка висящего сегмента",
            )
            assert launcher.get_stats()["startup"]["shm_cleanup_segments"] == 1
            assert "cleanup_stale_shm: очищено 1 SHM-сегментов" in _system_log(log_root)
        finally:
            try:
                leaked.close()
            except Exception:  # noqa: BLE001 — teardown теста не имеет права падать
                pass
            try:
                leaked.unlink()
            except FileNotFoundError:
                pass
            except Exception:  # noqa: BLE001
                pass


class TestShutdownIsIdempotent:
    """Опасность 6: закрытие зовут повторно и на не поднятом журнале."""

    def test_shutdown_twice_and_without_a_journal_does_not_raise(self, log_root: Any, launchers: Any) -> None:
        launcher = launchers()
        _within_deadline(launcher._shutdown_observability, "закрытие без журнала")
        _within_deadline(lambda: launcher._log_info("что-нибудь"), "запись")
        _within_deadline(launcher._shutdown_observability, "первое закрытие")
        _within_deadline(launcher._shutdown_observability, "повторное закрытие")

        assert launcher._logger_manager is None
        assert launcher._error_manager is None
