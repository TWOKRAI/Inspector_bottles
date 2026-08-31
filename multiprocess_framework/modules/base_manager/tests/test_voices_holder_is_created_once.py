# -*- coding: utf-8 -*-
"""Сторож minor 9 ревью Task 1.4 — ленивый держатель окон создаётся РОВНО один раз.

Находка: ``ObservableMixin._voices`` был написан как check-then-set (``get`` →
``if None`` → присвоение). Два потока, впервые голосящие одновременно, получали
РАЗНЫХ держателей, и один тут же становился сиротой вместе со своим счётом
подавлений: голос по его ключам звучал бы заново, а «подавлено с прошлой
записи» потерялось бы молча.

**Естественным прогоном это не воспроизводится** — ревью намеряло 0 из 200:
между двумя операциями под GIL 3.12 просто некуда вклиниться. Поэтому сторож
не «гоняет шторм и надеется», а РАСШИРЯЕТ окно искусственно: конструктор
держателя задерживается, и оба потока гарантированно оказываются между
проверкой и присвоением. Ровно тот же приём, которым ревью и увидело дефект.

Что проверяется — ТОЖДЕСТВО объекта, а не отсутствие потери счёта: потеря
недетерминирована и тест на неё был бы флейком в одну сторону и вакуумом в
другую, а «держатель один» — это и есть обещание.
"""

from __future__ import annotations

import threading
import time
from typing import Any, List

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.logger_module.core import windowed_voice

#: Дедлайн на ``join``. Тест, который висит, хуже отсутствующего.
_JOIN_DEADLINE_SEC = 20.0

#: Насколько расширяем окно между «проверил» и «присвоил».
_WIDEN_SEC = 0.05


class _Probe(BaseManager, ObservableMixin):
    """Минимальный носитель миксина: нужен только ``__dict__`` и ``_voices``."""

    def __init__(self) -> None:
        BaseManager.__init__(self, manager_name="VoicesHolderProbe")
        ObservableMixin.__init__(self)

    def initialize(self) -> bool:  # noqa: D102 — абстрактные слоты базы, телу здесь нечего делать
        return True

    def shutdown(self) -> bool:  # noqa: D102
        return True


def test_two_threads_racing_the_lazy_holder_get_the_same_object(monkeypatch) -> None:
    real_init = windowed_voice.WindowedVoices.__init__

    def _slow_init(self, *args, **kwargs):
        # Задержка ВНУТРИ конструктора: к моменту присвоения соседний поток уже
        # прошёл свою проверку `get(...) is None` и строит второй экземпляр.
        real_init(self, *args, **kwargs)
        time.sleep(_WIDEN_SEC)

    monkeypatch.setattr(windowed_voice.WindowedVoices, "__init__", _slow_init)

    probe = _Probe()
    seen: List[Any] = []
    errors: List[BaseException] = []
    start = threading.Barrier(2, timeout=_JOIN_DEADLINE_SEC)

    def grab() -> None:
        try:
            start.wait()
            seen.append(probe._voices())
        except BaseException as exc:  # noqa: BLE001 — падение потока обязано доехать до теста
            errors.append(exc)

    threads = [threading.Thread(target=grab, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_JOIN_DEADLINE_SEC)

    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"потоки не завершились за {_JOIN_DEADLINE_SEC} с: {alive}"
    assert not errors, f"исключения в потоках: {errors}"
    assert len(seen) == 2, f"оба потока обязаны получить держатель: {seen!r}"

    # Литерал обещания: держатель ОДИН. Сравнение по id, а не по равенству —
    # у WindowedVoices нет __eq__, и два пустых экземпляра «равны» неотличимо.
    assert seen[0] is seen[1], (
        "два потока получили РАЗНЫХ держателей окон: один из них — сирота вместе со своим счётом подавлений"
    )
    assert probe._voices() is seen[0], "закреплённым обязан остаться тот же держатель"
