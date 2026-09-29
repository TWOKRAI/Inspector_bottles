# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 4.6 (слепые, по контракту из брифа): число потоков OpenCV
процесса берётся из рецепта (``cv_threads``), дефолт 2.

Контракт:
  * ``ProcessConfig.extras["cv_threads"]`` → ``as_generic_config()`` → поле
    ``GenericProcessConfig`` → ``build()`` кладёт его в ``proc_dict["config"]``.
  * ``run_process_function`` до создания класса процесса зовёт
    ``cv2.setNumThreads(N)``; N = ``cv_threads`` или 2 при отсутствии ключа.
  * ``introspect.status`` отдаёт ``cv_threads`` = ``cv2.getNumThreads()``;
    cv2 недоступен → процесс стартует, ``cv_threads: None``.

Реальный ребёнок — spawn-процесс с настоящим ``run_process_function`` (bundle-режим),
детали в ``_cv_threads_helpers``. Ожидаемые значения — литералы. Жёсткий дедлайн:
join(25 с) → kill.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys

import pytest

from multiprocess_framework.modules.process_manager_module.topology.blueprint import ProcessConfig

from ._cv_threads_helpers import child_entry

_JOIN_DEADLINE_S = 25.0
_MISSING = "<no report>"


def _cores_default() -> int:
    """Дефолт OpenCV в ЭТОМ окружении (родитель не трогали) — чтобы выбрать значение,
    которое не совпадёт с ним случайно."""
    import cv2

    return cv2.getNumThreads()


def _run_child(tmp_path, monkeypatch, config: dict, block_cv2: bool = False) -> dict:
    report = tmp_path / "report.json"
    monkeypatch.setenv("T46_REPORT", str(report))  # spawn наследует os.environ
    ctx = mp.get_context("spawn")
    stop, system_stop = ctx.Event(), ctx.Event()
    proc = ctx.Process(
        target=child_entry,
        args=("t46child", config, block_cv2, stop, system_stop),
        daemon=True,
    )
    proc.start()
    proc.join(_JOIN_DEADLINE_S)
    hung = proc.is_alive()
    if hung:
        proc.kill()
        proc.join(5.0)
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    data["_hung"] = hung
    data["_exitcode"] = proc.exitcode
    return data


def _child_config(**extra) -> dict:
    # РЕАЛЬНАЯ форма proc_dict у runner'а: рецептные ключи живут ТОЛЬКО во вложенном "config"
    # (GenericProcessConfig.build() кладёт их туда; верхнего уровня у cv_threads в проде нет).
    return {"config": dict(extra)}


# --------------------------------------------------------------------------- #
#  Рецепт → GenericProcessConfig                                              #
# --------------------------------------------------------------------------- #


def test_blueprint_passes_cv_threads_from_extras_to_process_config() -> None:
    cfg = ProcessConfig(process_name="p", plugins=[], extras={"cv_threads": 4}).as_generic_config()
    _name, proc_dict = cfg.build()
    assert proc_dict["config"].get("cv_threads") == 4


# --------------------------------------------------------------------------- #
#  Реальный ребёнок                                                           #
# --------------------------------------------------------------------------- #


@pytest.fixture
def recipe_value() -> int:
    # 4 по брифу; если это и есть дефолт OpenCV машины — тест был бы вакуумным.
    return 4 if _cores_default() != 4 else 3


def test_recipe_value_four_is_applied_in_child(tmp_path, monkeypatch, recipe_value) -> None:
    got = _run_child(tmp_path, monkeypatch, _child_config(cv_threads=recipe_value))
    assert got.get("_hung") is False, got
    assert got.get("run", _MISSING) == recipe_value, got


def test_default_is_two_when_key_absent(tmp_path, monkeypatch) -> None:
    if _cores_default() == 2:
        pytest.skip("дефолт OpenCV на этой машине уже 2 — тест не различал бы реализацию")
    got = _run_child(tmp_path, monkeypatch, _child_config())
    assert got.get("_hung") is False, got
    assert got.get("run", _MISSING) == 2, got


