# -*- coding: utf-8 -*-
"""Фикстуры пакета тестов statistics_module (Ф0.1 «trust gate»).

Здесь живёт ``declarations_snapshot`` — замена сплошной очистке реестра
объявлений. Тот же файл-близнец лежит в ``process_module/tests/conftest.py``:
общего места для тестовых фикстур двух модулей в дереве нет, а conftest на
уровне ``modules/`` накрыл бы ВСЕ модули разом — шире, чем задача просила.
Две копии по десять строк дешевле, чем новый общий слой; расходиться им
незачем, но если разойдутся — правки видно в обеих.
"""

import sys
from pathlib import Path

_modules = Path(__file__).resolve().parent.parent.parent
_root = _modules.parent.parent
for p in (_modules, _root):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

import pytest  # noqa: E402

from multiprocess_framework.modules.observability_declarations import (  # noqa: E402
    restore,
    snapshot,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (  # noqa: E402
    ensure_framework_producers,
)


@pytest.fixture(autouse=True)
def declarations_snapshot():
    """Снимок реестра объявлений до теста, возврат к нему после.

    **Зачем.** Реестр объявлений процессный и наполняется ИМПОРТОМ. Тест, унёсший
    из него чужое имя, ломает не себя, а соседей — и не сразу, а в зависимости от
    порядка сборки: на коммите ``5226045a`` один голый ``forget_declarations()``
    здесь давал ``21 failed`` в ``process_module/tests``, если ``statistics_module``
    собирался первым, и ноль в обратном порядке. Снимок/возврат делает след теста
    ограниченным самим тестом, каким бы этот след ни был.

    **Догрев производителей ДО снимка — не украшение, а условие корректности.**
    ``restore`` возвращает реестр К СНИМКУ, то есть стирает и то, что объявилось
    ИМПОРТОМ во время теста. Ленивый импорт производителя внутри теста — живая
    дорога (гейт heartbeat тянет ``heartbeat/telemetry.py`` из ``_make_gate``), и
    без догрева фикстура сама создала бы ту же потерю, от которой заведена: имя,
    стёртое возвратом, обратно не объявится — модуль уже в ``sys.modules``.
    ``ensure_framework_producers()`` идемпотентна (после первого раза — поиск в
    ``sys.modules`` и ничего сверх) и втягивает пятёрку метрик фреймворка ДО
    снятия снимка, так что терять её нечему.

    **Фикстура не отменяет стража сессии** (``modules/tests/conftest.py``). Она
    лечит след теста в ДВУХ каталогах, где она объявлена; страж смотрит на живой
    реестр в конце сессии и ловит утечку откуда угодно — из прототипа, плагинов,
    process_manager_module, где фикстуры нет. Проверено тестом
    ``modules/tests/test_declarations_registry_hazards.py``.
    """
    ensure_framework_producers()
    state = snapshot()
    yield
    restore(state)
