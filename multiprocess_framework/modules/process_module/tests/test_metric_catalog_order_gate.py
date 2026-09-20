# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 0.3 (M1) плана ``observability-closure`` — ДО реализации.

Цель задачи: ни одного WARNING «Неизвестные ключи telemetry.publish.metrics …»
при живой, реально существующей метрике; каталог объявленных метрик
(:func:`gated_metrics` / :func:`declared_metrics`) не должен зависеть от того,
что успел импортировать вызывающий код ДО обращения к нему.

**Почему subprocess, а не обычный pytest-тест в этом же процессе.**
``test_telemetry_gate.py`` (сосед в этом же пакете) импортирует
``heartbeat.telemetry`` на верхнем уровне файла — а pytest грузит модули с
тестами ДО их исполнения. К моменту, когда любой тест текущего пакета доходит
до ``ProcessHeartbeat._build_telemetry_gate()``, каталог метрик УЖЕ полон
чужим импортом, и дефект M1 не воспроизводится: проверено запуском одного из
тестов ниже прямо в этом файле без subprocess — он остаётся зелёным при живом
дефекте, потому что сосед по сессии уже дотянул ``telemetry.py``. Только
свежий интерпретатор, где ничего постороннего не импортировано, показывает то,
что видит настоящий загружающийся процесс (ревью: «было 7 WARNING за прогон
boot webcam_sketch»).

**Откуда взят сценарий (прочитано в коде, а не предположено).**
``ProcessHeartbeat._build_telemetry_gate()`` (process_heartbeat.py:498-571)
вызывает ``self._warn_unknown_metrics(config)`` (:561) РАНЬШЕ, чем
``self._make_gate(config)`` (:571) — а именно ``_make_gate`` тянет
``from .telemetry import TelemetryGate`` (:589), и это ПЕРВЫЙ импорт
производителя ``fps``/``latency_ms``/``effective_hz``/``cycle_duration_ms`` на
этом пути. ``_warn_capped_metrics(config)`` (:559, тоже до :561) мог бы
импортировать ``telemetry.py`` раньше, но делает это только когда
``config.tick_sec`` задан и положителен (process_heartbeat.py:376-380) — в
конфиге прототипа (`tick_sec: null`, наследуется от heartbeat_interval) эта
ветка не срабатывает вовсе. Итог: при ПЕРВОЙ в жизни процесса сборке гейта с
``tick_sec`` не заданным и конфигом, называющим настоящую метрику по имени
(``fps``), каталог в момент проверки содержит только ``shm`` (её объявляет
сам ``process_heartbeat.py`` на уровне модуля, process_heartbeat.py:21) — и
``fps`` ошибочно считается опечаткой.

Литералы каталога (5 имён) и текст WARNING — не выведены из проверяемого кода,
а списаны в задаче руками: ``observability_declarations.py`` объявляет
``fps``, ``latency_ms``, ``effective_hz``, ``cycle_duration_ms`` (telemetry.py)
и ``shm`` (process_heartbeat.py) — сверено чтением обоих файлов.
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

#: Литерал, а не producer(declared_metrics()) — ожидание, вычисленное тем же
#: кодом, который проверяется, согласилось бы с любым ответом (в т.ч. пустым).
_FRAMEWORK_METRICS = ("cycle_duration_ms", "effective_hz", "fps", "latency_ms", "shm")

#: Общий пролог: fake-сервисы (без pytest — subprocess исполняет голым python -c),
#: тот же минимальный контракт, что у ``_FakeServices`` в test_telemetry_gate.py
#: (get_config/log_warning) — прецедент подтверждает, что ``_build_telemetry_gate``
#: ничего больше не требует.
#:
#: Собрана СТРОКОЙ БЕЗ ОБЩЕГО ОТСТУПА (не через textwrap.dedent на f-string со
#: вставкой) — вложенный ``textwrap.dedent`` над f-строкой, куда этот текст
#: подставлен, не может согласовать общий отступ (у вставки он свой, у
#: обрамляющего литерала — свой), и `dedent` в этом случае молча ничего не
#: срезает: класс дефекта пойман здесь же прогоном (``IndentationError:
#: unexpected indent`` в подпроцессе) при первой попытке через f-string.
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


def _build_script(*, cfg: dict) -> str:
    """Собрать скрипт для харнесса ``_build_telemetry_gate`` БЕЗ f-string/dedent
    поверх ``_FAKE_SERVICES_SRC`` — та же причина, что у комментария выше.
    ``cfg`` едет через ``repr()`` (питоний литерал: JSON ``false/true/null`` —
    не то же самое, что ``False/True/None``, подстановка ``json.dumps`` сюда
    дала бы ``NameError: name 'false' is not defined`` — воспроизведено при
    первой попытке).
    """
    return "\n".join(
        [
            "import json",
            _FAKE_SERVICES_SRC,
            "from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (",
            "    ProcessHeartbeat,",
            ")",
            f"cfg = {cfg!r}",
            "svc = _FakeServices(cfg)",
            "hb = ProcessHeartbeat(svc)",
            "hb._build_telemetry_gate()",
            'print(json.dumps({"warnings": svc.logs}))',
        ]
    )


