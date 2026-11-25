# -*- coding: utf-8 -*-
"""W1-c (multicam-observability) — база контекста логгера стоит ДО шага 6 ``initialize()``.

Purpose: плагины пишут в ``configure``/``start`` внутри ``boot()``, а ``boot()`` зовётся из
``_init_custom_managers`` (шаг 6). Строки, записанные на шаге 6, обязаны нести имя процесса
(``extra["proc_name"]``), а вместе с ним — ``incarnation`` и ``recipe``; до правки база ставилась
на шаге 9 и строки шага 6 уходили с ``[-]``.

Стенд — настоящий ``ProcessModule("...").initialize()`` (не ``__new__`` с фейковым PSR), подкласс
переопределяет ``_init_custom_managers`` — это и есть хук шага 6. Tap ставится ВНУТРИ хука: логгер
появляется на шаге 3, раньше tap поставить нельзя. Запись ищется по тексту ``w1c-step6``, а не как
``records[0]``: до хука в tap идут и другие строки.

Тесты:
  1. строка из главного потока хука несёт ``proc_name``;
  2. строка из потока, созданного и присоединённого внутри хука (дедлайн ``join(2.0)``), тоже несёт
     ``proc_name`` — база общая на процесс, а не на поток;
  3. настоящий ``SharedResourcesManager`` и настоящий рецепт: в записи есть ``incarnation`` и
     ``recipe``. ``_build_resource`` глушит любое исключение (``except Exception: pass`` в трёх
     ветках), поэтому без этого теста молчаливая потеря поля прошла бы зелёной;
  4. строка из начала шага 4 (``_init_communication``) несёт ``proc_name`` — сторожит позицию «до
     шага 4», шаг 6 один этого не видит;
  5. ``_build_resource`` бросает — ``initialize()`` всё равно успешен и пишет WARNING: сбой украшения
     записи не вправе уронить подъём процесса и оставить router/console/command без shutdown.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.shared_resources_module.core.shared_resources_manager import (
    SharedResourcesManager,
)

__all__ = []

_MARKER = "w1c-step6"
_STEP4_MARKER = "w1c-step4"
_THREAD_JOIN_S = 2.0


class _Sink:
    """Приёмник tap: складывает записи, безопасен к записи из нескольких потоков."""

    name = "w1c"

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def write(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.records.append(data)
        return {"status": "success"}

    def close(self) -> None: ...

    def with_text(self, text: str) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.records if text in str(r.get("message", ""))]


class _HookProcess(ProcessModule):
    """``ProcessModule``, который пишет одну строку из хука шага 6 (``_init_custom_managers``)."""

    #: Пишет ли строку из отдельного потока (иначе — из потока, зовущего ``initialize``).
    log_from_thread = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sink = _Sink()
        self.hook_ran = False
        self.thread_alive_after_join: bool | None = None

    def _init_custom_managers(self) -> None:
        super()._init_custom_managers()
        # Tap — только здесь: логгер появился на шаге 3, раньше его поставить нельзя.
        self.get_manager("logger").add_tap(self.sink, min_level="DEBUG", name="w1c")
        if self.log_from_thread:
            worker = threading.Thread(target=self.log_info, args=(_MARKER,), name="w1c-hook-thread", daemon=True)
            worker.start()
            worker.join(_THREAD_JOIN_S)
            self.thread_alive_after_join = worker.is_alive()
        else:
            self.log_info(_MARKER)
        self.hook_ran = True


class _ThreadHookProcess(_HookProcess):
    log_from_thread = True


class _Step4Process(ProcessModule):
    """``ProcessModule``, который пишет строку в начале шага 4 (``_init_communication``)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sink = _Sink()

    def _init_communication(self) -> None:
        self.get_manager("logger").add_tap(self.sink, min_level="DEBUG", name="w1c")
        self.log_info(_STEP4_MARKER)
        super()._init_communication()


