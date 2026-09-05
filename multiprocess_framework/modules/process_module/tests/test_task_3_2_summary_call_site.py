# -*- coding: utf-8 -*-
"""Авторский hazard-тест Task 3.2 К2 — точка вызова в ``ProcessModule.run()``.

Независимые тесты тестера (``dispatch_module``/``command_module``,
``test_task_3_2_boot_chatter.py``, классы ``TestK2…``) зовут
``log_registration_summary()`` НАПРЯМУЮ на менеджере — они доказывают, что
метод существует и говорит литеральное число, но НЕ видят, действительно ли
``ProcessModule.run()`` этот метод вызывает. Вердикт CTO прямо предсказал:
удалить вызов из ``run()`` — и тесты тестера дадут **0 красных**. Этот файл
закрывает именно эту дыру: свойство точки вызова, а не свойство метода.

Два теста:

* ``TestK2SummaryCallSiteInRun`` — обязательный hazard-тест (условие 3
  вердикта CTO): после ``run()`` сводка эмитится РОВНО один раз, и число в
  её тексте равно НЕЗАВИСИМО посчитанному числу построчных DEBUG-строк
  регистрации, пойманных в ТОМ ЖЕ прогоне. Это два независимых голоса
  одного факта — ни один не выведен из ``len()`` таблицы диспетчера,
  которая и есть предмет проверки.
* ``TestK2MissingSummaryMethodWarnsInsteadOfCrashing`` — условие 2 вердикта
  CTO: фейковый ``command_manager`` без ``log_registration_summary()``
  (таких в ``process_module/tests/`` 32 файла с собственным
  ``register_command``, посчитано грепом) не должен уронить ``run()``
  через ``AttributeError`` — отсутствие метода обязано быть посчитано и
  предупреждено (WARNING с именем объекта), а не проглочено молча.

Процесс поднимается ЦЕЛИКОМ (``initialize()`` + ``run()`` с мок
``shared_resources``) — тот же паттерн, что уже используется в
``test_process_lifecycle.py::TestBuiltinCommandsReachableViaCommandManager``
для того же файла ``run()``: поднять fake-процесс дешевле, чем городить
собственный харнесс, а свойство («сводка = независимый счёт DEBUG-строк»)
без реального ``CommandManager``+``Dispatcher`` не проверить — начинка
таблицы должна быть настоящей.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import Mock

from multiprocess_framework.modules.process_module import ProcessModule


def _resolve(msg: Any) -> str:
    """Превратить сообщение (готовая строка ИЛИ Ф1.4-``callable``) в текст."""
    return msg() if callable(msg) else msg


def make_mock_shared_resources():
    """Мок ``shared_resources``, совместимый с ``ISharedResources`` (как в
    ``test_process_lifecycle.py``) — даёт ``ProcessModule.initialize()``
    пройти до конца и построить РЕАЛЬНЫЙ ``CommandManager``.
    """
    sr = Mock()
    sr.get_process_data = Mock(return_value=None)
    sr.queue_registry = None
    sr.memory_manager = None
    sr.event_manager = Mock()
    sr.event_manager.set_router_manager = Mock()
    sr.process_state_registry = Mock()
    sr.process_state_registry.get_process_names = Mock(return_value=[])
    sr.process_state_registry.register_process = Mock(return_value=True)
    sr.process_state_registry.update_state = Mock(return_value=True)
    return sr


class TestK2SummaryCallSiteInRun:
    """Обязательный hazard-тест (условие 3 вердикта CTO)."""

    def test_summary_count_matches_independently_counted_debug_lines(self) -> None:
        sr = make_mock_shared_resources()
        # Имя БЕЗ цифр: CommandManager.manager_name == process.name (см.
        # process_managers.py:442..443) и попадает в текст сводки — цифра
        # в имени спутала бы regex, вытаскивающий число сводки ниже.
        process = ProcessModule("summary_call_site", shared_resources=sr, config={})
        assert process.initialize() is True, "предусловие: initialize() обязан пройти на пустом конфиге"

        cm = process.command_manager
        assert cm is not None, "предусловие: initialize() обязан построить настоящий CommandManager"

        # Базовая линия ДО run(): initialize() уже регистрирует часть команд
        # (шаг 6 — коннектор статистики: flush_stats/get_metric/get_metrics/
        # reset_metrics/stats_snapshot, воспроизведено отдельным замером —
        # 5 команд на пустом config={}). Сводка — снимок ВСЕЙ таблицы на
        # момент вызова, а не только батча run(), поэтому независимая сверка
        # обязана сравнивать ДЕЛЬТУ счёта с числом DEBUG-строк, пойманных
        # именно за run(), а не абсолютный счёт с абсолютным.
        baseline_count = len(cm.get_commands())

        info_calls: list = []
        debug_calls: list = []
        # Полная замена (не forwarding-спай): у логирования здесь нет
        # побочных эффектов, от которых зависела бы регистрация команд.
        cm._log_info = lambda msg, **kw: info_calls.append(_resolve(msg))
        cm._log_debug = lambda msg, **kw: debug_calls.append(_resolve(msg))

        process.run()  # <-- проверяемая точка вызова (process_module.py, run())

        # Снимок СРАЗУ после run(), ДО shutdown(): CommandManager.shutdown()
        # тоже зовёт cm._log_info(f"CommandManager '...' shutdown completed")
        # — эта строка не имеет отношения к сводке регистрации и не должна
        # попасть в счёт "ровно одна INFO-строка".
        info_snapshot = list(info_calls)
        debug_snapshot = list(debug_calls)
        process.shutdown()

        assert len(info_snapshot) == 1, (
            "К2 нарушен НА ТОЧКЕ ВЫЗОВА: ProcessModule.run() обязан позвать "
            f"CommandManager.log_registration_summary() РОВНО один раз, поймано "
            f"{len(info_snapshot)}: {info_snapshot!r}"
        )
        summary_text = info_snapshot[0]
        match = re.search(r"\d+", summary_text)
        assert match, f"сводка обязана называть число: {summary_text!r}"
        summary_count = int(match.group())

        per_key_lines = [t for t in debug_snapshot if re.fullmatch(r"Command '.*' registered successfully", t)]
        # Анкор существования (правило проекта: негативное/производное
        # утверждение без якоря существования вырождается в проверку на
        # пустом множестве) — без него "0 == 0" молча прошло бы и в случае,
        # когда builtin-команды вообще не зарегистрировались.
        assert per_key_lines, (
            "анкор существования не выполнен: ни одной построчной DEBUG-строки "
            "регистрации не поймано — сводку не с чем сверять"
        )
        delta = summary_count - baseline_count
        assert delta == len(per_key_lines), (
            f"число в сводке ({summary_count}) минус базовая линия до run() "
            f"({baseline_count}) = {delta}, что разошлось с независимо посчитанными "
            f"построчными DEBUG-строками за run() ({len(per_key_lines)}) — два голоса "
            f"одного факта обязаны совпасть"
        )


class TestK2MissingSummaryMethodWarnsInsteadOfCrashing:
    """Условие 2 вердикта CTO: отсутствие метода посчитано и предупреждено,
    не проглочено молча (``except: pass``) и не фатально (``AttributeError``
    наружу). ~32 файла в ``process_module/tests/`` определяют собственный
    ``register_command`` без ``log_registration_summary()`` (посчитано
    ``grep -c "def register_command" process_module/tests``); голый вызов
    без гварда уронил бы ЛЮБОЙ тест, который довёл бы такой фейк до
    ``ProcessModule.run()``.
    """

    class _FakeCommandManagerWithoutSummary:
        """Минимальный фейк старого контракта CommandManager — без К2-метода."""

        def register_command(self, *args, **kwargs) -> bool:
            return True

    def test_missing_method_logs_a_warning_and_run_completes(self) -> None:
        process = ProcessModule("summary_guard")
        process.worker_manager = Mock()
        process.update_process_state = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)
        process.command_manager = self._FakeCommandManagerWithoutSummary()

        warnings: list = []
        process._log_warning = lambda msg, **kw: warnings.append(_resolve(msg))

        process.run()  # НЕ должен уронить AttributeError
        process.stop()

        assert warnings, "К2-гвард нарушен: отсутствие log_registration_summary() прошло МОЛЧА"
        assert any("log_registration_summary" in w for w in warnings), (
            f"WARNING обязан называть метод, которого не хватает: {warnings!r}"
        )
        assert any("summary_guard" in w or "FakeCommandManagerWithoutSummary" in w for w in warnings), (
            f"WARNING обязан называть объект/процесс, у которого метода не хватает: {warnings!r}"
        )