def _run_fresh_interpreter(script: str) -> dict:
    """Выполнить ``script`` в СВЕЖЕМ интерпретаторе (subprocess) и вернуть JSON из
    последней строки stdout.

    Таймаут обязателен: висящий тест хуже отсутствующего (прячет регрессию за
    ожиданием). ``cwd=_REPO_ROOT`` — тот же способ резолва импорта
    ``multiprocess_framework.*``, что и обычный прогон pytest из корня.
    """
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
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
# Критерий 1 — каталог полон «при любом порядке импортов». Проверено на ДВУХ
# разных заходах: (а) прочитать каталог, не импортировав НИ ОДНОГО
# производителя вручную; (б) импортировать производителя, объявляющего только
# ЧАСТЬ каталога (``shm``), и снова прочитать каталог. Оба захода должны дать
# ПОЛНЫЙ каталог — сегодня оба дают неполный, каждый на свой лад, и это само
# по себе доказательство «каталог зависит от порядка импортов».
# ---------------------------------------------------------------------------


def test_catalog_complete_with_zero_producer_preimport() -> None:
    """Каталог читается БЕЗ ручного импорта производителей — обязан быть полным.

    Критерий 1: «каталог не зависит от порядка импортов» подразумевает, что он
    не зависит и от того, импортировал ли вызывающий код производителей
    ВООБЩЕ, — сборка каталога обязана обеспечить это сама. Сегодня
    ``gated_metrics()`` — тонкая обёртка над ``declared_metrics()`` без
    принудительного импорта, поэтому в свежем интерпретаторе, где никто не
    тянул ``heartbeat.telemetry`` / ``heartbeat.process_heartbeat``, каталог
    пуст.
    """
    script = textwrap.dedent(
        """
        import json
        from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
            gated_metrics,
        )

        print(json.dumps({"catalog": sorted(gated_metrics())}))
        """
    )
    result = _run_fresh_interpreter(script)
    assert tuple(result["catalog"]) == _FRAMEWORK_METRICS


def test_catalog_complete_when_only_partial_producer_preimported() -> None:
    """Импортирован ЛИШЬ ``process_heartbeat`` (объявляет только ``shm``) — каталог
    всё равно обязан быть полон после обращения к нему.

    Второй порядок из требования «минимум два разных порядка импорта»: здесь,
    в отличие от предыдущего теста, один производитель УЖЕ импортирован —
    ровно та ситуация, где сегодня каталог отвечает по-разному в зависимости
    от того, какой именно код успел выполниться раньше.
    """
    script = textwrap.dedent(
        """
        import json
        import multiprocess_framework.modules.process_module.heartbeat.process_heartbeat  # noqa: F401
        from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
            gated_metrics,
        )

        print(json.dumps({"catalog": sorted(gated_metrics())}))
        """
    )
    result = _run_fresh_interpreter(script)
    assert tuple(result["catalog"]) == _FRAMEWORK_METRICS


# ---------------------------------------------------------------------------
# Критерий 2 — живая метрика не даёт ложного WARNING. Харнесс — тот же
# ``ProcessHeartbeat(_FakeServices(...))._build_telemetry_gate()``, что уже
# используется в ``test_telemetry_gate.py::TestBuildTelemetryGate`` (там —
# внутри общего pytest-процесса, где каталог уже полон чужим импортом; здесь —
# в свежем интерпретаторе, где он ещё нет).
# ---------------------------------------------------------------------------


def test_boot_with_real_metric_name_gives_no_false_unknown_warning() -> None:
    """Первая сборка гейта в процессе, ``tick_sec`` не задан (дефолт прототипа),
    конфиг называет НАСТОЯЩУЮ метрику ``fps`` — WARNING быть не должно.

    Это прямой аналог живого симптома ревью («7 ложных WARNING за прогон
    boot webcam_sketch»), сведённый к минимальному воспроизведению: реальный
    boot требует поднятого стенда, а этот харнесс — синхронный и без IO
    (прецедент: ``test_telemetry_gate.py`` использует тот же приём для
    аналогичных живых свойств гейта).
    """
    cfg = {"telemetry": {"publish": {"metrics": {"fps": {"enabled": False}}}}}
    result = _run_fresh_interpreter(_build_script(cfg=cfg))
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Критерий 3 — контрольная пара (ложноотрицательная сторона). Настоящая
# опечатка обязана по-прежнему звучать ОДИН раз — иначе «тест, который умеет
# только молчать, ничего не доказывает» (инструкция задачи), и наивное
# исправление («каталог всегда считать полным» / «warning убрать вовсе»)
# прошло бы предыдущие тесты, спрятав реальную опечатку.
# ---------------------------------------------------------------------------


def test_boot_with_typo_metric_name_still_warns_exactly_once() -> None:
    """``latency`` вместо ``latency_ms`` — WARNING обязан прозвучать, и ровно один раз.

    Тот же харнесс и тот же (худший, RED) порядок импорта, что у предыдущего
    теста — только дефекту здесь взяться неоткуда: правило существует, а
    подходящей метрики с таким именем нет ни в одном каталоге ни при каком
    порядке импортов. Этот тест ожидаемо ЗЕЛЁН уже сегодня (см. отчёт
    тестировщика, раздел «что ненадёжно») — его роль не доказывать M1, а
    стеречь БУДУЩЕЕ исправление от наивного решения («каталог всегда считать
    полным», «WARNING убрать вовсе»), которое молча спрятало бы настоящую
    опечатку.
    """
    cfg = {"telemetry": {"publish": {"metrics": {"latency": {"interval_sec": 0.5}}}}}
    result = _run_fresh_interpreter(_build_script(cfg=cfg))
    warnings = result["warnings"]
    assert len(warnings) == 1
    assert "latency" in warnings[0]
