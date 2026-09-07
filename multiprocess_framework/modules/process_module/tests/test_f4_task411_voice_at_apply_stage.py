# -*- coding: utf-8 -*-
"""Task 4.11 (independent tester, RED-до-реализации): голос ADR-PM-046 переезжает
со стадии «разбор» на стадию «применяю»; аварийный выход вычищен из позиций,
адресованных ОПЕРАТОРУ.

**Реализации ещё нет.** Тесты пишутся ПО КРИТЕРИЯМ приёмки плана
(``plans/observability-closure/phase-4-scale-and-form.md``, Task 4.11), без
чтения diff'а/`_impl/`. Запрещённые файлы (тесты задачи 2.12, закрепляющие
СТАРУЮ модель «окно считает разборы») НЕ читались.

Сегодняшнее (дефектное) поведение измерено живым прогоном ДО написания этого
файла (харнесс ниже, три ``config.reload`` подряд):

    windowed_suppressed после 1-го reload:  5
    windowed_suppressed после 2-го reload: 11
    windowed_suppressed после 3-го reload: 17

Это ровно шесть разборов на reload (три стадии команды × два ``model_validate``
на стадию), совпадает с докстрингом валидатора дословно. Задача 4.11 обязана
превратить «17» в «2» (два ДЕЙСТВИЯ оператора, подавленных после первого), не
трогая при этом «сколько строк лежит в файле» (это уже 1 — окно Task 2.12).

Критерии приёмки (план, дан текстом, не выведен из кода):

  1. Один ``config.reload`` со ``stats.enabled: false`` → РОВНО 1 голос.
  2. Три ``config.reload`` подряд за одно окно → «подавлено» называет 2, не 17.
  3. Голос читается ИЗ ФАЙЛА журнала настоящего ``LoggerManager`` (золотой путь).
  4. Boot со старым конфигом: голос в файле, число названо; между процессами
     окно не работает по построению — это не дефект.
  5. Ноль ``emergency_log`` в позиции «сообщение ОПЕРАТОРУ» (посчитано AST/грепом).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    reset_process_voices,
    reset_voice_counters,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

#: Корень репозитория — ЭТОГО worktree (файл лежит внутри него), не главного дерева.
REPO_ROOT = Path(__file__).resolve().parents[4]

#: Маркер строки голоса ADR-PM-046 — стабильнее полного текста (переживёт правку
#: формулировки), но не настолько общий, чтобы ловить чужие WARNING.
_VOICE_MARKER = "ADR-PM-046"


# ---------------------------------------------------------------------------
# Харнесс: настоящий ProcessModule + настоящий LoggerManager + настоящий
# config.reload через BuiltinCommands. Архитектура — та же, что уже проверена
# боевым концом в test_flight_recorder_real_wiring.py (не форбидден, публичная
# часть тестовой базы): минимальный набор менеджеров, при котором IPC-команда
# доезжает до `_cmd_config_reload` → `apply_observability_layers` →
# `compose_managers_payload` → `expand_observability` → `model_validate`.
# stats/error-менеджеры НЕ нужны — `_cmd_config_reload` читает их через
# `getattr(svc, "...", None)` и безопасно пропускает отсутствующие.
# ---------------------------------------------------------------------------


class _Cm:
    """Двойник реестра команд — то же, что `CommandManager` для регистрации."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name: str, handler: Any, metadata: Any = None, tags: Any = None) -> None:
        self.handlers[name] = handler


