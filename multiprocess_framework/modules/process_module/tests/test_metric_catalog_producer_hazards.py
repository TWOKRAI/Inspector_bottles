# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА добора каталога метрик (Task 0.3, находка M1) — тесты автора.

Приёмочные критерии задачи стережёт независимый набор
``test_metric_catalog_order_gate.py``; здесь — то, чего он видеть не мог, потому
что писался до реализации и не знал, ЧЕМ она будет сделана. Реализация — два
предохранителя, и каждый ниже доказан ОТДЕЛЬНО:

1. :func:`~...configs.telemetry_publish_config.ensure_framework_producers` —
   ``gated_metrics()`` сам втягивает модули-производители, поэтому каталог полон
   у ЛЮБОГО читателя (гейт, readback ``introspect.telemetry``, строки GUI,
   ``unknown_metrics``), а не только на дороге heartbeat;
2. порядок вызовов — ``_warn_unknown_metrics`` ПОСЛЕ ``_make_gate`` на обоих
   входах (``_build_telemetry_gate`` и ``reconfigure_telemetry``), потому что
   именно ``_make_gate`` тянет ``heartbeat/telemetry.py``.

**Почему это не одна работа, сделанная дважды, и почему тесты на них разные.**
Каждый предохранитель В ОДИНОЧКУ чинит дорогу heartbeat — измерено (см.
:class:`TestOrderSafeguardAloneKeepsTheVoiceHonest`). Значит, набор, который
проверяет только «на буте нет ложного WARNING», остаётся ЗЕЛЁНЫМ при снятии
любого одного из них: предохранители маскируют друг друга, а свойство, которое
не краснеет от собственной поломки, не существует. Поэтому здесь два разных
объектива: предохранитель 1 виден по ПОЛНОТЕ КАТАЛОГА в свежем интерпретаторе
(его снятие красит :class:`TestImportRingAndCatalogCompleteness`), предохранитель
2 — по ГОЛОСУ при НАМЕРЕННО обезвреженном предохранителе 1.

**Почему свежий интерпретатор.** Причина та же, что у соседнего файла: pytest
грузит модули с тестами до их исполнения, а ``test_telemetry_gate.py``
импортирует ``heartbeat.telemetry`` на верхнем уровне — к моменту любого теста
пакета каталог уже полон чужим импортом, и порядок импортов перестаёт значить.

**Хелпер ``_run_fresh_interpreter`` продублирован из соседнего файла намеренно.**
Импорт приватного имени из тестерского набора связал бы два файла, которые
владелец гоняет через ОТДЕЛЬНЫЕ слом-инъекции: правка или откат одного файла
ронял бы сбор другого, и матрица прочитала бы «ноль красных» там, где на деле
сторожа не собрались (класс дефекта из памяти проекта: «ноль в инъекции = сторожа
не собрались»). Двадцать строк дубля дешевле такой ошибки.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# tests/ -> process_module -> modules -> multiprocess_framework -> корень worktree
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYTHON = sys.executable
_TIMEOUT_S = 30.0

#: Литерал, а не ``gated_metrics()``: ожидание, вычисленное проверяемым кодом,
#: согласилось бы с любым ответом, включая пустой.
_FRAMEWORK_METRICS = ("cycle_duration_ms", "effective_hz", "fps", "latency_ms", "shm")

_TPC = "multiprocess_framework.modules.process_module.configs.telemetry_publish_config"
_HEARTBEAT = "multiprocess_framework.modules.process_module.heartbeat.process_heartbeat"

#: Минимальный дублёр сервисов процесса — тот же контракт (``get_config`` +
#: ``log_*``), что у ``_FakeServices`` в ``test_telemetry_gate.py``. Собран строкой
#: без общего отступа: ``textwrap.dedent`` поверх f-строки со вставкой не может
#: согласовать два разных отступа и молча не срезает ничего.
_FAKE_SERVICES_SRC = "\n".join(
    [
        "class _FakeServices:",
        "    def __init__(self, config):",
        "        self._config = config",
        "        self.logs = []",
        "    def get_config(self, key, default=None):",
        "        return self._config.get(key, default)",
        "    def log_info(self, *a, **k):",
        "        pass",
        "    def log_debug(self, *a, **k):",
        "        pass",
        "    def log_warning(self, msg, *a, **k):",
        "        self.logs.append(str(msg))",
    ]
)