class _BrokenResourceProcess(ProcessModule):
    """``_build_resource`` бросает; tap ставится здесь же — раньше шага 3a логгера ещё нет."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sink = _Sink()

    def _build_resource(self) -> dict[str, Any]:
        self.get_manager("logger").add_tap(self.sink, min_level="DEBUG", name="w1c")
        raise RuntimeError("w1c-boom")


def _only_record(process: _HookProcess) -> dict[str, Any]:
    """Единственная запись ``w1c-step6`` из tap; иначе — осмысленный провал, а не IndexError."""
    assert process.hook_ran, "хук _init_custom_managers не дошёл до конца — шаг 6 не проверен"
    hits = process.sink.with_text(_MARKER)
    assert len(hits) == 1, f"записей с {_MARKER}: {len(hits)}; всего в tap: {len(process.sink.records)}"
    return hits[0]


def test_step6_record_has_proc_name() -> None:
    """Строка из главного потока хука шага 6 несёт ``proc_name == "w1c_proc"``."""
    process = _HookProcess("w1c_proc")
    try:
        assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"
        extra = _only_record(process)["extra"]
        assert extra["proc_name"] == "w1c_proc", extra
    finally:
        process.shutdown()


def test_step6_thread_record_has_proc_name() -> None:
    """Строка из потока, созданного и присоединённого в хуке, тоже несёт ``proc_name``."""
    process = _ThreadHookProcess("w1c_proc")
    try:
        assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"
        assert process.thread_alive_after_join is False, "поток хука не завершился за 2 с — запись могла не дойти"
        extra = _only_record(process)["extra"]
        assert extra["proc_name"] == "w1c_proc", extra
    finally:
        process.shutdown()


def test_step6_record_has_incarnation_and_recipe(tmp_path: Path) -> None:
    """Настоящие PSR и рецепт: ``incarnation == 5`` и ``recipe == "w1c_recipe"`` доехали до записи шага 6.

    ``_build_resource`` глушит любое исключение в ветках ``incarnation`` и ``recipe``;
    без проверки этих двух полей тихая потеря одного из них оставила бы тесты зелёными.
    """
    recipe = tmp_path / "w1c_recipe.yaml"
    recipe.write_text("observability: {}\n", encoding="utf-8")

    srm = SharedResourcesManager()
    # Как при рождении процесса оркестратором: инкарнация засеяна ДО создания ProcessModule.
    assert srm.process_state_registry.register_process(
        "w1c_proc", initial_state={"metadata": {"routing_incarnation": 5}}
    )

    process = _HookProcess(
        "w1c_proc",
        shared_resources=srm,
        config={"observability_recipe_path": str(recipe)},
    )
    try:
        assert process.initialize() is True, "initialize() с настоящим SharedResourcesManager не прошёл"
        extra = _only_record(process)["extra"]
        assert extra["proc_name"] == "w1c_proc", extra
        assert extra["incarnation"] == 5, extra
        assert extra["recipe"] == "w1c_recipe", extra
    finally:
        process.shutdown()


def test_step4_record_has_proc_name() -> None:
    """Позиция «до шага 4»: строка, записанная в начале ``_init_communication``, уже несёт имя.

    Тесты шага 6 это не сторожат — блок, уехавший за шаг 4 или 5, оставил бы их зелёными.
    """
    process = _Step4Process("w1c_proc")
    try:
        assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"
        hits = process.sink.with_text(_STEP4_MARKER)
        assert len(hits) == 1, f"записей с {_STEP4_MARKER}: {len(hits)}"
        extra = hits[0]["extra"]
        assert extra["proc_name"] == "w1c_proc", extra
    finally:
        process.shutdown()


def test_broken_resource_does_not_fail_initialize_and_warns() -> None:
    """Сбой ``_build_resource`` на шаге 3a: ``initialize()`` всё равно успешен, в логе WARNING с причиной."""
    process = _BrokenResourceProcess("w1c_proc")
    try:
        assert process.initialize() is True, "сбой _build_resource не должен проваливать initialize()"
        warnings = [r for r in process.sink.with_text("w1c-boom") if r["level"] == "WARNING"]
        assert len(warnings) == 1, process.sink.with_text("w1c-boom")
        assert "контекст логирования процесса 'w1c_proc' не установлен" in warnings[0]["message"]
    finally:
        process.shutdown()
