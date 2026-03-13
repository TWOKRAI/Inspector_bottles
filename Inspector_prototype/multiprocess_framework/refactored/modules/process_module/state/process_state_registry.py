"""
ProcessStateRegistry — обратная совместимость.

Класс перенесён в shared_resources_module.state.process_state_registry
для устранения циклической зависимости.

Этот файл сохраняется как алиас для старых импортов.
"""

from ...shared_resources_module.state.process_state_registry import ProcessStateRegistry

__all__ = ["ProcessStateRegistry"]
