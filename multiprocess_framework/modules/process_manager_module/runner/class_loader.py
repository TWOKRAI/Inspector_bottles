"""Динамическая загрузка класса процесса.

Собственного логгера здесь БОЛЬШЕ НЕТ (2.2). Был ``_ProcessLogger`` — 57 строк,
разводившие «есть менеджер / нет менеджера» третьим по счёту способом; внутри
он держал ``FallbackLogger``, то есть был обёрткой над обёрткой. Оба
производственных вызова создавали его БЕЗ менеджера
(``process_runner``, ``spawner``), а параметр ``logger_manager`` жил только в
тестах — то есть развилка, ради которой класс существовал, в проде не
исполнялась ни разу.

Замена — именованный вид ``get_std_logger(<имя процесса>)``: тот же контракт
(«есть процессный менеджер — пишем в него под своим именем, нет — в stdlib, но
не в никуда»), вдвое дешевле по замеру и на одного писателя меньше.
"""

import importlib
import traceback
from typing import Any, Optional, Type

from ...logger_module.adapters.std_facade import StdLoggerFacade


def _load_process_class(class_path: str, log: StdLoggerFacade) -> Optional[Type[Any]]:
    """Загрузить класс процесса по полному пути модуля."""
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as e:
        log.error("Failed to load process class '%s': %s", class_path, e)
        traceback.print_exc()
        return None