def _run_fresh_interpreter(script: str) -> dict:
    """Выполнить ``script`` в СВЕЖЕМ интерпретаторе и вернуть JSON из последней строки.

    Таймаут обязателен: висящий тест хуже отсутствующего — он прячет регрессию за
    ожиданием вместо того, чтобы покраснеть. ``cwd=_REPO_ROOT`` резолвит импорт
    ``multiprocess_framework.*`` тем же способом, что и обычный прогон из корня.
    """
    import os

    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    try:
        proc = subprocess.run(
            [_PYTHON, "-c", script],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"свежий интерпретатор завис дольше {_TIMEOUT_S}с — hang хуже отсутствия теста: {exc}")
    assert proc.returncode == 0, (
        f"скрипт в свежем интерпретаторе упал (returncode={proc.returncode}).\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"скрипт не напечатал JSON-строку. stderr:\n{proc.stderr}"
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# Предохранитель 1 — кольцо импортов и полнота каталога.
#
# ``ensure_framework_producers`` живёт в ``configs/telemetry_publish_config.py``,
# а тянет ``heartbeat/telemetry.py``, который ЭТОТ ЖЕ файл импортирует у себя на
# уровне модуля. Кольцо здесь не гипотеза: соседний ``observability_declarations``
# описывает воспроизведённый ``ImportError: partially initialized module`` ровно
# от такой пары, и именно поэтому производителей запрещено импортировать оттуда.
# ---------------------------------------------------------------------------


class TestImportRingAndCatalogCompleteness:
    """Модуль конфига импортируется первым делом и отдаёт ПОЛНЫЙ каталог."""

    def test_bare_first_import_of_the_config_module_does_not_break(self) -> None:
        """``import <telemetry_publish_config>`` ПЕРВЫМ делом и БЕЗ вызова функций.

        Отдельный тест от «каталог полон» намеренно: кольцо ломает сам ИМПОРТ, а
        не чтение каталога, и упавший импорт в тесте, который сразу зовёт
        ``gated_metrics()``, читался бы как «каталог не собрался». Здесь виден
        именно импорт: ни одной функции не вызвано.
        """
        script = textwrap.dedent(
            f"""
            import json
            import {_TPC} as tpc

            print(json.dumps({{
                "module": tpc.__name__,
                "has_ensure": callable(getattr(tpc, "ensure_framework_producers", None)),
            }}))
            """
        )
        result = _run_fresh_interpreter(script)
        assert result["module"] == _TPC
        assert result["has_ensure"] is True

    def test_catalog_is_full_when_the_producer_module_is_imported_first(self) -> None:
        """Обратный порядок: сперва ``heartbeat.telemetry`` (он сам тянет конфиг).

        Третий порядок сверх двух тестерских — и единственный, где импорт идёт
        ПРОТИВ направления добора: ``telemetry.py`` → ``telemetry_publish_config``
        → (при первом же вызове) обратно в ``telemetry.py``. Если бы добор стоял
        на уровне модуля, кольцо замкнулось бы именно здесь.
        """
        script = textwrap.dedent(
            """
            import json
            from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics

            print(json.dumps({"catalog": sorted(gated_metrics())}))
            """
        )
        result = _run_fresh_interpreter(script)
        assert tuple(result["catalog"]) == _FRAMEWORK_METRICS

    def test_catalog_is_full_when_the_policy_module_is_imported_first(self) -> None:
        """Четвёртый порядок: сперва ``configs.observation_policy``.

        Он и замыкает кольцо на практике: ``telemetry.py`` импортирует
        ``observation_policy``, а тот — ``telemetry_publish_config``. Порядок, при
        котором частично инициализированным оказывается СРЕДНЕЕ звено, не
        покрывают ни тестерские два, ни предыдущий.
        """
        script = textwrap.dedent(
            f"""
            import json
            import multiprocess_framework.modules.process_module.configs.observation_policy  # noqa: F401
            from {_TPC} import gated_metrics

            print(json.dumps({{"catalog": sorted(gated_metrics())}}))
            """
        )
        result = _run_fresh_interpreter(script)
        assert tuple(result["catalog"]) == _FRAMEWORK_METRICS


# ---------------------------------------------------------------------------
# Цена. ``gated_metrics()`` зовётся часто (readback пульта, строки GUI, каждая
# сборка гейта), и добор обязан стоить ровно поиск в ``sys.modules``.
# ---------------------------------------------------------------------------


class TestCatalogWarmupCost:
    """Повторный вызов не исполняет модулей и не доходит до ``sys.meta_path``."""

    def test_repeat_calls_never_reach_the_meta_path(self) -> None:
        """После прогрева N вызовов дают НОЛЬ обращений к ``sys.meta_path``.

        Измерение, а не таймер: сторож по времени на общей машине флейкует, а
        ``find_spec`` — точная граница «дальше ``sys.modules`` не пошли».
        Интерпретатор спрашивает ``meta_path`` ТОЛЬКО когда модуля нет в
        ``sys.modules``, поэтому ноль здесь и означает «работы сверх поиска в
        ``sys.modules`` не делается».

        Число из живого замера (20 000 вызовов, этот же интерпретатор):
        ``declared_metrics`` — 0.655 мкс/вызов, ``gated_metrics`` с добором —
        1.283 мкс/вызов, накладные добора ≈ 0.63 мкс. В assert время не вынесено
        намеренно (см. выше про флейк), число живёт здесь как ориентир.
        """
        from ..configs.telemetry_publish_config import gated_metrics

        gated_metrics()  # прогрев: первый вызов действительно импортирует

        class _CountingFinder:
            calls = 0

            def find_spec(self, fullname, path=None, target=None):  # noqa: D102, ANN001
                _CountingFinder.calls += 1
                return None

        modules_before = len(sys.modules)
        sys.meta_path.insert(0, _CountingFinder())
        try:
            for _ in range(2000):
                gated_metrics()
        finally:
            sys.meta_path.pop(0)

        assert _CountingFinder.calls == 0, (
            f"добор каталога уходил в sys.meta_path {_CountingFinder.calls} раз на 2000 вызовов — "
            "это не поиск в sys.modules, а настоящий импорт на горячем пути"
        )
        assert len(sys.modules) == modules_before


# ---------------------------------------------------------------------------
# Предохранитель 2 — ПОРЯДОК вызовов, проверенный в одиночку.
#
# Предохранитель 1 здесь намеренно ОБЕЗВРЕЖЕН подменой
# ``tpc.ensure_framework_producers`` на no-op: иначе каталог полон и до
# ``_make_gate``, голос молчит по чужой заслуге, и тест остался бы зелёным при
# любом порядке — то есть не доказывал бы ничего.
# ---------------------------------------------------------------------------


def _script_with_disabled_producer_import(*, body: list[str]) -> str:
    """Скрипт, где добор каталога снят, а дальше исполняется ``body``.

    Собран ``"\\n".join`` без ``dedent``: внутрь подставляется исходник класса со
    своим отступом, и ``dedent`` поверх f-строки в таком случае молча не срезает
    ничего (класс дефекта пойман соседним файлом — ``IndentationError`` в
    подпроцессе).
    """
    return "\n".join(
        [
            "import json",
            f"import {_TPC} as tpc",
            "tpc.ensure_framework_producers = lambda: None  # снять предохранитель 1",
            _FAKE_SERVICES_SRC,
            f"from {_HEARTBEAT} import ProcessHeartbeat",
            "before = sorted(tpc.gated_metrics())",
            *body,
            'print(json.dumps({"before": before, "after": sorted(tpc.gated_metrics()), "warnings": svc.logs}))',
        ]
    )


class TestOrderSafeguardAloneKeepsTheVoiceHonest:
    """Порядок ``_warn_unknown_metrics`` после ``_make_gate`` — сам по себе достаточен.

    Каждый тест сначала УТВЕРЖДАЕТ неполноту каталога до сборки гейта
    (``before`` без ``fps``) — иначе он выродился бы в проверку того, что каталог
    и так полон, и молчал бы при возврате старого порядка.
    """

    def test_boot_stays_silent_on_a_real_metric_without_the_producer_import(self) -> None:
        """Вход 1 (``_build_telemetry_gate``): каталог неполон, WARNING всё равно нет."""
        cfg = {"telemetry": {"publish": {"metrics": {"fps": {"enabled": False}}}}}
        script = _script_with_disabled_producer_import(
            body=[
                f"svc = _FakeServices({cfg!r})",
                "hb = ProcessHeartbeat(svc)",
                "hb._build_telemetry_gate()",
            ]
        )
        result = _run_fresh_interpreter(script)
        assert "fps" not in result["before"], (
            "предохранитель 1 не обезврежен — каталог полон ДО сборки гейта, "
            f"и тест ничего не проверяет: before={result['before']}"
        )
        assert "fps" in result["after"], "после _make_gate каталог обязан быть полон — иначе гейт собран не тем"
        assert result["warnings"] == []

    def test_reconfigure_stays_silent_on_a_real_metric_without_the_producer_import(self) -> None:
        """Вход 2 (``reconfigure_telemetry``): то же свойство на рантайм-дороге.

        Второй вход попадает первым, когда рантайм-команда приходит раньше первой
        сборки гейта — у процесса без секции ``telemetry.publish`` гейт на старте
        не собирается вовсе, и ``.telemetry`` тогда не импортирован никем.
        """
        script = _script_with_disabled_producer_import(
            body=[
                "svc = _FakeServices({})",
                "hb = ProcessHeartbeat(svc)",
                "hb.reconfigure_telemetry({'metrics': {'fps': {'enabled': False}}}, mode='replace')",
            ]
        )
        result = _run_fresh_interpreter(script)
        assert "fps" not in result["before"], (
            f"предохранитель 1 не обезврежен — тест выродился: before={result['before']}"
        )
        assert "fps" in result["after"]
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Второй вход целиком (оба предохранителя на месте) + контрольная пара для него.
# У тестера теста на ``reconfigure_telemetry`` нет — он честно предупредил, что
# его критерии называют только бут.
# ---------------------------------------------------------------------------


def _reconfigure_script(*, publish: dict) -> str:
    """Скрипт рантайм-пересборки гейта в свежем интерпретаторе (без правок реализации)."""
    return "\n".join(
        [
            "import json",
            _FAKE_SERVICES_SRC,
            f"from {_HEARTBEAT} import ProcessHeartbeat",
            "svc = _FakeServices({})",
            "hb = ProcessHeartbeat(svc)",
            f"hb.reconfigure_telemetry({publish!r}, mode='replace')",
            'print(json.dumps({"warnings": svc.logs}))',
        ]
    )


class TestReconfigureEntryPoint:
    """``telemetry.reconfigure`` — вторая дорога к тому же голосу."""

    def test_runtime_reconfigure_with_a_real_metric_name_does_not_warn(self) -> None:
        """Живая метрика в рантайм-команде — тишина."""
        script = _reconfigure_script(publish={"metrics": {"fps": {"enabled": False}}})
        assert _run_fresh_interpreter(script)["warnings"] == []

    def test_runtime_reconfigure_with_a_typo_still_warns_exactly_once(self) -> None:
        """Контрольная пара второго входа: ``latency`` вместо ``latency_ms`` слышно.

        Без этого теста «починка» второго входа могла бы состоять в снятии голоса
        (или в расширении стража «пустой каталог → не судить» на любой каталог) —
        оба варианта прошли бы тест выше и спрятали бы настоящую опечатку.
        """
        result = _run_fresh_interpreter(_reconfigure_script(publish={"metrics": {"latency": {"interval_sec": 0.5}}}))
        warnings = result["warnings"]
        assert len(warnings) == 1, f"ожидался ровно один WARNING, пришло {len(warnings)}: {warnings}"
        assert "latency" in warnings[0]