def _boot(tmp_path: Path, name: str) -> Tuple[ProcessModule, LoggerManager, Any]:
    """Поднять минимальный, но НАСТОЯЩИЙ процесс с файловым логгером и config.reload."""
    proc = ProcessModule(name, config={})
    logger_cfg = LoggerManagerConfig(app_name=name, log_directory=str(tmp_path))
    logger = LoggerManager(manager_name=f"{name}Logger", config=logger_cfg, process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc.command_manager = _Cm()
    proc._wire_observability_hub()
    BuiltinCommands(proc).register()
    handler = proc.command_manager.handlers["config.reload"]
    return proc, logger, handler


def _system_log_path(tmp_path: Path, name: str) -> Path:
    # LoggerCore кладёт файловые каналы под подкаталогом ИМЕНИ процесса —
    # измерено спайком ДО написания тестов (`tmp_path/<name>/system.log`).
    return tmp_path / name / "system.log"


def _read_log(tmp_path: Path, name: str) -> str:
    path = _system_log_path(tmp_path, name)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _voice_lines(text: str) -> list:
    return [ln for ln in text.splitlines() if _VOICE_MARKER in ln]


@pytest.fixture(autouse=True)
def _isolated_voice_window() -> Iterator[None]:
    """Каждый тест — свой процессный держатель окна и обнулённые счётчики.

    ``_PROCESS_VOICES``/``_totals`` в ``windowed_voice`` — процессные singleton'ы
    (см. докстринг модуля); без сброса тест унаследовал бы состояние соседа по
    сьюте, и число перестало бы быть литералом (найдено соседним тестом
    ``test_windowed_suppressed_readback_acceptance.py``, тот же приём).
    """
    reset_process_voices()
    reset_voice_counters()
    yield
    reset_process_voices()
    reset_voice_counters()


@pytest.fixture(autouse=True)
def _log_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``config.reload`` берёт каталог логов из МАШИННОГО контекста (env), не из
    аргумента команды (``resolve_base_log_dir``) — без этого голос уехал бы в
    системный temp процесса, а не в файл, который читает тест (измерено спайком:
    без переменной окружения запись уходила в
    ``%LOCALAPPDATA%/Temp/multiprocess_framework/logs``, а не в ``tmp_path``).
    """
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)


# ---------------------------------------------------------------------------
# Критерий 1 (+3, золотой путь): один config.reload -> ровно 1 голос в файле.
# ---------------------------------------------------------------------------


class TestSingleActionVoicesExactlyOnce:
    """Критерий 1 — первая половина, и одновременно золотой путь критерия 3.

    Уже держится СЕГОДНЯ окном Task 2.12: шесть разборов ОДНОГО reload
    (три стадии команды × два ``model_validate``) попадают в одно окно и
    схлопываются в одну запись. Это БАЗОВЫЙ инвариант, который 4.11 обязана НЕ
    сломать при переезде голоса на стадию «применяю». Зелёный тест здесь ДО
    реализации — не вакуум: он читает НАСТОЯЩИЙ файл настоящего LoggerManager
    и считает НАСТОЯЩИЕ строки; сегодняшний механизм уже даёт верный ответ
    именно на ЭТОТ вопрос («сколько строк») — дефект в ДРУГОМ числе
    («сколько подавлено»), это проверяет соседний класс.
    """

    def test_one_reload_writes_exactly_one_voice_line_in_the_real_log_file(self, tmp_path: Path) -> None:
        proc, logger, handler = _boot(tmp_path, "single_action")
        try:
            result = handler({"observability": {"stats": {"enabled": False}}})
            assert result["success"] is True

            lines = _voice_lines(_read_log(tmp_path, "single_action"))
            assert len(lines) == 1, (
                f"один config.reload обязан дать РОВНО один голос в файле журнала, найдено {len(lines)}: {lines!r}"
            )
        finally:
            logger.shutdown()

    def test_enabled_true_does_not_voice_at_all_reachability_control(self, tmp_path: Path) -> None:
        """Парная проверка достижимости: без ``enabled: false`` дорога МОЛЧИТ.

        Без этого контроля предыдущий тест доказывал бы только «в файле есть
        хоть что-то», а не что строка адресована именно правилу ADR-PM-046.
        """
        proc, logger, handler = _boot(tmp_path, "single_action_control")
        try:
            result = handler({"observability": {"stats": {"enabled": True}}})
            assert result["success"] is True

            text = _read_log(tmp_path, "single_action_control")
            assert _VOICE_MARKER not in text, "enabled: true — предупреждать не о чем, дорога обязана молчать"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 2 — ядро задачи: подавлено считает ДЕЙСТВИЯ, а не РАЗБОРЫ.
# ---------------------------------------------------------------------------


class TestSuppressedCountsActionsNotParses:
    """Три ``config.reload`` подряд внутри одного окна → подавлено = 2, не 17.

    Наблюдаемая величина — ``windowed_suppressed`` из readback ``LoggerManager``
    (``get_stats()``, тот же путь, что боевым концом проверил
    ``test_windowed_suppressed_readback_acceptance.py``) — а НЕ текст
    «подавлено с прошлой записи: N» внутри самой строки журнала: этот текст
    показывается только СЛЕДУЮЩИМ голосом, то есть только после истечения окна
    (по умолчанию 5 секунд), и ждать его в юнит-тесте значило бы завести
    «порог по часам меряет кучу» — ровно то, что правило проекта просит не
    делать. Счётчик процессный (сумма по ВСЕМ ключам), поэтому тест снимает
    БАЗОВУЮ линию сразу после boot и судит ДЕЛЬТУ, а не абсолютное значение.

    Число «17» ниже — не домысел: это измеренный текущий результат (см.
    докстринг файла), контрольная величина ПЕРЕД тем, как писать тест.
    """

    def test_three_reloads_report_two_suppressed_not_seventeen(self, tmp_path: Path) -> None:
        proc, logger, handler = _boot(tmp_path, "triple_action")
        try:
            baseline = logger.get_stats().get("windowed_suppressed", 0)

            for _ in range(3):
                result = handler({"observability": {"stats": {"enabled": False}}})
                assert result["success"] is True

            delta = logger.get_stats()["windowed_suppressed"] - baseline
            assert delta == 2, (
                "три ДЕЙСТВИЯ оператора внутри одного окна обязаны подавить ровно ДВА "
                f"следующих действия (действия, а не разборы секции); получено {delta}"
            )
        finally:
            logger.shutdown()

    def test_three_reloads_still_write_only_one_line_defects_are_independent(self, tmp_path: Path) -> None:
        """Контроль независимости дефектов: плохой счётчик ≠ дублирующиеся строки.

        Сегодняшний механизм уже не пишет вторую строку в окне — ломается
        именно счётчик «подавлено». Если это перестанет быть так, дефект
        сменил класс, и об этом стоит узнать отдельно от критерия 2.
        """
        proc, logger, handler = _boot(tmp_path, "triple_action_lines")
        try:
            for _ in range(3):
                handler({"observability": {"stats": {"enabled": False}}})

            lines = _voice_lines(_read_log(tmp_path, "triple_action_lines"))
            assert len(lines) == 1, f"окно уже не даёт дублей строк — если это изменилось, дефект другой: {lines!r}"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 4 — дорога BOOT (не только reload), и независимость окна между
# процессами (не дефект, а следствие устройства — сказано вслух явным тестом).
# ---------------------------------------------------------------------------


class TestBootRoadVoicesTheSameWayAsReload:
    """``apply_observability_layers`` — ЕДИНАЯ функция применения (её собственный
    докстринг: «И hot-reload watcher, и IPC-команда config.reload зовут именно
    её») — ``process_managers.py`` (дорога boot) зовёт ТУ ЖЕ функцию. Тест зовёт
    её напрямую с ``origin="boot:layers"`` и слоем L1, заполненным ДО вызова —
    минимальный воспроизводимый эквивалент «прототип поднялся со старым
    конфигом», без веса полного ``_apply_boot_observability_layers`` (тому
    нужен настоящий ``config_handler``/``ConfigStore``, не относящийся к предмету
    проверки).
    """

    def test_boot_road_voices_once_and_names_zero_suppressed(self, tmp_path: Path) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            LAYER_APP,
            process_observability_layers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )

        proc, logger, _handler = _boot(tmp_path, "boot_road")
        try:
            layers = process_observability_layers(proc)
            layers.replace_layer(LAYER_APP, {"stats": {"enabled": False}}, source="boot", origin="boot:layers")

            apply_observability_layers(
                layers,
                logger=proc.logger_manager,
                error=None,
                stats=None,
                log_info=getattr(proc, "_log_info", None),
                origin="boot:layers",
            )

            lines = _voice_lines(_read_log(tmp_path, "boot_road"))
            assert len(lines) == 1, (
                "boot с унаследованным конфигом обязан голосить — дорога та же apply_observability_layers"
            )
            assert "подавлено" not in lines[0], (
                "первый голос процесса ничего не подавлял до себя — число 0 словом не называется"
            )
        finally:
            logger.shutdown()


class TestWindowIsPerProcessByConstructionNotADefect:
    """Критерий 4, вторая половина — окно НЕ работает МЕЖДУ процессами, и это
    заявлено вслух как ОЖИДАЕМОЕ поведение, а не как дефект.

    ``_PROCESS_VOICES`` — держатель ПРОЦЕССА (module-level singleton в памяти
    интерпретатора). Два боевых процесса — два разных интерпретатора, делить
    состояние им физически нечем — граница ОС-процесса даёт изоляцию сама, без
    единой строчки кода. Внутри ОДНОГО pytest-процесса оба «boot» иначе делили
    бы ОДИН И ТОТ ЖЕ держатель, и тест проверял бы не то, поэтому
    ``reset_process_voices()`` между двумя boot'ами — честная эмуляция этой
    границы (в проде она происходит сама, здесь её приходится звать руками).
    """

    def test_two_independent_process_boots_each_get_their_own_voice(self, tmp_path: Path) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            LAYER_APP,
            process_observability_layers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )

        def _voice_once(name: str) -> None:
            proc, logger, _handler = _boot(tmp_path, name)
            try:
                layers = process_observability_layers(proc)
                layers.replace_layer(LAYER_APP, {"stats": {"enabled": False}}, source="boot", origin="boot:layers")
                apply_observability_layers(
                    layers, logger=proc.logger_manager, error=None, stats=None, origin="boot:layers"
                )
            finally:
                logger.shutdown()

        _voice_once("proc_a")
        reset_process_voices()  # граница ОС-процесса, эмулированная руками
        _voice_once("proc_b")

        lines_a = _voice_lines(_read_log(tmp_path, "proc_a"))
        lines_b = _voice_lines(_read_log(tmp_path, "proc_b"))
        assert len(lines_a) == 1 and len(lines_b) == 1, (
            "оба процесса обязаны получить СВОЙ голос — окно per-процесс, а не общее на систему "
            f"(proc_a={len(lines_a)}, proc_b={len(lines_b)})"
        )


# ---------------------------------------------------------------------------
# Критерий 5 — ноль emergency_log в позиции «сообщение ОПЕРАТОРУ».
# ---------------------------------------------------------------------------


class TestNoEmergencyLogInOperatorFacingPositions:
    """Инвентарь сверен грепом (сегодня, до реализации):

    * всего боевых вызовов ``emergency_log`` — 21 в 10 файлах;
    * в ошибочной позиции («сообщение ОПЕРАТОРУ», не самоотчёт сломавшегося
      маршрута) — 5, все три — в функциях ниже;
    * 4 пограничных (``observability_store.py`` — стор сам tap логгера, довод
      «рекурсия», решаются планом ОТДЕЛЬНО) — этот страж их НЕ трогает;
    * 12 законных (маршрут наблюдаемости сообщает о СОБСТВЕННОЙ поломке).

    Страж адресует функцию по ИМЕНИ через AST, не по номеру строки: номер
    сдвигается при любой соседней правке, а имя функции — то, что реально
    переносит решение «где стоит голос».
    """

    _TARGETS = (
        (Path("Services/documents/wiring.py"), "_migrate_auto_vacuum"),
        (Path("multiprocess_framework/modules/observability_declarations.py"), "_declare"),
        (
            Path("multiprocess_framework/modules/process_module/configs/observability_config.py"),
            "_complain_about_removed_batching_keys",
        ),
    )

    @staticmethod
    def _emergency_log_calls_in_function(path: Path, func_name: str) -> int:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        func = inner.func
                        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                        if name == "emergency_log":
                            calls += 1
        return calls

    @pytest.mark.parametrize("rel_path,func_name", _TARGETS)
    def test_operator_facing_function_has_zero_emergency_log_calls(self, rel_path: Path, func_name: str) -> None:
        full_path = REPO_ROOT / rel_path
        assert full_path.exists(), f"файл сместился, страж указывает не туда: {full_path}"
        count = self._emergency_log_calls_in_function(full_path, func_name)
        assert count == 0, (
            f"{func_name} в {rel_path} обязана перейти на ВИД (FallbackLogger) — это адрес "
            f"ОПЕРАТОРУ, а не самоотчёт сломавшегося маршрута; найдено {count} вызов(ов)"
        )

    def test_scanner_reachability_control_still_finds_a_real_call_elsewhere(self) -> None:
        """Парная проверка достижимости AST-сканера самого по себе.

        Пограничная функция (``observability_store.py``) СЕГОДНЯ ещё содержит
        ``emergency_log`` — это ожидаемо (план решает её отдельно от этой
        задачи) и служит доказательством, что сканер вообще СПОСОБЕН найти
        вызов, если он есть — без этого нулевые результаты выше могли бы
        значить «сканер ничего не находит», а не «вызовов нет».
        """
        path = REPO_ROOT / "multiprocess_framework/modules/channel_routing_module/observability/observability_store.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "emergency_log")
                or getattr(node.func, "attr", None) == "emergency_log"
            )
            for node in ast.walk(tree)
        )
        assert found, "сканер обязан находить emergency_log там, где он реально есть (контроль достижимости)"
