# -*- coding: utf-8 -*-
"""Боевая ПРОВОДКА политики чисел: heartbeat → порт (Ф2, задача 2.1, шаг 3).

**Зачем отдельный файл, если приёмка зелёная.** Приёмка тестера подключает
политику к порту РУКАМИ (``port.attach_numbers_policy(policy)``) — иначе она не
смогла бы проверить поведение гейта вовсе. Поэтому её девять зелёных ничего не
говорят о том, зовёт ли этот метод кто-нибудь в БОЮ. Проверено грепом на готовой
реализации: не звал никто — механизм был бы мёртв на живом процессе при полностью
зелёном наборе. Класс дефекта в проекте назван («провод портов ≠ маршрут»), и
стоил он живого разбора; здесь он закрыт тестом, а не внимательностью.

Проверяются ОБЕ дороги, которыми политика встаёт на место: загрузочная
(``_build_telemetry_gate`` → ``_resolve_observation_policy``) и правочная
(``apply_observation_policy`` ← ``config.reload``). Их четыре точки присвоения
сведены в один шов ``_install_observation_policy``; тест смотрит на НАБЛЮДАЕМЫЙ
результат обеих, а не на существование шва — переименуй его кто-нибудь, и тест
останется верным.
"""

from __future__ import annotations

from typing import Tuple

from ...statistics_module.observation.observation_manager import ObservationManager
from ..heartbeat.process_heartbeat import ProcessHeartbeat
from ..plugins.testing import MockProcessServices


class _Services(MockProcessServices):
    """Дубль сервисов с НАСТОЯЩИМ портом наблюдений в слоте ``observation``.

    Дубль-порт из ``testing.py`` здесь не годится: он не менеджер и метода
    подключения политики не имеет — тест на нём был бы зелёным и при мёртвой
    проводке, потому что резолвер ступени 1 отдал бы объект без
    ``attach_numbers_policy``, а шов молча прошёл бы мимо.
    """

    def __init__(self, name: str = "cam1") -> None:
        super().__init__(name=name)
        port = ObservationManager(manager_name=f"observation_{name}", process=self)
        assert port.initialize(), "стенд сломан ДО проверки: порт не поднялся"
        self._observation_port_double = port

    @property
    def port(self) -> ObservationManager:
        return self._observation_port_double


def _boot(name: str = "cam1") -> Tuple[_Services, ProcessHeartbeat]:
    services = _Services(name=name)
    return services, ProcessHeartbeat(services)


def _rules(process: str, metric: str) -> dict:
    return {"rules": {f"processes.{process}.stats.{metric}": {"enabled": False}}}


class TestThePolicyReachesThePortInProduction:
    def test_the_port_starts_without_a_gate(self) -> None:
        """КОНТРОЛЬ: до проводки гейта нет.

        Без него оба теста ниже прошли бы и при гейте, поставленном где-то ещё
        (например, конструктором порта) — то есть доказывали бы не проводку.
        """
        services, _ = _boot()
        try:
            assert services.port.numbers_gate is None, "порт родился с гейтом — контроль мёртв"
        finally:
            services.port.shutdown()

    def test_config_reload_road_delivers_the_policy_and_it_acts(self) -> None:
        """``apply_observation_policy`` ставит ТУ ЖЕ политику и в порт — и она режет.

        Проверяются оба берега: ТОЖДЕСТВО объекта (второй потребитель, а не
        вторая сборка — иначе счёт попаданий и правила разъехались бы) и
        НАБЛЮДАЕМЫЙ эффект (число не собрано, счётчик вырос). Одного тождества
        мало: ссылка могла бы лечь в поле, которое никто не спрашивает.
        """
        services, hb = _boot()
        port = services.port
        try:
            applied = hb.apply_observation_policy(_rules("cam1", "noisy"))
            assert "processes.cam1.stats.noisy" in applied["rules"], f"правило не применилось вовсе: {applied!r}"

            gate = port.numbers_gate
            assert gate is not None, "политика не доехала до порта — механизм мёртв на живом процессе"
            assert gate.policy is hb._observation_policy, (
                "в порт уехала ДРУГАЯ политика: второй потребитель обязан быть тем же объектом, "
                "иначе счёт попаданий и правила разъедутся"
            )

            for _ in range(3):
                port.record_metric("noisy", 1)
            port.record_metric("open", 1)
            assert gate.dropped_by_metric() == {"noisy": 3}, (
                f"правило доехало, но не действует: {gate.dropped_by_metric()!r}"
            )
        finally:
            port.shutdown()

    def test_the_boot_road_delivers_the_policy_too(self) -> None:
        """Загрузочная дорога — вторая из четырёх точек, и она тоже обязана доставить.

        ``_build_telemetry_gate`` резолвит политику из слоёв и на процессе без
        секции ``telemetry.publish`` выходит рано, вернув ``None``. Политика при
        этом УЖЕ поставлена — и до правки шва ранний выход оставлял бы числа без
        неё до первого ``config.reload``.
        """
        services, hb = _boot()
        port = services.port
        try:
            hb._build_telemetry_gate()
            gate = port.numbers_gate
            assert gate is not None, "загрузочная дорога не доставила политику в порт"
            assert gate.policy is hb._observation_policy
        finally:
            port.shutdown()

    def test_a_port_without_the_method_does_not_break_the_tick(self) -> None:
        """Ступень 2 резолвера (вид без менеджера) — молчание, а не отказ.

        У процесса, поднятого не через ``register_all``, в слоте порта нет
        вовсе; доставка политики чисел не имеет права уронить такт уровней —
        уровни у такого процесса работают, а числа туда и не доставляются.
        """
        services, hb = _boot()
        port = services.port
        try:
            services._observation_port_double = object()  # слот отдаёт посторонний объект
            applied = hb.apply_observation_policy(_rules("cam1", "noisy"))
            assert applied["rules"], "такт уровней обязан пережить недоставку политики чисел"
        finally:
            port.shutdown()
