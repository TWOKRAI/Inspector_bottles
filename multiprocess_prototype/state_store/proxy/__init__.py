# state_store/proxy — клиентская часть StateStore
#
# StateProxy     — IPC-клиент для ProcessModule: чтение/запись/подписки
# GuiStateProxy  — Qt-safe обёртка: callbacks через Qt main thread
from multiprocess_prototype.state_store.proxy.state_proxy import StateProxy
from multiprocess_prototype.state_store.proxy.gui_state_proxy import GuiStateProxy

__all__ = [
    "StateProxy",
    "GuiStateProxy",
]
