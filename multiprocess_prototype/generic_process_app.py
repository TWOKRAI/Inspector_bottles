"""generic_process_app.py -- GenericProcessApp: исторический адрес класса процесса.

StateProxy теперь заводит фреймворковый ``GenericProcess`` (ADR-PM-049); здесь
поведения не осталось.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import (
    GenericProcess,
)


class GenericProcessApp(GenericProcess):
    """Исторический адрес: на него ссылаются ~116 ``process_class`` в YAML прототипа.

    Поведение (StateProxy, ``ctx.state_proxy``, останов прокси) — у ``GenericProcess``,
    ADR-PM-049. Переименование ссылок в YAML — отдельная задача.
    """
