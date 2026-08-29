# -*- coding: utf-8 -*-
"""Страж сетки: каталог метрик фреймворка на закрытии сессии (Ф0.1 «trust gate»).

Сторож живёт в conftest, а не в тест-файле, потому что предмет у него —
СЕССИЯ, а не файл: teardown session-фикстуры откладывается до конца всего
прогона, где бы ни лежал последний тест. В conftest он вдобавок подключается к
любому прогону, который вообще касается ``modules/tests`` — включая прогон
одного файла, — а фикстура, объявленная внутри тест-модуля, требует, чтобы
собрался именно тот модуль.

Setup у сторожа не пустой: он ДОГРЕВАЕТ производителей метрик до снятия
каталога. Зачем и почему это не маскирует утечку — в шапке
``_declarations_catalogue_guard.py``.
"""

import sys
from pathlib import Path

_modules = Path(__file__).resolve().parent.parent
_root = _modules.parent.parent
for p in (_modules, _root):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

import pytest  # noqa: E402

from multiprocess_framework.modules.observability_declarations import declared_metrics  # noqa: E402

from multiprocess_framework.modules.tests._declarations_catalogue_guard import (  # noqa: E402
    catalogue_verdict,
    loaded_producers,
    warm_producers,
)


@pytest.fixture(scope="session", autouse=True)
def framework_metric_catalogue_guard():
    """Сверяет каталог метрик фреймворка с литералом ПОСЛЕ последнего теста сессии.

    Догрев на setup — чтобы у сторожа была собранная сцена (и чтобы соседний
    приёмочный страж из ``test_declarations_leak_session_catalogue_guard.py``,
    который догрева не делает, судил о полном каталоге, а не о пустоте прогона
    одного файла). Вердикт на teardown — чтобы поймать утечку из любого теста
    сессии, включая тесты вне ``statistics_module``/``process_module``, где
    фикстуры ``declarations_snapshot`` нет.
    """
    warm_producers()
    yield
    verdict = catalogue_verdict(declared_metrics(), producers=loaded_producers())
    assert verdict is None, verdict
