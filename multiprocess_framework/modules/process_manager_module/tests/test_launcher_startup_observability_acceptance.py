# -*- coding: utf-8 -*-
"""Task 1.2 плана observability-closure — независимый тестер, ДО реализации.

Источник контракта: акцептанс-критерии задачи (переданы координатором, НЕ читались
из ``plans/observability-closure/**`` — это запрещённый путь). Проверяются ровно две
из трёх заявленных «невидимых поломок»:

1. Лончер (``SystemLauncher``, код ДО существования единого процесса) логирует INFO
   в никуда — записи не попадают в файл.
3. Очистка устаревшего SHM обёрнута в голый ``except: pass`` — при сбое ничего не
   логируется и ничего не считается.

Оба теста здесь вызывают ``SystemLauncher._prepare_pid_registry()`` +
``SystemLauncher._cleanup_shm_at_startup(processes_config)`` НАПРЯМУЮ — именно ту
последовательность, которую ``start()``/``run()`` исполняют ДО создания spawner'а
(см. исходник ``launcher/system_launcher.py``). Полный boot дочерних процессов здесь
не нужен: обе поломки происходят до появления хоть одного дочернего процесса.

**Риск, который я называю заранее (см. отчёт координатору):** если фикс поместит
настройку логирования лончера СТРОГО внутри ``start()``/``run()`` (например, первой
строкой, ДО ``_prepare_pid_registry()``), а не внутри самих приватных методов —
тесты этого файла останутся красными и ПОСЛЕ корректной реализации (ложный красный).
Я не читаю реализацию, поэтому проверить это не могу — называю риск явно.
"""

from __future__ import annotations

import re
import uuid
from multiprocessing import shared_memory
from typing import Any, Dict, List, Tuple

import pytest

from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
    SystemLauncher,
)


def _find_key(obj: Any, key: str, _path: str = "") -> List[Tuple[str, Any]]:
    """DFS-поиск ключа ``key`` в произвольно вложенном dict/list.

    Возвращает список (путь, значение) ВСЕХ найденных вхождений — используется там,
    где контракт называет ИМЯ счётчика, но не место, где он живёт (см. докстринг
    класса ``TestShmCleanupFailureCounter`` ниже).
    """
    hits: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{_path}.{k}" if _path else str(k)
            if k == key:
                hits.append((p, v))
            hits.extend(_find_key(v, key, p))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hits.extend(_find_key(v, key, f"{_path}[{i}]"))
    return hits


