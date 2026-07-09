"""delta_message.py — контракт state_delta-сообщения (Delta → bridge-envelope).

Единая точка сборки словаря, который GuiProcess.delta_sink гонит в
DataReceiverBridge, а GuiStateBindings/topology_bridge потребляют. Раньше
envelope собирался инлайном в `process.py` и терял часть Delta: удаление
(`new_value is MISSING`), `transaction_id`, `old_value`, `source`. Здесь
контракт зафиксирован в одном месте — производитель и потребитель согласованы.

Формат envelope (Dict at Boundary, все значения pickle-safe):
    {
        "data_type": "state_delta",
        "path": "processes.cam.state.fps",
        "value": <new_value | None при удалении>,
        "deleted": <bool>,          # True → узел удалён (new_value был MISSING)
        "old_value": <old_value | None если узел создавался>,
        "transaction_id": "<uuid>", # связывает дельты одного batch
        "source": "camera_0",
    }

`value` при удалении — None (а не sentinel MISSING): потребитель отличает
удаление по флагу `deleted`, а не по значению. None-как-значение и удаление
различимы (`deleted=False, value=None` ≠ `deleted=True, value=None`).
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta

STATE_DELTA = "state_delta"


def state_delta_message(delta: Delta) -> dict[str, Any]:
    """Собрать bridge-envelope из Delta без потери delete/transaction_id/old_value.

    Args:
        delta: Delta из GuiStateProxy (уже десериализованный объект).

    Returns:
        dict формата state_delta (см. модульный docstring).
    """
    is_delete = delta.new_value is MISSING
    return {
        "data_type": STATE_DELTA,
        "path": delta.path,
        "value": None if is_delete else delta.new_value,
        "deleted": is_delete,
        "old_value": None if delta.old_value is MISSING else delta.old_value,
        "transaction_id": delta.transaction_id,
        "source": delta.source,
    }
