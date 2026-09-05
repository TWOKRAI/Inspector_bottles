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
7. **Один разъём на точку.** Отказ уходит ТОЛЬКО в плоскость ошибок. Параллельная
   строка в ``system.log`` не «дублирует для удобства», а лишает смысла вопрос
   «сколько раз это случилось» — считать инциденты станет нечем.

Итерация 1 ревью добавила ещё пять — все пять про свойства, которые механизм
ЗАЯВЛЯЛ (в docstring или комментарии), но не охранял ничем:

8. **Отказ подъёма — тоже один раз** (F2). Идемпотентность держалась на
   результате успеха, поэтому мёртвый журнал пробовали поднять на каждой записи.
9. **``stop()`` терминален** (F3). После закрытия журнал не воскресает, а записи
   уходят в аварийный выход, а не в никуда.
10. **Журнал закрывается ПОСЛЕДНИМ** (F7). До починки 9 этот порядок соблюдался
    «сам собой» — потому что журнал воскресал, а не потому что порядок верен.
11. **Ноль освобождённых сегментов бывает двух сортов** (F1, F6). На платформе,
    где висящих сегментов не бывает, ноль — свойство платформы; живой сегмент не
    имеет права считаться освобождённым; «упала» не равно «нашла ноль».
12. **Отказ реапа PID-реестра слышен** (F8) — тот же голый ``except: pass`` на
    том же пути «до существования хоть одного процесса».

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

from ...shared_resources_module.memory.platform import is_posix
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


