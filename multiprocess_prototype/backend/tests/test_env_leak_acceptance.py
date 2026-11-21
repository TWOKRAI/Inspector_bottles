"""Приёмка C-99: env приложения не утекает между тестами (слепой tester, до реализации).

Дефект. Тесты и код приложения (``apply_env_aliases()``, SystemLauncher, launch,
``frontend/run.py``) пишут в ``os.environ`` НАПРЯМУЮ, минуя ``monkeypatch``.
``monkeypatch.delenv(k, raising=False)`` на ОТСУТСТВУЮЩЕМ ключе ничего не
запоминает, поэтому записанное значение переживает тест и красит следующий.
Реальная пара: ``test_main_applies_env_aliases_before_resolve`` дописывает
``INSPECTOR_MANIFEST``; следующий в том же процессе
``test_boot_foundation_names_from_real_manifest`` падает с ``KeyError: 'system'``.

Файл читается сверху вниз: ПОРЯДОК ОПРЕДЕЛЕНИЙ — ЧАСТЬ ТЕСТА (писатель, затем
жертва; pytest идёт в порядке определения, плагинов перестановки в проекте нет).

Критерии приёмки → тесты:

1. набор из 18 ключей, дрейф ``ENV_ALIAS_PAIRS``  → ``test_key_set_is_18_and_tracks_alias_pairs``
2. откат после прямой записи любого из 18 ключей   → писатель/жертва ``direct``
3. откат после настоящего ``apply_env_aliases()``  → писатель/жертва ``real``
4. реальная пара-репродукция даёт 2 passed         → ``test_real_repro_pair_passes_in_one_process``
5. жертва не зеленеет вслепую                      → флаги ``_WRITER_RAN`` +
   ``test_victims_alone_go_red_not_trivially_green``
6. независимость от окружения запуска              → модульная фикстура ``_pinned_env``
7. без блокирующих вызовов; subprocess — с timeout → ``_run_nested_pytest``

Ожидаемые значения — литералы, из проверяемого кода не выводятся.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Корень репозитория: <root>/multiprocess_prototype/backend/tests/<этот файл>.
_ROOT = Path(__file__).resolve().parents[3]
_THIS_FILE = Path(__file__).resolve().relative_to(_ROOT).as_posix()

#: Ровно 18 ключей env приложения: 8 пар ENV_ALIAS_PAIRS + два одиночных ключа.
KEYS: tuple[str, ...] = (
    "MULTIPROCESS_PID_FILE",
    "INSPECTOR_PID_FILE",
    "MULTIPROCESS_LOG_DIR",
    "INSPECTOR_LOG_DIR",
    "MULTIPROCESS_MANIFEST",
    "INSPECTOR_MANIFEST",
    "MULTIPROCESS_LOG_LEVEL",
    "INSPECTOR_LOG_LEVEL",
    "MULTIPROCESS_FRAME_TRACE",
    "INSPECTOR_FRAME_TRACE",
    "MULTIPROCESS_HEALTH_LOG_ONLY",
    "INSPECTOR_HEALTH_LOG_ONLY",
    "MULTIPROCESS_HEALTH_BREAKER_THRESHOLD",
    "INSPECTOR_HEALTH_BREAKER_THRESHOLD",
    "MULTIPROCESS_HEALTH_BREAKER_COOLDOWN",
    "INSPECTOR_HEALTH_BREAKER_COOLDOWN",
    "INSPECTOR_PRESENTATION",
    "MPF_APP_NAME",
)

#: Состояние «до писателя»: задано заранее ровно два ключа (как у оператора),
#: остальные 16 отсутствуют. Эти два писатель потом перезаписывает.
BASELINE: dict[str, str] = {
    "INSPECTOR_LOG_LEVEL": "WARNING",
    "MPF_APP_NAME": "BaselineApp",
}

#: Состояние, которое обязан увидеть тест ПОСЛЕ писателя: ровно BASELINE.
EXPECTED_AFTER: dict[str, str | None] = {k: BASELINE.get(k) for k in KEYS}

#: Реальная пара-репродукция из дефекта (писатель, затем жертва).
REAL_WRITER = (
    "multiprocess_prototype/backend/tests/test_run_app_prototype.py::test_main_applies_env_aliases_before_resolve"
)
REAL_VICTIM = (
    "multiprocess_prototype/frontend/tests/test_app_foundation_names.py::test_boot_foundation_names_from_real_manifest"
)

#: Писатель отметился в ЭТОМ процессе (ставится в самом конце тела писателя).
#: Жертва без отметки обязана краснеть: запуск жертвы отдельно (-k, --deselect,
#: --lf) не должен давать «зелёное» потому, что утечки просто не было.
_WRITER_RAN: dict[str, bool] = {"direct": False, "real": False}


def _snapshot() -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in KEYS}


def _reset_to_baseline() -> None:
    """Прямо (без monkeypatch) привести 18 ключей к BASELINE."""
    for key in KEYS:
        os.environ.pop(key, None)
    os.environ.update(BASELINE)


@pytest.fixture(scope="module", autouse=True)
def _pinned_env():
    """Критерий 6: тесты не зависят от env запуска.

    В окружении оператора ``INSPECTOR_PID_FILE`` и др. могут быть заданы заранее —
    фиксируем известное состояние на модуль и возвращаем исходное после модуля.
    Возврат — ручной и безусловный: даже если утечку писателя не откатил откат на
    уровне теста, она не выйдет за пределы этого файла.
    """
    original = _snapshot()
    _reset_to_baseline()
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --- критерий 1: набор ключей и дрейф ENV_ALIAS_PAIRS ---------------------------


def test_key_set_is_18_and_tracks_alias_pairs():
    """18 ключей = 8 пар ENV_ALIAS_PAIRS + INSPECTOR_PRESENTATION + MPF_APP_NAME.

    Красный при дрейфе: добавили пару в ENV_ALIAS_PAIRS — набор KEYS (а с ним и
    откат env) устарел, обновить надо оба.
    """
    from multiprocess_framework.modules.app_module import ENV_ALIAS_PAIRS

    assert len(KEYS) == 18
    assert len(set(KEYS)) == 18, "в KEYS есть дубликат"
    assert len(ENV_ALIAS_PAIRS) == 8, (
        f"ENV_ALIAS_PAIRS изменилась: {len(ENV_ALIAS_PAIRS)} пар вместо 8 — обновите набор ключей отката env"
    )
    from_pairs = {key for pair in ENV_ALIAS_PAIRS for key in pair}
    assert set(KEYS) == from_pairs | {"INSPECTOR_PRESENTATION", "MPF_APP_NAME"}, (
        f"дрейф набора ключей: нет в KEYS={sorted(from_pairs - set(KEYS))}, "
        f"лишние в KEYS={sorted(set(KEYS) - from_pairs - {'INSPECTOR_PRESENTATION', 'MPF_APP_NAME'})}"
    )


# --- критерий 2: откат после ПРЯМОЙ записи в os.environ ---------------------------


def test_writer_direct_environ_writes():
    """Писатель: напрямую пишет все 18 ключей (в том числе два предзаданных)."""
    for key in KEYS:
        os.environ[key] = f"/writer/{key}"
    # наблюдаемый эффект самого писателя: запись действительно легла в env
    assert _snapshot() == {k: f"/writer/{k}" for k in KEYS}
    _WRITER_RAN["direct"] = True


def test_victim_direct_writes_rolled_back():
    """Жертва: env ровно как до писателя — отсутствовавшие ключи отсутствуют,
    предзаданные (INSPECTOR_LOG_LEVEL, MPF_APP_NAME) с прежним значением."""
    assert _WRITER_RAN["direct"], "писатель не отработал в этом процессе: проверка жертвы бессмысленна"
    assert _snapshot() == EXPECTED_AFTER


# --- критерий 3: откат после НАСТОЯЩЕГО apply_env_aliases() ----------------------


def test_writer_real_apply_env_aliases():
    """Писатель: настоящий apply_env_aliases(). Задан только MULTIPROCESS_MANIFEST,
    INSPECTOR_LOG_LEVEL=WARNING предзадан — функция дописывает зеркала."""
    from multiprocess_framework.modules.app_module import apply_env_aliases

    # независимость от успеха отката после прошлого писателя: старт всегда из BASELINE
    _reset_to_baseline()
    os.environ["MULTIPROCESS_MANIFEST"] = "/writer/manifest.yaml"

    apply_env_aliases()

    # наблюдаемый эффект: зеркала легли в os.environ (через снимок 18 ключей:
    # assert по os.environ напрямую печатает в сообщении весь env, с секретами)
    snap = _snapshot()
    assert snap["INSPECTOR_MANIFEST"] == "/writer/manifest.yaml"
    assert snap["MULTIPROCESS_LOG_LEVEL"] == "WARNING"
    assert snap["MULTIPROCESS_MANIFEST"] == "/writer/manifest.yaml"
    _WRITER_RAN["real"] = True


def test_victim_apply_env_aliases_rolled_back():
    """Жертва: ни INSPECTOR_MANIFEST, ни MULTIPROCESS_MANIFEST, ни зеркального
    MULTIPROCESS_LOG_LEVEL; INSPECTOR_LOG_LEVEL по-прежнему WARNING."""
    assert _WRITER_RAN["real"], "писатель не отработал в этом процессе: проверка жертвы бессмысленна"
    snap = _snapshot()
    assert snap["INSPECTOR_MANIFEST"] is None
    assert snap["MULTIPROCESS_MANIFEST"] is None
    assert snap["MULTIPROCESS_LOG_LEVEL"] is None
    assert snap["INSPECTOR_LOG_LEVEL"] == "WARNING"
    assert snap == EXPECTED_AFTER


# --- критерии 4 и 5: вложенный pytest (subprocess, всегда с timeout) ---------------

_STATUS_LINE = re.compile(r"^(\S+::\S+) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.MULTILINE)


def _run_nested_pytest(node_ids: list[str], timeout: float = 120.0) -> tuple[int, dict[str, str], str]:
    """Запустить вложенный pytest: cwd = корень дерева, жёсткий timeout.

    Возвращает (код возврата, {node-id: статус} в порядке выполнения, вывод).
    Если вложенный запуск не нашёл ни одного из тестов — падает с понятным
    сообщением (а не молча «ничего не проверил»).
    """
    # детям — чистый env без 18 ключей: независимость от окружения запуска (критерий 6)
    child_env = {k: v for k, v in os.environ.items() if k not in KEYS}
    cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider", *node_ids]
    try:
        proc = subprocess.run(
            cmd,
            cwd=_ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stdout or b"")[-2000:] if isinstance(exc.stdout, bytes) else (exc.stdout or "")[-2000:]
        pytest.fail(f"вложенный pytest не уложился в {timeout} с (зависание): {tail}")
    out = proc.stdout + "\n" + proc.stderr
    statuses = {m.group(1): m.group(2) for m in _STATUS_LINE.finditer(out)}
    missing = [n for n in node_ids if n not in statuses]
    if missing:
        pytest.fail(
            f"вложенный запуск не нашёл/не выполнил тест(ы) {missing} (код {proc.returncode}); вывод:\n{out[-3000:]}"
        )
    return proc.returncode, statuses, out


@pytest.mark.timeout(150)
def test_real_repro_pair_passes_in_one_process():
    """Критерий 4: писатель → жертва из дефекта в ОДНОМ процессе дают 2 passed.

    До реализации ожидаемо: 1 passed (писатель), 1 failed (жертва, KeyError: 'system').
    """
    code, statuses, out = _run_nested_pytest([REAL_WRITER, REAL_VICTIM])
    assert list(statuses) == [REAL_WRITER, REAL_VICTIM], f"порядок выполнения нарушен: {list(statuses)}"
    assert statuses[REAL_WRITER] == "PASSED", out[-2500:]
    assert statuses[REAL_VICTIM] == "PASSED", f"жертва красна после писателя (утечка env):\n{out[-2500:]}"
    assert code == 0


@pytest.mark.timeout(150)
def test_victims_alone_go_red_not_trivially_green():
    """Критерий 5: жертвы этого файла, запущенные БЕЗ писателей (по node-id),
    краснеют — а не зеленеют тривиально оттого, что утечки не было."""
    victims = [
        f"{_THIS_FILE}::test_victim_direct_writes_rolled_back",
        f"{_THIS_FILE}::test_victim_apply_env_aliases_rolled_back",
    ]
    code, statuses, out = _run_nested_pytest(victims)
    assert statuses == {v: "FAILED" for v in victims}, out[-2500:]
    assert code != 0