def test_threads_set_before_process_class_init(tmp_path, monkeypatch, recipe_value) -> None:
    got = _run_child(tmp_path, monkeypatch, _child_config(cv_threads=recipe_value))
    assert got.get("init_done") is True, got  # класс процесса действительно создан
    assert got.get("init", _MISSING) == recipe_value, got


def test_child_starts_without_cv2_and_reports_none(tmp_path, monkeypatch) -> None:
    got = _run_child(tmp_path, monkeypatch, _child_config(cv_threads=4), block_cv2=True)
    # «стартует» = класс создан и run() отработал; «сообщает None» = снимок без cv2.
    assert got.get("init_done") is True, got
    assert got.get("_hung") is False, got
    assert got.get("run", _MISSING) is None, got
    # ... и ИМЕННО None в introspect.status (не «ключа нет», не исключение)
    assert got.get("status", _MISSING) is None, got


def test_top_level_key_is_fallback_for_flat_configs(tmp_path, monkeypatch, recipe_value) -> None:
    # Запасной путь для не-Generic процессов: плоский конфиг без вложенного "config".
    got = _run_child(tmp_path, monkeypatch, {"cv_threads": recipe_value})
    assert got.get("_hung") is False, got
    assert got.get("run", _MISSING) == recipe_value, got


def test_recipe_to_child_chain_via_real_build(tmp_path, monkeypatch, recipe_value) -> None:
    # Вся цепочка без ручной сборки конфига: extras рецепта -> as_generic_config().build()
    # -> bundle -> настоящий runner в spawn-ребёнке -> реальное getNumThreads().
    cfg = ProcessConfig(process_name="p", plugins=[], extras={"cv_threads": recipe_value}).as_generic_config()
    _name, proc_dict = cfg.build()
    got = _run_child(tmp_path, monkeypatch, dict(proc_dict))
    assert got.get("_hung") is False, got
    assert got.get("init", _MISSING) == recipe_value, got
    assert got.get("run", _MISSING) == recipe_value, got


def test_non_numeric_extras_value_error_names_the_key() -> None:
    cfg = ProcessConfig(process_name="p", plugins=[], extras={"cv_threads": "abc"})
    with pytest.raises(Exception, match="cv_threads"):
        cfg.as_generic_config()


@pytest.mark.parametrize("bad", [0, -1, True, 2.5, "abc"])
def test_invalid_value_in_runner_falls_back_to_default_with_warning(monkeypatch, bad) -> None:
    from multiprocess_framework.modules.process_manager_module.runner.process_runner import _apply_cv_threads

    applied: list = []

    class _FakeCv2:
        @staticmethod
        def setNumThreads(n):
            applied.append(n)

    warnings: list = []

    class _Log:
        def warning(self, msg):
            warnings.append(msg)

    monkeypatch.setitem(sys.modules, "cv2", _FakeCv2)
    _apply_cv_threads({"config": {"cv_threads": bad}}, _Log())
    assert applied == [2], (bad, applied)
    assert len(warnings) == 1 and "cv_threads" in warnings[0], warnings


# --------------------------------------------------------------------------- #
#  introspect.status                                                          #
# --------------------------------------------------------------------------- #


def _status() -> dict:
    from multiprocess_framework.modules.process_module.tests.test_introspect_commands import _make

    _svc, cm = _make(worker_manager=None)
    return cm.dispatch("introspect.status")


def test_introspect_status_reports_effective_cv_threads() -> None:
    import cv2

    before = cv2.getNumThreads()
    try:
        cv2.setNumThreads(3)
        result = _status()
    finally:
        cv2.setNumThreads(before)
    assert result.get("cv_threads") == 3, result


def test_introspect_status_reports_none_without_cv2(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)  # import cv2 → ImportError
    result = _status()
    assert result["success"] is True
    assert "cv_threads" in result and result["cv_threads"] is None, result
