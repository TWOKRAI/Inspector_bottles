# -*- coding: utf-8 -*-
"""pult_web — веб-пульт ленты (Task 2.3b плана ``line-sim``).

Процесс ``pult`` в одиночку: страница + JSON API на 127.0.0.1:8092,
форвардящий каждую ручку в ``belt.*`` процесса ``robot`` через
``DeviceHubClient``. Своей логики ленты у пульта нет.
"""

from .plugin import PultWebPlugin

__all__ = ["PultWebPlugin"]
