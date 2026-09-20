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

**Добор ревью задач 2.7/2.8 (Н-1, ``review-phase-1.md``).** Пара выше водит
ТОЛЬКО точку ``:402`` (``_prepare_pid_registry()``) — счётчик растёт ещё в ОДНОМ
месте, ``system_launcher.py:581``, внутри ``stop()`` на отказе ``pid_registry.clear()``.
Ревьюер поставил ложный инкремент СРАЗУ ПОСЛЕ успешного ``clear()`` в ``stop()`` —
и пара выше его не увидела: 0 красных из 1144. ``TestPidRegistryFailuresStopHalf``
ниже — недостающая половина именно для точки ``stop()``, тем же приёмом (заведомо
успешный путь, дельта счётчика обязана быть 0).

**Замыкатель класса (координатор, добор ревью Ф2, 2026-09-01).** Три пары выше
(``TestPidRegistryFailuresIsAPair`` + ``TestPidRegistryFailuresStopHalf``) закрывают
ДВЕ КОНКРЕТНЫЕ точки — но список точек был перечислен РУКАМИ, тем же приёмом,
которым ``_prepare_pid_registry`` когда-то был единственной. Появись ТРЕТЬЯ точка
инкремента (например, в будущем методе ``restart()``), она осталась бы
ненаблюдаемой до следующего ревью — тот же класс дефекта, что и у самой находки
Н-1. ``TestPidRegistryFailuresPairIsComputedNotEnumerated`` ниже заменяет ручной
список на AST-скан: охват «какие точки инкремента обязаны иметь парный успешный
сценарий» вычисляется из САМОГО КОДА ``SystemLauncher``, а не декларируется.
Новая точка, не заведённая в ``_SUCCESS_SCENARIOS``, валит
``test_every_increment_site_has_a_paired_success_scenario`` громко, вместо того
чтобы молчать.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from multiprocess_framework.modules.process_manager_module.launcher import (
    system_launcher as _system_launcher_module,
)
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


class TestPidRegistryFailuresStopHalf:
    """Вторая ТОЧКА того же счётчика: ``system_launcher.py:581`` внутри ``stop()``.

    Класс выше (``TestPidRegistryFailuresIsAPair``) гонит только ``_prepare_pid_registry()``
    (``:402``) — успешный ``stop()`` он не задевает вовсе, а именно там ревьюер
    доказал дыру заплаткой (Н-1, ``review-phase-1.md``): ложный инкремент СРАЗУ
    ПОСЛЕ успешного ``clear()`` внутри ``stop()`` прошёл 1144 теста без единого
    красного.
    """

    def test_a_successful_stop_leaves_the_counter_at_zero(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``stop()`` без spawner'а (реестр пуст, ``clear()`` тривиально успешен) —
        счётчик обязан остаться на 0. ``_spawner`` не задан нарочно: этот тест
        смотрит ИМЕННО на ветку успешной очистки реестра, а не на остановку
        дочерних процессов (та ветка вне области этой находки).
        """
        _isolated_pid_registry(monkeypatch, tmp_path)
        launcher = SystemLauncher()

        launcher.stop()

        assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
            "pid_registry_failures вырос на успешном stop() — вторая половина "
            "пары (точка :581, а не :402), которой не было по находке Н-1"
        )

    def test_successful_stops_in_a_row_leave_the_counter_at_zero(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Симметрично первому классу: N успешных ``stop()`` подряд не имеют
        права тронуть счётчик. ``stop()`` документирован как идемпотентный
        (``_shutdown_observability``) — повторный вызов не должен ронять тест.
        """
        _isolated_pid_registry(monkeypatch, tmp_path)
        launcher = SystemLauncher()

        n_attempts = 3
        for i in range(n_attempts):
            launcher.stop()
            assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
                f"pid_registry_failures вырос на успешном stop() №{i + 1}"
            )


