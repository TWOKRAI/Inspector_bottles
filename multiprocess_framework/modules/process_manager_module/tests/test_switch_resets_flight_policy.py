# -*- coding: utf-8 -*-
"""Ф5 (5.1) — switch рецепта возвращает политику дампа вместе со всем остальным.

**Шестая дорога пересборки**, которой спека не называла (она перечисляла пять):
``ProcessManagerProcess._reset_observability_sessions``. Инъекция И8d снимала
рекордер ровно в этом вызове и давала **ноль красных** — вся остальная батарея
задачи проходит мимо PM.

Что при этом ломается вживую: switch чистит слой L3, ``introspect.observability``
честно отвечает «сессия пуста», а рекордер продолжает работать по СНЯТОЙ правке.
Провенанс и действующая политика расходятся — и расходятся молча. Это тот самый
класс «следствие без причины», который уже ловили на телеметрии (5.10.f) и на
отборе широких записей (4.1).

Сторож живёт рядом с механизмом (``process_manager_module``), а не в
``process_module/tests/``: последний слоем НИЖЕ и импортировать PM не вправе — на
4.1 такая правка уже роняла контракт слоёв.

Судится ЭФФЕКТ (ручки живого рекордера вернулись к нижнему слою), а не факт
вызова: шпион на имени функции стережёт имя.
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_flight import FlightRecorder

#: Политика нижнего слоя (L1) — то, к чему обязан вернуться switch.
BASE_KEEP = 5
#: Ручка оператора в L3 — то, что switch обязан снять. Отличается от базы;
#: совпади они — сторож был бы зелен и при полностью оторванной дороге.
SESSION_KEEP = 1


def _pm() -> ProcessManagerProcess:
    """PM в объёме, который читает ``_reset_observability_sessions``.

    Через ``__new__`` и минимальный набор атрибутов — дословно приём соседних
    сторожей оркестратора: поднимать полный PM ради одной строки значило бы
    платить секундами и сделать сторож хрупким по чужой причине.
    """
    pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.logger_manager = pm.error_manager = pm.stats_manager = None
    pm._heartbeat = None
    pm.flight_recorder = FlightRecorder(True, "ring", BASE_KEEP, 0)
    pm._config = {"observability_app": {"flight": {"enabled": True, "sink": "ring", "keep": BASE_KEEP}}}
    pm.errors: List[str] = []
    pm.get_config = lambda key, default=None: pm._config.get(key, default)  # type: ignore[method-assign]
    pm._log_info = lambda *a, **k: None  # type: ignore[method-assign]
    pm._log_error = lambda msg, *a, **k: pm.errors.append(str(msg))  # type: ignore[method-assign]
    pm._broadcast_command = lambda *a, **k: 0  # type: ignore[method-assign]
    return pm


def test_switch_returns_the_flight_policy_to_the_lower_layer() -> None:
    """Ручка оператора снята слоем — значит снята и у рекордера, а не только в провенансе."""
    pm = _pm()
    layers = process_observability_layers(pm)
    layers.session_set("flight.keep", SESSION_KEEP, origin="test")
    # Предпосылка, без которой сторож вакуумен: правка ДЕЙСТВУЕТ до switch.
    # Донести её до живого рекордера — та же пересборка, которой пользуется
    # `config.reload`; не сделай мы этого, «после switch keep=5» было бы верно
    # и на нетронутом рекордере.
    from multiprocess_framework.modules.process_module.managers.observability_reload import (
        apply_observability_layers,
    )

    apply_observability_layers(layers, flight_recorder=pm.flight_recorder, origin="test")
    assert pm.flight_recorder.knobs[2] == SESSION_KEEP, "предпосылка: ручка оператора действует"

    pm._reset_observability_sessions("switch")

    assert layers.session_keys() == (), "предпосылка: слой сессии действительно очищен"
    assert not pm.errors, f"сброс не имеет права падать молча: {pm.errors}"
    assert pm.flight_recorder.knobs[2] == BASE_KEEP, (
        "switch снял ручку со слоя, а рекордер остался на снятой правке — "
        "провенанс и действующая политика разошлись молча"
    )


def test_the_reset_reports_its_own_keys() -> None:
    """Контроль к утверждению выше: сброс действительно ВИДЕЛ ключ, а не промолчал.

    Без него «ключей нет и политика базовая» читалось бы как здоровье и при
    сбросе, который не нашёл ничего (подтверждающий ноль засчитывается только в
    паре с контролем, дающим ненулевое).
    """
    pm = _pm()
    process_observability_layers(pm).session_set("flight.keep", SESSION_KEEP, origin="test")

    report: Dict[str, Any] = pm._reset_observability_sessions("switch")

    assert report["orchestrator"] == ["flight.keep"]