def _messages_log(root: Any) -> str:
    """Файл INFO-плоскости лаунчера.

    До Task 3.2 записи INFO лежали в ``system.log``: скоуп ``BUSINESS`` писал
    в ОБА файла, и ``messages.log`` был строгим подмножеством ``system.log``
    (замер на восьми процессах: 368 строк, 0 уникальных). Решение владельца
    Р-7(а) убрало ``system_file`` из ``BUSINESS``, а ``_LEVEL_DEFAULT_SCOPE``
    отображает ``INFO -> BUSINESS`` — поэтому INFO лаунчера теперь здесь.
    Инвариант одинаков во всех каталогах, включая ``launcher/``:
    ``messages.log`` = INFO, ``system.log`` = WARNING+ и DEBUG-скоуп.
    """
    path = root / "launcher" / "messages.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _errors_log(root: Any) -> str:
    path = root / "launcher" / "errors.log"
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

        assert marker in _messages_log(log_root), (
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

        content = _messages_log(log_root)
        starts = len(re.findall(r"LoggerManager initialized", content))
        assert starts == 1, f"журнал поднялся {starts} раз(а) вместо одного:\n{content}"
        for i in range(5):
            assert content.count(f"запись {i}") == 1, f"'запись {i}' в файле не ровно один раз:\n{content}"


class TestTheRaiseIsAlsoOnceOnFailure:
    """Вторая половина опасности 2 (ревью Task 1.2, F2): отказ — тоже один раз.

    Флагом идемпотентности был результат УСПЕХА (``_logger_manager``), поэтому
    пока подъём падал, каждая запись пробовала снова. Замер до правки — 5 записей
    дали 5 аварийных выходов; замер с падающим ``ErrorManager`` — 3 записи дали 3
    живых ``LoggerManager``, каждый со своими файлами и потоком подметальщика.
    """

    def test_a_failed_raise_is_not_retried_on_every_record(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, launchers: Any
    ) -> None:
        """Каталог занят файлом → 5 записей дают РОВНО один аварийный выход."""
        blocked = tmp_path / "occupied"
        blocked.write_text("это файл, а не каталог", encoding="utf-8")
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(blocked))
        monkeypatch.setenv("INSPECTOR_LOG_DIR", str(blocked))

        calls: List[Any] = []
        monkeypatch.setattr(
            "multiprocess_framework.modules._fallback.emergency_log",
            lambda *a, **kw: calls.append(a),
        )

        launcher = launchers()

        def _emit() -> None:
            for i in range(5):
                launcher._log_info(f"запись {i}")

        _within_deadline(_emit, "пять записей при мёртвом журнале")

        raises = [c for c in calls if "не поднялся" in str(c)]
        assert len(raises) == 1, f"подъём журнала пробовали {len(raises)} раз(а) вместо одного: {calls!r}"

    def test_a_half_raised_journal_still_has_an_owner(
        self, log_root: Any, monkeypatch: pytest.MonkeyPatch, launchers: Any
    ) -> None:
        """``ErrorManager`` падает → поднятый логгер обязан остаться на объекте.

        Иначе он осиротеет: файлы открыты, поток подметальщика жив, а
        ``_shutdown_observability`` его не увидит и не закроет.
        """
        import multiprocess_framework.modules.error_module as error_module

        def _boom(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("ErrorManager не создался")

        monkeypatch.setattr(error_module, "ErrorManager", _boom)

        launcher = launchers()
        _within_deadline(lambda: launcher._log_info("запись при падающем ErrorManager"), "запись")

        assert launcher._logger_manager is not None, (
            "логгер поднялся, но владельца не получил — закрывать его будет некому"
        )
        assert launcher._error_manager is None
        closed: List[str] = []
        monkeypatch.setattr(launcher._logger_manager, "shutdown", lambda: closed.append("logger"))
        _within_deadline(launcher._shutdown_observability, "закрытие")
        assert closed == ["logger"], "полуподнятый журнал не закрыли"


class TestStopIsTerminal:
    """F3: ``stop()`` терминален — следующая запись не воскрешает журнал.

    До правки три ``stop()`` давали три подъёма и три строки закрытия, а запись
    после закрытия снова открывала файлы. «Журнал закрыт» переставало что-либо
    значить, и обещание README о безусловном маршруте держалось ровно этим.
    """

    def test_a_record_after_stop_does_not_raise_the_journal_again(
        self, log_root: Any, monkeypatch: pytest.MonkeyPatch, launchers: Any
    ) -> None:
        launcher = launchers()
        _within_deadline(lambda: launcher._log_info("до закрытия"), "первая запись")
        _within_deadline(launcher.stop, "первый stop")
        _within_deadline(launcher.stop, "второй stop")

        calls: List[Any] = []
        monkeypatch.setattr(
            "multiprocess_framework.modules._fallback.emergency_log",
            lambda *a, **kw: calls.append(a),
        )
        marker = "ПОСЛЕ_ЗАКРЫТИЯ"
        _within_deadline(lambda: launcher._log_info(marker), "запись после закрытия")

        content = _messages_log(log_root)
        assert content.count("LoggerManager initialized") == 1, (
            f"журнал поднялся заново после stop() — «закрыт» ничего не значит:\n{content}"
        )
        assert marker not in content, "запись после закрытия попала в закрытый журнал"
        assert any(marker in str(c) for c in calls), (
            f"запись после закрытия пропала молча — аварийный выход её не получил: {calls!r}"
        )


class TestJournalClosesLast:
    """F7: «журнал закрывается ПОСЛЕДНИМ» было комментарием, а не свойством.

    Инъекция (перенос ``_shutdown_observability()`` в НАЧАЛО ``stop()``) не
    роняла ничего: строки всё равно доезжали — потому что журнал воскресал
    (F3), а не потому что порядок соблюдён. Сторож ставится ПОСЛЕ починки F3,
    иначе он охранял бы воскрешение.
    """

    def test_the_stop_lines_are_in_the_file(self, log_root: Any, launchers: Any) -> None:
        class _FakeSpawner:
            def stop(self) -> None:
                return None

        launcher = launchers()
        launcher._spawner = _FakeSpawner()
        _within_deadline(launcher.stop, "остановка с журналом")

        content = _messages_log(log_root)
        assert "Stopping system..." in content, f"строка начала остановки не доехала:\n{content}"
        assert "System stopped" in content, (
            f"«System stopped» не доехала — журнал закрылся раньше строк, которые обязан был принять:\n{content}"
        )


class TestPidRegistryFailureHasAVoice:
    """F8: отказ реапа PID-реестра — та же плоскость ошибок и свой счётчик.

    Голый ``except: pass`` стоял на пути «до существования хоть одного процесса»
    строкой выше уборки SHM — того самого класса, который эта задача чинила.
    Провалившийся реап означает выживших от прошлого запуска.
    """

    def test_a_failed_reap_is_counted_and_told(
        self, log_root: Any, monkeypatch: pytest.MonkeyPatch, launchers: Any
    ) -> None:
        marker = f"РЕАП_НЕ_УДАЛСЯ_{uuid.uuid4().hex[:6]}"
        monkeypatch.setattr(
            "multiprocess_framework.modules.process_manager_module.launcher.pid_registry.reap_and_reset",
            _failing_cleanup(marker),
        )

        launcher = launchers()
        _within_deadline(launcher._prepare_pid_registry, "подготовка реестра")
        _within_deadline(launcher._shutdown_observability, "закрытие журнала")

        assert launcher.get_stats()["startup"]["pid_registry_failures"] == 1, (
            "отказ реапа не посчитан — «выжившие от прошлого запуска» остались без единого следа"
        )
        errors = _errors_log(log_root)
        assert marker in errors, f"отказ реапа не доехал до errors.log:\n{errors}"
        assert "Traceback" in errors, f"отказ реапа приехал без трассы:\n{errors}"


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
    """Опасность 5: «очищено N» — измеренное число, а не украшение строки.

    **Переписан по ревью (F1).** Первая редакция создавала сегмент, ДЕРЖАЛА его
    открытым и ждала «очищено 1». На POSIX это правда (``unlink`` снимает имя у
    живого сегмента), а на Windows единица приходила по обратной причине:
    ``SharedMemory(create=False)`` там резолвится ровно потому, что сегмент ЖИВ и
    его кто-то держит. Тест не проверял уборку — он пришпиливал перевёрнутый
    смысл, и стенд (Windows) считал этой строкой НЕ убранное.

    Поэтому пара разделена по платформам, и обе половины буквальны.
    """

    def test_on_posix_cleanup_takes_the_name_away(self, log_root: Any, launchers: Any) -> None:
        """POSIX: висящий сегмент → ровно 1, и ИМЕНИ после уборки больше нет.

        Второй assert важнее первого: единица без проверки имени согласна и с
        «функция посчитала, но ничего не сделала».
        """
        if not is_posix():
            pytest.skip("на не-POSIX уборка недоступна — половина пары ниже")
        region = f"hz{uuid.uuid4().hex[:8]}"
        leaked = shared_memory.SharedMemory(name=f"{region}_0", create=True, size=64)
        launcher = launchers()
        try:
            leaked.close()
            _within_deadline(
                lambda: launcher._cleanup_shm_at_startup({"p": {"memory": {"names": {region: (1, 1, 1)}, "coll": 1}}}),
                "уборка висящего сегмента",
            )
            assert launcher.get_stats()["startup"]["shm_cleanup_segments"] == 1
            assert "cleanup_stale_shm: очищено 1 SHM-сегментов" in _messages_log(log_root)
            with pytest.raises(FileNotFoundError):
                shared_memory.SharedMemory(name=f"{region}_0", create=False)
        finally:
            try:
                leaked.unlink()
            except Exception:  # noqa: BLE001 — teardown теста не имеет права падать
                pass

    def test_a_living_segment_is_never_counted_as_freed(self, log_root: Any, launchers: Any) -> None:
        """Не-POSIX: живой сегмент обязан дать 0 — и остаться живым.

        Ровно то, что делал прежний тест наоборот. На Windows уборка не убирает
        ничего, поэтому единственный честный ответ про ЖИВОЙ сегмент — ноль; а
        строка журнала обязана сказать, что ноль здесь про платформу, иначе стенд
        читает его как «уборка работала и ничего не нашла».
        """
        if is_posix():
            pytest.skip("на POSIX уборка снимает имя — половина пары выше")
        region = f"hz{uuid.uuid4().hex[:8]}"
        alive = shared_memory.SharedMemory(name=f"{region}_0", create=True, size=64)
        alive.buf[0] = 42
        launcher = launchers()
        try:
            _within_deadline(
                lambda: launcher._cleanup_shm_at_startup({"p": {"memory": {"names": {region: (1, 1, 1)}, "coll": 1}}}),
                "уборка живого сегмента",
            )
            assert launcher.get_stats()["startup"]["shm_cleanup_segments"] == 0, (
                "живой сегмент посчитан освобождённым — счётчик перечисляет ровно НЕ убранное"
            )
            still = shared_memory.SharedMemory(name=f"{region}_0", create=False)
            try:
                assert still.buf[0] == 42, "сегмент изменился — «уборка» на этой платформе что-то трогает"
            finally:
                still.close()
            assert "уборка на этой платформе недоступна" in _messages_log(log_root), (
                "строка журнала выдаёт свойство платформы за показание об уборке"
            )
        finally:
            try:
                alive.close()
            except Exception:  # noqa: BLE001 — teardown теста не имеет права падать
                pass
            try:
                alive.unlink()
            except Exception:  # noqa: BLE001
                pass

    def test_three_states_of_the_segment_counter(self, log_root: Any, launchers: Any, monkeypatch: Any) -> None:
        """F6: «не выполнялась», «упала» и «освободила N» — три РАЗНЫХ показания.

        Пара читается вместе с ``shm_cleanup_failures``; если отказ выставит
        число (хоть ноль), «упала» станет неотличимо от «нашла ноль».
        """
        launcher = launchers()
        fresh = launcher.get_stats()["startup"]
        assert fresh["shm_cleanup_segments"] is None and fresh["shm_cleanup_failures"] == 0, (
            "до первой уборки число обязано быть неизвестным"
        )

        monkeypatch.setattr(
            "multiprocess_framework.modules.shared_resources_module.memory.platform.cleanup_known_shm_at_startup",
            _failing_cleanup("отказ ради третьего состояния"),
        )
        _within_deadline(
            lambda: launcher._cleanup_shm_at_startup({"p": {"memory": {"names": {"x": (1, 1, 1)}, "coll": 1}}}),
            "упавшая уборка",
        )
        failed = launcher.get_stats()["startup"]
        assert failed["shm_cleanup_failures"] == 1
        assert failed["shm_cleanup_segments"] is None, (
            "упавшая уборка выставила ЧИСЛО — «сломалась» стало неотличимо от «ничего не нашла»"
        )


class TestErrorPlaneHasAnAddress:
    """F7: у плоскости ошибок лаунчера есть СВОЁ имя, и оно приходит из конфига.

    Свойство было заявлено комментарием («без этой строки звалась бы безадресным
    ErrorManager») и не охранялось ничем: инъекция, снявшая ``model_copy``,
    оставила все тесты зелёными. Воспроизведение 2026-08-31 показывает, что само
    утверждение ВЕРНО — имя конфига сильнее аргумента конструктора::

        WITHOUT model_copy -> manager_name = ErrorManager
        WITH model_copy    -> manager_name = error_launcher

    Значит нужен не отзыв утверждения, а сторож. Объектив — живой менеджер, а не
    текст в файле: под инъекцией текст ``errors.log`` не меняется вовсе, разница
    видна только в имени менеджера.
    """

    def test_the_error_plane_is_named_after_the_launcher(self, log_root: Any, launchers: Any) -> None:
        launcher = launchers()
        _within_deadline(lambda: launcher._log_info("поднять журнал"), "подъём журнала")

        error = launcher._error_manager
        assert error is not None, "плоскость ошибок не поднялась"
        assert error.manager_name == "error_launcher", (
            f"плоскость ошибок лаунчера зовётся '{error.manager_name}' — безадресно: "
            "по имени в записи нельзя понять, чья это плоскость"
        )


class TestOneBaseForTheWholeRun:
    """F4: база каталога логов у лаунчера и у слоя L0 процессов — ОДНА функция.

    Общей была только ``managers_from_log_dir``; аргумент ей считали две разные
    функции с разными последними рубежами, и при молчащем окружении один запуск
    писал в два дерева. Проверяется на ПУСТОМ окружении — единственном режиме,
    где рубежи вообще различимы.
    """

    def test_bases_coincide_on_an_empty_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("MULTIPROCESS_LOG_DIR", "INSPECTOR_LOG_DIR"):
            monkeypatch.delenv(key, raising=False)
        from multiprocess_framework.modules.logger_module.core.log_paths import default_log_base_directory
        from multiprocess_framework.modules.process_module.managers.observability_reload import resolve_base_log_dir

        assert resolve_base_log_dir() == str(default_log_base_directory()), (
            "слой L0 процессов и журнал лаунчера резолвят базу по-разному — один запуск, два дерева логов"
        )


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


class TestOneConnectorPerPoint:
    """Опасность 7: отказ, рассказанный дважды, ломает счёт «сколько раз».

    :meth:`SystemLauncher._log_error` пишет ТОЛЬКО в плоскость ошибок — это
    заявлено в его docstring как свойство конструкции, но до этого теста его не
    сторожил никто. Замер 2026-08-31 (матрица инъекций, М5): заплатка, дописавшая
    к отказу параллельную строку в ``system.log``, оставила ВСЕ 34 теста задачи
    зелёными, а ручная проба показала маркер разом в двух файлах.

    Дубль опасен не объёмом файла: по двум строкам об одном инциденте нельзя
    ответить, сколько раз он случился, а именно повтор отличает разовый сбой от
    насовсем сломанной уборки.

    Ожидания — литералы, и вторая половина важнее первой: маркер обязан быть в
    ``errors.log`` и обязан ОТСУТСТВОВАТЬ в ``system.log``.
    """

    def test_a_failure_is_told_once_and_only_to_the_error_plane(self, log_root: Any, launchers: Any) -> None:
        launcher = launchers()
        marker = "ОДИН_РАЗЪЁМ_НА_ТОЧКУ"

        def _emit() -> None:
            # Изнутри except: log_exception собирает трассу из активного исключения.
            try:
                raise RuntimeError(marker)
            except RuntimeError as exc:
                launcher._log_error("проверка одного разъёма", exc)

        _within_deadline(_emit, "запись отказа")
        _within_deadline(launcher._shutdown_observability, "закрытие журнала")

        errors = _errors_log(log_root)
        # Task 3.2 (Р-7(а)): плоскость логов лежит теперь в ДВУХ файлах —
        # `messages.log` (INFO) и `system.log` (WARNING+ и DEBUG-скоуп).
        # Утверждение об отсутствии обязано покрывать обе половины: проверяя
        # только `system.log`, тест согласился бы с дублем, приехавшим по
        # INFO-дороге, и остался бы зелёным — то есть ослеп бы ровно на том
        # классе, ради которого написан.
        log_plane = _system_log(log_root) + _messages_log(log_root)
        assert marker in errors, f"errors.log не содержит маркер отказа: {errors!r}"
        assert marker not in log_plane, (
            "тот же инцидент попал ВТОРОЙ строкой в плоскость логов "
            "(system.log или messages.log) — «сколько раз это случилось» "
            f"перестаёт иметь ответ: {log_plane!r}"
        )


class TestPrefixCleanupTellsThePlatform:
    """Р5: у ПРЕФИКСНОГО блока гейт строже, а строка журнала об этом молчала.

    Ревью Task 1.2 закрыло этот класс в первом блоке уборки и оставило его
    открытым в блоке-близнеце. ``cleanup_orphaned_by_prefix`` сканирует
    ``/dev/shm`` и работает ТОЛЬКО на Linux: на Windows enumeration недоступен,
    на macOS каталога просто нет. То есть на двух платформах проекта из трёх
    строка «очищено 0 по префиксам …» была свойством платформы, выданным за
    показание об уборке — ровно то, за что правился первый блок.

    Ожидания литералами и обе половины нужны: без первой тест согласится с
    исчезновением строки вовсе, без второй — с молчанием о платформе.
    """

    def test_the_prefix_line_says_the_scan_is_unavailable(
        self, log_root: Any, launchers: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from multiprocess_framework.modules.shared_resources_module.buffers.cleanup import _is_linux

        if _is_linux():
            pytest.skip("на Linux скан реален — ноль там показание, а не свойство платформы")
        monkeypatch.setenv("FW_SHM_PREFIX_CLEANUP", "1")
        launcher = launchers()

        _within_deadline(lambda: launcher._cleanup_shm_at_startup({}), "уборка с префиксным блоком")

        content = _messages_log(log_root)
        assert "cleanup_orphaned_by_prefix: очищено 0 SHM-сегментов" in content, (
            f"строки префиксной уборки нет в журнале вовсе: {content!r}"
        )
        assert "скан по префиксу доступен только на Linux" in content, (
            "строка выдаёт недоступность скана за результат уборки — читатель стенда "
            f"не отличит «чистить было нечего» от «сканировать здесь нечем»: {content!r}"
        )