def _find_counter_increment_sites(module: object, class_name: str, attr_name: str) -> dict[str, int]:
    """AST-скан: все ``self.<attr_name> += N`` внутри методов класса ``class_name``.

    Возвращает ``{имя_метода: номер_строки}``. Источник охвата — САМ КОД, а не
    список, который кто-то поддерживает руками, — новая точка инкремента попадёт
    в результат сама, без правки этого сканера.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    sites: dict[str, int] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            for child in ast.walk(item):
                if (
                    isinstance(child, ast.AugAssign)
                    and isinstance(child.target, ast.Attribute)
                    and child.target.attr == attr_name
                    and isinstance(child.target.value, ast.Name)
                    and child.target.value.id == "self"
                ):
                    sites[item.name] = child.lineno

    return sites


def _run_prepare_pid_registry_success(launcher: SystemLauncher) -> None:
    """Успешный сценарий для точки ``_prepare_pid_registry``: пустой реестр,
    реап тривиально успешен (тот же приём, что в ``TestPidRegistryFailuresIsAPair``)."""
    launcher._prepare_pid_registry()


def _run_stop_success(launcher: SystemLauncher) -> None:
    """Успешный сценарий для точки ``stop``: без spawner'а, ``clear()`` тривиально
    успешен (тот же приём, что в ``TestPidRegistryFailuresStopHalf``)."""
    launcher.stop()


class TestPidRegistryFailuresPairIsComputedNotEnumerated:
    """Охват «какие точки инкремента обязаны иметь парный успешный сценарий»
    вычисляется AST-сканом ``SystemLauncher``, а не перечисляется руками.

    Ручной список (``TestPidRegistryFailuresIsAPair`` + ``TestPidRegistryFailuresStopHalf``
    выше) был написан ПОСЛЕ того, как ревью нашло вторую точку постфактум — то
    есть тем же способом, которым была пропущена третья. Этот класс переворачивает
    порядок: сначала сканируется код на предмет ВСЕХ точек инкремента, потом
    список сверяется с реестром сценариев. Новая точка без сценария роняет
    ``test_every_increment_site_has_a_paired_success_scenario`` — сразу, а не на
    следующем ревью.
    """

    #: Карта «имя метода → успешный сценарий». Ручной список ЗДЕСЬ законен: это
    #: не перечень точек (тот вычисляется сканом), а перечень СЦЕНАРИЕВ для уже
    #: найденных точек — сценарий обязан знать специфику метода (что считается
    #: «успехом» для конкретно этого пути), автоматически его не вывести.
    _SUCCESS_SCENARIOS = {
        "_prepare_pid_registry": _run_prepare_pid_registry_success,
        "stop": _run_stop_success,
    }

    def test_every_increment_site_has_a_paired_success_scenario(self) -> None:
        sites = _find_counter_increment_sites(_system_launcher_module, "SystemLauncher", "_pid_registry_failures")

        assert sites, (
            "AST-скан не нашёл НИ ОДНОЙ точки инкремента pid_registry_failures в "
            "SystemLauncher — подозрительно пусто, вероятно сканер сломан, а не "
            "находка чиста (ожидались как минимум _prepare_pid_registry и stop)"
        )

        missing = sorted(set(sites) - set(self._SUCCESS_SCENARIOS))
        assert missing == [], (
            "новая точка инкремента pid_registry_failures без парного успешного "
            f"сценария: {[(m, sites[m]) for m in missing]} — допишите сценарий в "
            "_SUCCESS_SCENARIOS (или объясните письменно, почему у этой точки "
            "пары не может быть)"
        )

    @pytest.mark.parametrize("method_name", sorted(_SUCCESS_SCENARIOS))
    def test_the_paired_success_scenario_leaves_the_counter_at_zero(
        self, method_name: str, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сама пара: у каждой известной точки — сценарий, оставляющий счётчик на 0.

        Параметризация читает ``_SUCCESS_SCENARIOS`` (а не сайты скана напрямую):
        сайты называют МЕСТО, сценарии — ПОВЕДЕНИЕ; смешивать их значило бы
        требовать от скана знать, как выглядит успех произвольного метода.
        """
        _isolated_pid_registry(monkeypatch, tmp_path)
        launcher = SystemLauncher()

        self._SUCCESS_SCENARIOS[method_name](launcher)

        assert launcher.get_stats()["startup"]["pid_registry_failures"] == 0, (
            f"pid_registry_failures вырос на успешном сценарии точки {method_name!r}"
        )