def _isolated_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Обе ручки пары (см. ``log_paths.default_log_base_directory``) на ``tmp_path``.

    ``MULTIPROCESS_LOG_DIR`` СИЛЬНЕЕ ``INSPECTOR_LOG_DIR`` в резолве — ставим ОБЕ,
    иначе унаследованная из окружения первая ручка тихо перебила бы вторую и тест
    писал бы логи не туда, где их ищет assert.

    Заодно изолирует PID-реестр (``MULTIPROCESS_PID_FILE``/``INSPECTOR_PID_FILE``) на
    свой файл в ``tmp_path``: тесты этого файла зовут
    ``SystemLauncher._prepare_pid_registry()`` напрямую, а та БЕЗ этой изоляции читает
    и РЕАПИТ (убивает живые PID) реестр ПО УМОЛЧАНИЮ — общий на приложение, в системном
    temp. На машине разработчика в нём могут быть записи настоящего, вручную запущенного
    стенда — реап чужого живого реестра убил бы его процессы (см. Н-8 в памяти проекта).
    ``monkeypatch`` откатывает обе ручки автоматически после теста.
    """
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path))
    pid_file = str(tmp_path / "t12_pid_registry.jsonl")
    monkeypatch.setenv("MULTIPROCESS_PID_FILE", pid_file)
    monkeypatch.setenv("INSPECTOR_PID_FILE", pid_file)


def _leak_shm_segment(base_name: str) -> "shared_memory.SharedMemory":
    """Создать РЕАЛЬНЫЙ SHM-сегмент с именем ``{base_name}_0`` и НЕ закрыть его —
    имитация «предыдущий запуск не отработал cleanup» без падения дочернего процесса.

    Тот же процесс может открыть свой собственный созданный сегмент заново (и
    Windows, и POSIX) — поднимать настоящий дочерний процесс не нужно.
    """
    return shared_memory.SharedMemory(name=f"{base_name}_0", create=True, size=64)


def _release(shm: "shared_memory.SharedMemory") -> None:
    try:
        shm.close()
    except Exception:  # noqa: BLE001 — тест не должен упасть на teardown
        pass
    try:
        shm.unlink()  # Windows: no-op; POSIX: реально освобождает
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Критерий 1: launcher/messages.log содержит "cleanup_stale_shm: очищено N"
# (до Task 3.2 — system.log; решение Р-7(а) увело INFO в messages.log)
# ---------------------------------------------------------------------------


class TestLauncherShmCleanupMessageReachesAFile:
    """Акцептанс: сообщение об очистке устаревшего SHM (буквальный текст критерия
    ``cleanup_stale_shm: очищено N``) обязано лечь в ``{log_root}/launcher/messages.log``.

    Адрес файла сменился в Task 3.2 (решение владельца Р-7(а)): скоуп ``BUSINESS``
    перестал писать в ``system_file``, а ``_LEVEL_DEFAULT_SCOPE`` отображает
    ``INFO -> BUSINESS``. Литерал критерия НЕ менялся — сменился только файл.

    Сегодня НЕ ложится по ДВУМ независимым причинам сразу: (а) у лончера нет
    привязанного ``LoggerManager`` — записи через ``FallbackLogger`` уходят в
    stdlib-фолбэк, а не в файл процесса; (б) даже если бы уходили, реально вызываемая
    сегодня функция очистки (``memory/platform/shm.py::cleanup_stale_shm``) вообще
    ничего не логирует — это НЕ та функция, что несёт литерал критерия
    (``buffers/cleanup.py::cleanup_stale_shm`` несёт его, но сегодня не вызывается
    из ``SystemLauncher._cleanup_shm_at_startup`` вовсе).
    """

    def test_cleanup_message_with_a_number_reaches_launcher_messages_log(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolated_log_dir(monkeypatch, tmp_path)

        # Короткое уникальное имя — под лимитом macOS PSHMNAMLEN (см. shm.py, H3),
        # хотя стенд здесь Windows: лимит соблюдён с запасом на будущее.
        region_name = f"t1{uuid.uuid4().hex[:8]}"
        leaked = _leak_shm_segment(region_name)
        try:
            processes_config: Dict[str, Any] = {
                "probe_proc": {"memory": {"names": {region_name: (1, 1, 1)}, "coll": 1}}
            }
            launcher = SystemLauncher()
            launcher._prepare_pid_registry()
            launcher._cleanup_shm_at_startup(processes_config)

            log_file = tmp_path / "launcher" / "messages.log"
            assert log_file.exists(), (
                f"launcher/messages.log не создан ({tmp_path}) — записи лончера по-прежнему никуда не попадают"
            )
            content = log_file.read_text(encoding="utf-8", errors="replace")
            assert re.search(r"cleanup_stale_shm: очищено \d+", content), (
                "в launcher/messages.log нет строки вида 'cleanup_stale_shm: очищено N' "
                f"(литерал критерия). Содержимое файла:\n{content}"
            )
        finally:
            _release(leaked)


# ---------------------------------------------------------------------------
# Критерий 4: сбой очистки SHM громкий — errors.log с traceback + счётчик
# ---------------------------------------------------------------------------


class TestShmCleanupFailureReachesErrorsLog:
    """Акцептанс: сбой очистки (``e.g. a nonexistent path``) обязан дать ERROR с
    traceback в ``{log_root}/launcher/errors.log``.

    Инъекция сбоя — ``monkeypatch`` на ``cleanup_known_shm_at_startup`` (реально
    вызываемую сегодня функцию), поднимающий ``RuntimeError`` с уникальной меткой.
    Это не «подмена ради зелёного», а стандартная инъекция отказа — тот же приём,
    которым описан сценарий критерия («нет такого пути»).

    Сегодня — красный: голый ``except Exception: pass`` в
    ``SystemLauncher._cleanup_shm_at_startup`` глушит исключение целиком, ни один
    файл не появляется.
    """

    def test_failure_with_traceback_reaches_launcher_errors_log(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolated_log_dir(monkeypatch, tmp_path)

        failure_marker = f"SIMULATED nonexistent path failure {uuid.uuid4().hex[:8]}"

        def _raise(*_a: Any, **_kw: Any) -> None:
            raise RuntimeError(failure_marker)

        monkeypatch.setattr(
            "multiprocess_framework.modules.shared_resources_module.memory.platform.cleanup_known_shm_at_startup",
            _raise,
        )

        launcher = SystemLauncher()
        launcher._prepare_pid_registry()
        launcher._cleanup_shm_at_startup({"probe_proc": {"memory": {"names": {"x": (1, 1, 1)}, "coll": 1}}})

        errors_log = tmp_path / "launcher" / "errors.log"
        assert errors_log.exists(), (
            f"launcher/errors.log не создан при сбое очистки SHM ({tmp_path}) — отказ по-прежнему проглочен молча"
        )
        content = errors_log.read_text(encoding="utf-8", errors="replace")
        assert failure_marker in content, f"errors.log не содержит текста инъецированного сбоя:\n{content}"
        assert "Traceback" in content, f"errors.log не содержит traceback:\n{content}"


class TestShmCleanupFailureCounter:
    """Акцептанс: счётчик ``shm_cleanup_failures`` становится ``1`` при сбое очистки.

    **Группа счётчика не названа критерием** («which counter group it lives in is
    for you to determine»). У ``SystemLauncher`` (объект лончера, ДО существования
    хоть одного процесса) есть РОВНО два публичных метода, отдающих состояние:
    ``get_status()`` и ``get_stats()`` — оба уже существуют сегодня и оба СЕГОДНЯ
    ничего про SHM не знают. Тест ищет ключ ``shm_cleanup_failures`` ДФС-обходом по
    ОБОИМ, а не в заранее угаданном месте — так тест не привязан к конкретной
    вложенности и не сломается на верном ответе в неожиданном месте.

    **Это САМЫЙ ненадёжный тест файла** (см. отчёт координатору, раздел про
    незакрытое): оба метода сегодня рано выходят по ветке ``if not self._spawner``,
    а в этом тесте spawner не создаётся вовсе (``_cleanup_shm_at_startup`` вызван
    напрямую, до ``_create_spawner()``) — если фикс кладёт счётчик в структуру,
    доступную ТОЛЬКО после появления spawner'а, тест останется красным и после
    верной реализации. Проверить это без чтения реализации я не могу.
    """

    def test_shm_cleanup_failures_counter_becomes_one_somewhere_reachable(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _isolated_log_dir(monkeypatch, tmp_path)

        def _raise(*_a: Any, **_kw: Any) -> None:
            raise RuntimeError("SIMULATED nonexistent path failure for counter test")

        monkeypatch.setattr(
            "multiprocess_framework.modules.shared_resources_module.memory.platform.cleanup_known_shm_at_startup",
            _raise,
        )

        launcher = SystemLauncher()
        launcher._prepare_pid_registry()
        launcher._cleanup_shm_at_startup({"probe_proc": {"memory": {"names": {"x": (1, 1, 1)}, "coll": 1}}})

        status = launcher.get_status()
        stats = launcher.get_stats()
        hits = _find_key(status, "shm_cleanup_failures") + _find_key(stats, "shm_cleanup_failures")

        assert hits, (
            "ни get_status(), ни get_stats() не содержат ключ 'shm_cleanup_failures' нигде во "
            f"вложенной структуре.\nget_status()={status!r}\nget_stats()={stats!r}"
        )
        assert any(value == 1 for _path, value in hits), f"shm_cleanup_failures найден, но не равен 1: {hits}"
