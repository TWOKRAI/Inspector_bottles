"""Гейт чисел спрашивается ДО сборки записи — сторож, которого не было (Ф2, инъекция E1).

Найдено матрицей инъекций Ф2, заплата **E1**: сборка словаря записи перенесена
ПЕРЕД вызовом гейта (доставка при этом по-прежнему не происходит) — и из **2881
собранного теста не покраснел ни один**.

Почему ноль. Ближайший авторский сторож
``test_f2_numbers_policy_hazards.py::test_a_denied_number_never_reaches_delivery``
докстрингом честно называет себя «необходимым условием» и отдаёт достаточное
бенчу шага 5. Но в том же докстринге стоит утверждение «**словарь записи не
собирается**», и вот ЕГО тест не держит: он наблюдает
:meth:`ObservationPort._deliver_number`, то есть отвечает на вопрос «доставили
ли», а не «собирали ли». Заплата E1 собирает словарь и не доставляет — обе
проверки теста остаются верны.

Бенч сторожем здесь быть не может по двум причинам сразу: тест на время флейкий
по построению (абсолюты на этой машине гуляют вдвое), а сам бенч шага 5 сейчас
провален по постороннему поводу — цене ``ObservationPolicy.resolve``, которую
лечит Task 2.4. То есть до этого файла свойство «решение до сборки» не
сторожилось НИЧЕМ, и после починки 2.4 перенос гейта за сборку прошёл бы молча.

**Как сторожится здесь — наблюдаемым эффектом, а не шпионом на имени метода.**
Сборка записи читает ``tags`` (``dict(tags or {})``). Значит достаточно передать
отображение, которое замечает собственное чтение: гейт отработал первым — чтения
не было; сборка встала раньше — чтение произошло. Свойство держится при любом
переименовании внутренних методов и не зависит от того, как устроена доставка.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

from ...process_module.configs.observation_policy import (
    ObservationPolicy,
    ObservationPolicyConfig,
)
from ...process_module.configs.telemetry_publish_config import MetricRule
from .. import StatsManager
from ..observation.observation_manager import ObservationManager


class _WatchedTags(Dict[str, str]):
    """Словарь тегов, считающий обращения к своему содержимому.

    Наследник ``dict``: сборка записи зовёт ``dict(tags or {})``, а CPython на
    ``dict``-подклассе идёт быстрым путём копирования и ``keys``/``__iter__`` не
    трогает. Поэтому считаем ОБА естественных пути чтения — итерацию и
    ``keys()`` — и, чтобы быстрый путь не прошёл мимо счётчика, объявляем класс
    непустым: копирование непустого отображения обязано прочитать элементы.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reads: List[str] = []

    def keys(self):  # type: ignore[override]
        self.reads.append("keys")
        return super().keys()

    def __iter__(self) -> Iterator[str]:
        self.reads.append("iter")
        return super().__iter__()

    def items(self):  # type: ignore[override]
        self.reads.append("items")
        return super().items()


def _pair(process: str, policy: Any):
    """Реальные порт и менеджер, связанные как в ``ProcessManagers.create_all``."""
    port = ObservationManager(manager_name=f"port_{process}", process=SimpleNamespace(name=process))
    assert port.initialize()
    port.attach_numbers_policy(policy)
    mgr = StatsManager(
        manager_name=f"stats_{process}",
        config={
            "enabled": True,
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize()
    mgr.attach_observation_port(port)
    return mgr, port


def _policy(process: str, denied: str) -> ObservationPolicy:
    return ObservationPolicy(
        ObservationPolicyConfig(rules={f"processes.{process}.stats.{denied}": MetricRule(enabled=False)})
    )


class TestTheGateRunsBeforeTheRecordIsAssembled:
    """Запрещённая метрика не должна стоить даже сборки словаря."""

    def test_a_denied_metric_never_has_its_tags_read(self) -> None:
        mgr, _port = _pair("cam_e1", _policy("cam_e1", "denied"))
        tags = _WatchedTags({"cam": "left"})

        mgr.record_metric("denied", 1, tags)

        assert tags.reads == [], (
            f"теги запрещённой метрики прочитаны — значит запись собиралась ДО гейта: обращения {tags.reads}"
        )

    def test_the_control_an_allowed_metric_does_read_its_tags(self) -> None:
        """Контроль: без него предыдущий тест зелен и при полностью мёртвом пути.

        «Ноль обращений» — подтверждающий ноль, и засчитывать его можно только в
        паре с проверкой, дающей НЕнулевой ответ на соседнем входе.
        """
        mgr, _port = _pair("cam_e1c", _policy("cam_e1c", "denied"))
        tags = _WatchedTags({"cam": "left"})

        mgr.record_metric("allowed", 1, tags)

        assert tags.reads, "разрешённая метрика обязана собрать запись, а значит прочитать теги"

    def test_all_four_kinds_share_the_guarantee(self) -> None:
        """Гейт стоит на ОДНОМ шве — обещание обязано держаться у всех четырёх родов."""
        mgr, _port = _pair("cam_e1k", _policy("cam_e1k", "denied"))
        calls = (
            lambda t: mgr.record_metric("denied", 1, t),
            lambda t: mgr.increment("denied", t),
            lambda t: mgr.record_timing("denied", 0.5, t),
            lambda t: mgr.gauge("denied", 3, t),
        )
        for call in calls:
            tags = _WatchedTags({"cam": "left"})
            call(tags)
            assert tags.reads == [], f"род метрики собрал запись до гейта: {tags.reads}"
