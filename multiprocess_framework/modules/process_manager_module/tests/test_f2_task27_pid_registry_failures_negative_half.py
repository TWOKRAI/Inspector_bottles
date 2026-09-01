# -*- coding: utf-8 -*-
"""Task 2.7 плана observability-closure (добор ревью Ф1) — независимый тестер.

Критерий приёмки 1, вторая половина (текст задачи, передан координатором; план
``phase-2-one-policy.md`` и реализация мне не показаны):

    «Пара на pid_registry_failures: тест "реап реально провалился → счётчик вырос
    на литерал" И тест "серия УСПЕШНЫХ реапов → дельта == 0". Второй — тот,
    которого не было.»

Первая половина пары уже существует и зелёная —
``test_launcher_startup_observability_acceptance.py`` не покрывает её напрямую
(``pid_registry_failures`` там не упомянут), но АВТОРСКИЙ hazard-тест
``test_launcher_observability_hazards.py::TestPidRegistryFailureHasAVoice::
test_a_failed_reap_is_counted_and_told`` покрывает: инъекция сбоя ``reap_and_reset``
→ ``pid_registry_failures == 1``. Этот файл добавляет ИМЕННО отсутствовавшую
половину: серия УСПЕШНЫХ ``SystemLauncher._prepare_pid_registry()`` не имеет права
тронуть ``pid_registry_failures``.

**Дисклеймер по красноте.** Ревью Ф1 (``review-phase-1.md``, находка 1)
воспроизвело отсутствие этой половины ЗАПЛАТКОЙ (throwaway pytest-плагин,
инкремент счётчика при успешном реапе — ``894 passed`` без единого красного и без
заплатки же). Прочитанный код (``launcher/system_launcher.py::_prepare_pid_registry``)
растит ``self._pid_registry_failures`` СТРОГО внутри ``except Exception as exc:`` —
и это внешнее исключение самого ``_prepare_pid_registry``, а не любой отказ
ВНУТРИ ``reap_and_reset``/``_reap_file`` (та функция сама глушит свои отказы —
см. докстринг ``SystemLauncher.stop()``: «САМА ``clear()`` о своих отказах не
рассказывает — она глушит их внутри»). При пустом PID-файле ``reap_and_reset``
не убивает никого (``killed == 0``) и не бросает исключений — то есть уже
сегодня, без единой правки реализации, серия успешных реапов не имеет шанса
тронуть счётчик. Тест ниже поэтому ожидаемо ЗЕЛЁН на этом коммите (0b2d5b15):
закрывает пробел в ТЕСТАХ, а не создаёт ТЗ для новой реализации. Зелёный
результат назван в отчёте координатору отдельно, не спрятан.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
    SystemLauncher,
)


def _isolated_pid_registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Обе ручки пары (``MULTIPROCESS_PID_FILE`` сильнее ``INSPECTOR_PID_FILE``) на
    свой файл в ``tmp_path``. Без изоляции ``_prepare_pid_registry()`` реапнул бы
    БОЕВОЙ реестр по умолчанию (общий на приложение, в системном temp) — см. Н-8 в
    памяти проекта: убил бы живые процессы вручную запущенного стенда.
    """
    pid_file = str(tmp_path / "t27_pid_registry.jsonl")
    monkeypatch.setenv("MULTIPROCESS_PID_FILE", pid_file)
    monkeypatch.setenv("INSPECTOR_PID_FILE", pid_file)


class TestPidRegistryFailuresIsAPair:
    """Правило проекта: у диагностического счётчика — ОБЕ половины пары."""

    def test_successful_reaps_in_a_row_leave_the_counter_at_zero(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ложноположительная половина: N успешных ``_prepare_pid_registry()`` → дельта 0.

        Реестр пуст на каждом вызове (никто ничего не осиротил) — реап тривиально
        успешен по построению, ни один из N вызовов не имеет права его тронуть.
        """
        _isolated_pid_registry(monkeypatch, tmp_path)
        launcher = SystemLauncher()

        n_attempts = 5
        for i in range(n_attempts):
            launcher._prepare_pid_registry()
            assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
                f"pid_registry_failures вырос на успешном реапе №{i + 1} — "
                f"ложноположительная половина пары (та, которой не было по находке ревью Ф1)"
            )

        assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
            f"после {n_attempts} успешных реапов подряд счётчик не равен 0: "
            f"{launcher.get_stats()['startup']['pid_registry_failures']}"
        )

    def test_a_successful_reap_that_actually_kills_a_stale_pid_still_leaves_it_at_zero(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Тот же факт, но реестр НЕ пуст: одна протухшая (несуществующий PID) запись —
        ``reap_and_reset`` реально работает (читает файл, пробует психов), а не просто
        видит пустой файл и рано выходит. Это иначе исполняемая ветка кода, и пара
        из одного пустого реестра её не покрывает.
        """
        _isolated_pid_registry(monkeypatch, tmp_path)
        pid_file = tmp_path / "t27_pid_registry.jsonl"
        # PID, которого почти наверняка не существует, плюс create_time, который не
        # совпадёт ни с одним живым процессом — reap_and_reset должен пропустить его
        # тихо (не найден психом), но выполнить полный проход по файлу.
        pid_file.write_text('{"pid": 999999, "ct": 1.0}\n', encoding="utf-8")

        launcher = SystemLauncher()
        launcher._prepare_pid_registry()

        assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
            "pid_registry_failures вырос на реапе НЕпустого, но не давшего исключения реестра"
        )
