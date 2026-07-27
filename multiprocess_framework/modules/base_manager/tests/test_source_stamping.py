# -*- coding: utf-8 -*-
"""Ф2.1 — записи уходят под именем своего источника, а не под ``module="main"``.

План: plans/observability-unified-routing.md, задача 2.1.

Зачем это отдельный файл. До Ф2.1 ``ObservableMixin._log_*`` не передавал
``module`` вовсе, поэтому ВСЕ записи фреймворка ложились в файл под дефолтом
``main``: тридцать менеджеров и все плагины были неразличимы в артефакте.
Резолв правил по имени источника (2.2-2.7) строится поверх штампа, поэтому
штамп проверяется отдельно от резолва — иначе дефект штампа проявился бы как
дефект правил.

Здесь — правила штампа на слоте ``logger`` (кто выигрывает, что переживает
pickle, штампует ли auto_proxy-путь). Артефакт на диске — в
``logger_module/tests/test_source_stamp_artifact.py``; имя плагина — в
``process_module/tests/test_plugin_source_stamping.py``.
"""

from __future__ import annotations

import pickle
from typing import Any, Dict, List, Tuple

from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin


class _RecordingLogger:
    """Слот 'logger', запоминающий (уровень, сообщение, kwargs) каждого вызова.

    Сигнатура повторяет LoggerCore: ``module`` — именованный параметр, поэтому
    штамп виден в kwargs, а не растворяется в позиционных аргументах.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def _capture(self, level: str, message: str, **kwargs: Any) -> None:
        self.calls.append((level, message, kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        self._capture("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._capture("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._capture("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._capture("error", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._capture("critical", message, **kwargs)

    @property
    def last_module(self) -> Any:
        return self.calls[-1][2].get("module")


class _Manager(BaseManager, ObservableMixin):
    """Типовой наследник: BaseManager сначала, миксин следом."""

    def __init__(self, name: str, logger: Any, **mixin_kwargs: Any) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={"logger": logger}, **mixin_kwargs)

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


class _MixinFirstManager(BaseManager, ObservableMixin):
    """Обратный порядок инициализации — миксин ДО BaseManager.

    Такой порядок в кодовой базе встречается, и именно он ломает любую попытку
    вычислить имя источника в ``ObservableMixin.__init__``: ``manager_name``
    на тот момент ещё не существует.
    """

    def __init__(self, name: str, logger: Any) -> None:
        ObservableMixin.__init__(self, managers={"logger": logger})
        BaseManager.__init__(self, name)

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Кто выигрывает
# ---------------------------------------------------------------------------


def test_manager_name_stamped() -> None:
    """Имя менеджера доезжает до слота как module=."""
    slot = _RecordingLogger()
    _Manager("capture_manager", slot)._log_info("кадр получен")
    assert slot.last_module == "capture_manager"


def test_explicit_module_on_call_site_wins() -> None:
    """Явный module= на call-site сильнее штампа — иначе Ф2.1 сломала бы
    существующие вызовы, которые уже проставляют имя вручную."""
    slot = _RecordingLogger()
    _Manager("capture_manager", slot)._log_info("кадр", module="hikvision")
    assert slot.last_module == "hikvision"


def test_source_name_override_wins_over_manager_name() -> None:
    """Явный source_name= сильнее manager_name."""
    slot = _RecordingLogger()
    mgr = _Manager("capture_manager", slot, source_name="vision.capture")
    mgr._log_info("кадр")
    assert slot.last_module == "vision.capture"


def test_without_any_name_falls_back_to_main() -> None:
    """Голый миксин без имён сохраняет прежний дефолт."""

    class _Bare(ObservableMixin):
        pass

    slot = _RecordingLogger()
    bare = _Bare(managers={"logger": slot})
    bare._log_info("без имени")
    assert slot.last_module == "main"


def test_mixin_initialised_before_base_manager_still_stamps() -> None:
    """Резолв ленивый: обратный порядок __init__ не оставляет запись без имени."""
    slot = _RecordingLogger()
    _MixinFirstManager("late_named", slot)._log_info("привет")
    assert slot.last_module == "late_named"


# ---------------------------------------------------------------------------
# Все пути штампуют одинаково
# ---------------------------------------------------------------------------


def test_every_severity_helper_stamps() -> None:
    """Пять именованных помощников штампуют, а не только info."""
    slot = _RecordingLogger()
    mgr = _Manager("router_manager", slot)
    mgr._log_debug("d")
    mgr._log_info("i")
    mgr._log_warning("w")
    mgr._log_error("e")
    mgr._log_critical("c")
    assert [call[0] for call in slot.calls] == ["debug", "info", "warning", "error", "critical"]
    assert {call[2].get("module") for call in slot.calls} == {"router_manager"}


def test_generic_log_stamps() -> None:
    """``_log(level, ...)`` с уровнем-строкой — тот же штамп."""
    slot = _RecordingLogger()
    _Manager("state_manager", slot)._log("warning", "через общий вход")
    assert slot.calls[-1][0] == "warning"
    assert slot.last_module == "state_manager"


def test_public_alias_stamps() -> None:
    """Публичный алиас log_info (его принимает чужой код как зависимость)."""
    slot = _RecordingLogger()
    _Manager("chain_context", slot).log_info("через алиас")
    assert slot.last_module == "chain_context"


def test_auto_proxy_path_stamps() -> None:
    """auto_proxy-прокси создаются замыканиями в обход _log_* — до Ф2.1 они
    ходили прямо в _call_manager и остались бы без штампа."""
    slot = _RecordingLogger()
    mgr = _Manager("pool_dispatcher", slot, auto_proxy=True)
    mgr.log_info("через прокси")
    assert slot.last_module == "pool_dispatcher"


def test_auto_proxy_respects_explicit_module() -> None:
    """Прокси не перетирает явное имя."""
    slot = _RecordingLogger()
    mgr = _Manager("pool_dispatcher", slot, auto_proxy=True)
    mgr.log_warning("через прокси", module="worker_3")
    assert slot.last_module == "worker_3"


# ---------------------------------------------------------------------------
# Границы процесса
# ---------------------------------------------------------------------------


def test_source_name_survives_pickle() -> None:
    """spawn-режим Windows пиклит менеджеры. Менеджеры регистрируются заново
    у владельца, а имя обязано приехать с объектом — иначе в дочернем процессе
    все записи снова станут ``main``."""
    slot = _RecordingLogger()
    mgr = _Manager("shm_manager", slot, source_name="vision.shm")
    revived = pickle.loads(pickle.dumps(mgr))
    revived.register_manager("logger", slot)
    revived._log_info("после unpickle")
    assert slot.last_module == "vision.shm"


def test_manager_name_survives_pickle() -> None:
    """Тот же путь без явного source_name: имя берётся из manager_name."""
    slot = _RecordingLogger()
    mgr = _Manager("shm_manager", slot)
    revived = pickle.loads(pickle.dumps(mgr))
    revived.register_manager("logger", slot)
    revived._log_info("после unpickle")
    assert slot.last_module == "shm_manager"
