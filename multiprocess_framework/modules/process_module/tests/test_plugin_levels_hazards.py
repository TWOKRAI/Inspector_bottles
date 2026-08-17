# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА уровней плагина — авторский набор Task 3.5 (ADR-PM-038).

Дополнение к приёмочному ``test_plugin_levels_acceptance.py`` (независимый тестер,
от критериев), а НЕ замена. Здесь то, что видно только автору механизма: порядок
объявления и отдачи, два потока вокруг одного хранилища, столкновение имени
плагина с именем фреймворка, асимметрия push/poll относительно гейта, поведение
разъёма без хранилища.

Что каждый тест сторожит, если сформулировать до прогона:

* **порядок «объявил → отдал» не обязан соблюдаться, а «отдал, но не объявил» не
  обязан молчать.** Первое — потому что ``configure`` плагина вправе отдать
  стартовое значение раньше, чем дойдёт до объявления; второе — потому что
  необъявленное имя гейту неизвестно, публиковаться не будет НИКОГДА, и тихий
  отсев неотличим от опечатки в имени;
* **опрос гейту не подчиняется, а push подчиняется** — это не оплошность, а
  ADR-PM-035: гейт про трафик, а не про то, что процесс знает о себе. Свойство
  парное: закрытый гейт даёт ноль в дереве И ненулевое в опросе;
* **имя-дубль не разрешается — он отбрасывается.** Р3.5-11 сняла политику
  наложения («порядок несущий», «плагин побеждает») целиком: лист берётся, только
  если объявленный владелец имени совпадает с публикатором. Сторожится в ОБЕИХ
  дорогах — чужое имя не появляется ни в дереве, ни в опросе, и об этом слышно;
* **весь тик — ОДИН merge, и объединение имеет три ловушки** (Р3.5-12): пустой
  снимок воркеров не имеет права проглотить уровни и ``shm``; политика публикатора
  «все счётчики ``shm`` нулевые — не грузим дерево» обязана уцелеть внутри общей
  сборки; «данных нет вовсе» обязано давать НОЛЬ вызовов merge, а не пустой;
* **владелец считается в трёх местах — объявлении, публикации и снятии.** Разойдись
  они хоть в одном звене, уровень либо не поедет (владелец ≠ публикатор), либо не
  снимется на остановке. Сторожится ЭФФЕКТОМ на боевой тройке, а не чтением кода;
* **свежесть держится жизненным циклом.** ``retract`` зовёт фреймворк на остановке
  плагина, ПОСЛЕ пользовательского ``shutdown`` — плагин вправе отдать последнее
  значение в нём самом (``CapturePlugin`` обнуляет частоту на остановке захвата), и
  снятие до него оставило бы это значение висеть навсегда;
* **у хранилища три потока.** Писатель — воркер плагина, читатель — heartbeat,
  третий снимает уровни на остановке; копия словаря, растущего одновременно, без
  лока поднимает ``RuntimeError``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declared_metrics,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
    build_plugin_levels,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)


class _MinimalHazardPlugin(ProcessModulePlugin):
    """Плагин без поведения — нужен только его ЖИЗНЕННЫЙ ЦИКЛ."""

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        pass


#: Имя, которого нет нигде в репозитории, — положительное свойство §3.6
#: «универсальность». Механизм с зашитым списком имён провалит его по построению.
#:
#: БЕЗ ТОЧЕК, и это не косметика. Точечное имя уровня — отдельный, уже записанный
#: резидуал: ``TreeStore._merge_recursive`` разворачивает точку в ПУТЬ, но только
#: когда узел ``state`` уже существует как dict; на первом merge тот же ключ ложится
#: литералом. До Р3.5-12 уровни ехали своим merge прямо в ``processes.<p>.state``, и
#: первая ветка не встречалась; после объединения встречается обе. Судить тут форму
#: пути значило бы судить резидуал вместо универсальности — тестер пришёл к тому же
#: выводу независимо (``zzz_made_up_level`` в его П3).
MADE_UP = "zzz_made_up_level"


@pytest.fixture(autouse=True)
def _metric_registry_guard():
    """Забыть ТОЛЬКО имена, объявленные этим тестом.

    Не ``forget_declarations(KIND_METRIC)``: сплошная очистка плоскости
    невосстановима (производители уже импортированы, объявлять некому), а
    «восстановить, объявив заново» подменяет ВЛАДЕЛЬЦА и превращает законный
    повторный импорт соседа в ``ValueError``. Точечная форма забирает ровно
    свой мусор — см. ``forget_declarations(names=...)``.
    """
    before = set(declared_metrics())
    yield
    forget_declarations(KIND_METRIC, names=set(declared_metrics()) - before)


# --------------------------------------------------------------------------- #
# Носитель: протокол-полные сервисы (ВСЯ пятёрка log_*) + дерево + heartbeat.
# --------------------------------------------------------------------------- #
class _Proxy:
    """Мини-дерево со счётом обращений.

    **Точечный ключ ВНУТРИ ``data`` раскрывается в путь** — как у настоящего
    ``TreeStore._merge_recursive``, который склеивает ``f"{path}.{key}"`` и отдаёт
    результат в ``set()`` с полным резолвом. Первая редакция этого дубля делала
    ``node.update(data)`` и клала точечное имя ОДНИМ литеральным ключом; тест
    универсальности с именем ``zzz.made.up.level`` из-за этого краснел на
    исправном механизме — дубль не умел того, что умеет стор.
    """

    def __init__(self) -> None:
        self.tree: dict[str, Any] = {}
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, dict(data)))
        self._merge_recursive(path, data)

    def _merge_recursive(self, path: str, data: dict) -> None:
        """Дословно ``TreeStore._merge_recursive``: в dict рекурсия, если целевой
        узел ТОЖЕ dict; иначе — ``set`` по склеенному пути с полным резолвом точек."""
        for key, value in data.items():
            child = f"{path}.{key}" if path else key
            if isinstance(value, dict) and isinstance(self.get(child), dict):
                self._merge_recursive(child, value)
            else:
                *head, last = child.split(".")
                node = self.tree
                for part in head:
                    node = node.setdefault(part, {})
                node[last] = value

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class _Services(MockProcessServices):
    """Дубль сервисов, годный И плагину, И heartbeat'у, И BuiltinCommands.

    Наследование от ``MockProcessServices``, а не своя копия: пятёрка ``log_*``
    и порты приезжают оттуда, и когда протокол вырастет, дубль вырастет с ним.
    Добавлены только приватные имена, которые читают heartbeat/команды.
    """

    def __init__(self, name: str = "proc") -> None:
        super().__init__(name=name)
        self._state_proxy = _Proxy()
        self._heartbeat: ProcessHeartbeat | None = None

    def _log_info(self, *a: Any, **k: Any) -> None:  # BuiltinCommands зовёт с подчёркиванием
        pass

    def _log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def warnings(self) -> list[str]:
        return [str(entry.get("msg", "")) for entry in self.logs if entry.get("level") == "WARNING"]


def _boot(name: str = "proc") -> tuple[_Services, ProcessHeartbeat]:
    services = _Services(name=name)
    hb = ProcessHeartbeat(services)
    services._heartbeat = hb
    return services, hb


def _tick_levels(hb: ProcessHeartbeat, allowed_metrics=None) -> None:
    """Прогнать сборку тика БЕЗ воркеров — то есть судить ровно уровни.

    Р3.5-12 схлопнула три публикатора тика в один
    (``_publish_telemetry_to_tree``), и пустой снимок воркеров здесь не оговорка,
    а ловушка №1 объединения: ранний выход по ``not workers`` жил в прежнем
    воркерном публикаторе, и в общей сборке он проглотил бы и уровни, и ``shm``.
    Каждый вызов ниже — заодно проверка, что не проглатывает.
    """
    hb._publish_telemetry_to_tree({}, allowed_metrics)


def _poll(services: _Services) -> dict:
    bc = BuiltinCommands(services)
    bc._register_introspect_commands()
    return services.command_manager.commands["introspect.telemetry"]({})


def _tree(services: _Services, leaf: str) -> Any:
    return services._state_proxy.get(f"processes.{services.name}.state.{leaf}")


def _polled_state(services: _Services) -> dict:
    """Секция ``state`` снимка уровней — ТА ЖЕ форма пути, что у тика.

    ``levels`` зеркалит поддерево ``processes.<name>`` (``workers.*`` + ``state.*``),
    поэтому уровень адресуется ``levels["state"][имя]``, ровно как ``fps``.
    Плоского ``levels[имя]`` быть не может: ``TelemetryPoller._flatten_levels``
    склеивает ключи ответа с префиксом ``processes.<name>``, и плоское имя
    уехало бы в ``processes.<name>.<имя>`` — мимо пути, которым его пишет push.
    """
    levels = _poll(services).get("levels") or {}
    return levels.get("state") or {}


# --------------------------------------------------------------------------- #
# Универсальность — положительным свойством, а не отрицательным grep'ом.
# --------------------------------------------------------------------------- #
class TestFrameworkKnowsNoNames:
    def test_a_name_absent_from_the_repository_reaches_tree_and_poll(self):
        """Выдуманное имя доезжает обеими дорогами — значит списка имён нет."""
        services, hb = _boot(name="uni")
        ctx = PluginContext(services=services, config={}, plugin_name="made_up_plugin")
        ctx.declare_metric(MADE_UP)
        ctx.publish_metric(MADE_UP, 12.0)

        _tick_levels(hb)
        assert _tree(services, MADE_UP) == 12.0
        assert _polled_state(services)[MADE_UP] == 12.0

    def test_the_made_up_name_enters_the_gate_catalog(self):
        """И оно же становится управляемым: гейт обходит каталог объявлений."""
        services, _hb = _boot(name="uni2")
        ctx = PluginContext(services=services, config={}, plugin_name="made_up_plugin")
        ctx.declare_metric(MADE_UP)
        assert MADE_UP in declared_metrics()


# --------------------------------------------------------------------------- #
# Порядок: объявление после первого тика; публикация до объявления.
# --------------------------------------------------------------------------- #
class TestDeclarationOrder:
    def test_declaring_after_the_first_tick_starts_flowing_on_the_next(self):
        """Каталог читается НА ТИКЕ, а не кэшируется при сборке публикатора.

        Снимок каталога, взятый один раз, оставил бы плагин, объявившийся позже
        (ленивый импорт, hot-apply рецепта), без публикации навсегда — и симптом
        искали бы в гейте, где всё верно.
        """
        services, hb = _boot(name="late")
        ctx = PluginContext(services=services, config={}, plugin_name="late_plugin")
        ctx.publish_metric("late_level", 1.0)

        _tick_levels(hb)
        assert _tree(services, "late_level") is None, "необъявленное имя уехало в дерево"

        ctx.declare_metric("late_level")
        _tick_levels(hb)
        assert _tree(services, "late_level") == 1.0

    def test_publishing_before_declaring_keeps_the_value_and_says_it_once(self):
        """Значение не теряется, а отсев не молчит — и голос ровно один на имя."""
        services, hb = _boot(name="early")
        ctx = PluginContext(services=services, config={}, plugin_name="early_plugin")
        ctx.publish_metric("early_level", 5.0)

        _tick_levels(hb)
        _tick_levels(hb)
        _tick_levels(hb)
        said = [msg for msg in services.warnings() if "early_level" in msg]
        assert len(said) == 1, f"ожидали ОДИН голос на имя, получили {len(said)}: {said}"

        ctx.declare_metric("early_level")
        _tick_levels(hb)
        assert _tree(services, "early_level") == 5.0, "значение, отданное до объявления, потеряно"


# --------------------------------------------------------------------------- #
# Повторное объявление и конфликт владельцев.
# --------------------------------------------------------------------------- #
class TestRedeclaration:
    def test_same_plugin_may_redeclare(self):
        """Плагин переимпортируют (reload, spawn) — падать на этом нельзя."""
        services, _hb = _boot(name="re")
        ctx = PluginContext(services=services, config={}, plugin_name="same_plugin")
        ctx.declare_metric("re_level")
        ctx.declare_metric("re_level")

    def test_two_plugins_of_one_process_conflict(self):
        services, _hb = _boot(name="conf")
        a = PluginContext(services=services, config={}, plugin_name="plugin_a")
        b = PluginContext(services=services, config={}, plugin_name="plugin_b")
        a.declare_metric("conf_level")
        with pytest.raises(ValueError):
            b.declare_metric("conf_level")

    def test_context_without_plugin_name_owns_by_process(self):
        """Базовый ctx без имени плагина объявляет от имени ПРОЦЕССА, не 'None'."""
        services, _hb = _boot(name="owner_proc")
        PluginContext(services=services, config={}).declare_metric("owner_level")
        second = PluginContext(services=_Services(name="owner_proc"), config={})
        second.declare_metric("owner_level")  # тот же владелец — не конфликт


# --------------------------------------------------------------------------- #
# Гейт: push подчиняется, poll — нет. Пара маркеров ON/OFF.
# --------------------------------------------------------------------------- #
class TestGateCoversPushNotPoll:
    def test_closed_gate_zeroes_push_and_open_gate_restores_it(self):
        services, hb = _boot(name="gate")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin")
        ctx.declare_metric("gated_level")
        ctx.publish_metric("gated_level", 9.0)

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": False}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=0.0))
        assert _tree(services, "gated_level") is None, "закрытый гейт не остановил push"

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": True}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=1.0))
        assert _tree(services, "gated_level") == 9.0, (
            "открытый гейт не дал ненулевого — без этой половины пары закрытый ноль одинаков с 'механизм не подключён'"
        )

    def test_closed_gate_still_answers_the_poll(self):
        """ADR-PM-035: гейт про трафик, опрос про знание. Закрытое окно ≠ слепота."""
        services, hb = _boot(name="gate2")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin2")
        ctx.declare_metric("gated_level2")
        ctx.publish_metric("gated_level2", 4.0)

        hb.reconfigure_telemetry({"metrics": {"gated_level2": {"enabled": False}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=0.0))

        assert _tree(services, "gated_level2") is None
        assert _polled_state(services)["gated_level2"] == 4.0, (
            "закрытый гейт погасил и опрос — вкладка при флипе РТ-2 ослепла бы"
        )

    def test_the_gate_does_not_know_the_level_is_a_plugins(self):
        """Уровень плагина проходит ТОТ ЖЕ ``due_metrics``, что fps/latency_ms."""
        services, hb = _boot(name="gate3")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin3")
        ctx.declare_metric("gated_level3")
        hb.reconfigure_telemetry({"default_interval_sec": 10.0})
        allowed = hb._telemetry_gate.due_metrics(now=0.0)
        assert "gated_level3" in allowed
        # Созревание — тоже общее: второй вызов в том же окне метрику не выдаёт.
        assert "gated_level3" not in hb._telemetry_gate.due_metrics(now=0.1)


# --------------------------------------------------------------------------- #
# push == poll: одно число, один путь, одно округление.
# --------------------------------------------------------------------------- #
class TestPushEqualsPoll:
    def test_same_value_same_leaf_in_both_roads(self):
        services, hb = _boot(name="same")
        ctx = PluginContext(services=services, config={}, plugin_name="same_road")
        ctx.declare_metric("same_level")
        ctx.publish_metric("same_level", 15.34)

        _tick_levels(hb)
        assert _tree(services, "same_level") == pytest.approx(15.3)
        assert _polled_state(services)["same_level"] == pytest.approx(15.3), (
            "опрос и push разошлись в округлении — 'одна дорога' стало бы ложью"
        )

    def test_a_plugin_level_named_like_a_framework_metric_is_rejected_in_both_roads(self):
        """Имя-дубль (``fps``) ОТБРАСЫВАЕТСЯ, и одинаково в дереве и в опросе.

        Здесь стоял ровно обратный тест — «уровень плагина обязан лечь ПОСЛЕ
        агрегата и победить». Он пинил политику наложения ADR-PM-038, снятую
        Р3.5-11 целиком, и был зелен, пока политика была объявлена; на живом
        стенде она при этом НЕ РАБОТАЛА — продовое правило троттла
        ``processes.**.state.fps: 0.05`` вырезало вторую запись всегда, потому что
        оба merge тика приходили в одно окно 15.6-мс сетки Windows.

        Свойство, которое тест сторожил, уцелело и усилилось: **дерево и опрос
        отвечают на имя-дубль ОДИНАКОВО**. Изменился ответ — не «побеждает
        плагин», а «плагин отброшен, показание владельца цело». Судится значением,
        а не отсутствием вызова.
        """
        services, hb = _boot(name="dup")
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        ctx = PluginContext(services=services, config={}, plugin_name="dup_plugin")
        ctx.publish_metric("fps", 21.0)  # 'fps' объявлен фреймворком — чужое имя

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)
        assert _tree(services, "fps") == 8.0, "агрегат воркеров подменён публикацией в чужое имя"
        assert _polled_state(services)["fps"] == 8.0, "опрос разошёлся с деревом на имени-дубле"
        assert any("fps" in msg for msg in services.warnings()), (
            f"отсев чужого имени промолчал — тихий отсев неотличим от опечатки: {services.warnings()}"
        )

    def test_a_level_owned_by_ANOTHER_PLUGIN_is_rejected_too(self):
        """Сосед по процессу не может писать в имя чужого плагина.

        **Тест добавлен инъекцией, а не рассуждением, и это его главное свойство.**
        Инъекция И1 (проверку владельца заменить назад на членство в общем каталоге)
        оставила ЗЕЛЁНЫМИ оба теста П1 независимого тестера и соседний тест выше —
        потому что все трое сторожат имя ФРЕЙМВОРКА (``fps``), а его в дереве
        защищает не владение, а fail-safe порядок сборки: уровни плагинов ложатся
        первыми, агрегат фреймворка накрывает их сверху в том же dict'е, и чужое
        значение до merge просто не доживает.

        Здесь этой страховки нет по построению: оба участника — плагины, оба их
        уровня едут ОДНИМ проходом ``_collect_plugin_levels`` и ложатся в один и
        тот же словарь. Без проверки владельца победил бы порядок обхода dict'а —
        то есть порядок вызовов ``publish_metric``, который никто настройкой не
        считает. Ровно тот класс, который задача и чинит.

        Судится значением в дереве и в опросе, а не отсутствием вызова.
        """
        services, hb = _boot(name="neighbours")
        owner_ctx = PluginContext(services=services, config={}, plugin_name="plugin_a")
        owner_ctx.declare_metric("shared_gauge")
        owner_ctx.publish_metric("shared_gauge", 11.0)
        # Сосед публикует в ЧУЖОЕ имя ПОЗЖЕ — при победе порядка выиграл бы он.
        PluginContext(services=services, config={}, plugin_name="plugin_b").publish_metric("shared_gauge", 99.0)

        _tick_levels(hb)

        assert _tree(services, "shared_gauge") == pytest.approx(11.0), (
            "сосед по процессу подменил уровень чужого плагина — владение не стережётся "
            "там, где fail-safe порядок не помогает"
        )
        assert _polled_state(services)["shared_gauge"] == pytest.approx(11.0), (
            "опрос разошёлся с деревом на имени, которое перехватил сосед"
        )
        said = [msg for msg in services.warnings() if "shared_gauge" in msg]
        assert len(said) == 1 and "plugin_b" in said[0], (
            f"перехват чужого имени промолчал либо не назвал перехватчика: {services.warnings()}"
        )

    def test_the_rejection_voice_names_all_three_participants(self):
        """В голосе — имя, публикатор и владелец: три разных диагноза, три действия."""
        services, hb = _boot(name="voice")
        PluginContext(services=services, config={}, plugin_name="loud_plugin").publish_metric("fps", 1.0)

        _tick_levels(hb)

        said = [msg for msg in services.warnings() if "fps" in msg]
        assert len(said) == 1, said
        assert "loud_plugin" in said[0], said
        assert "telemetry" in said[0], f"владелец имени не назван — не отличить чужое имя от опечатки: {said[0]}"


# --------------------------------------------------------------------------- #
# Вложенный контекст.
# --------------------------------------------------------------------------- #
class TestSubPluginContext:
    def test_default_roads_are_named_noops(self):
        sub = SubPluginContext()
        assert sub.declare_metric("orphan") == "orphan", "заглушка обязана вернуть то же имя"
        sub.publish_metric("orphan", 1.0)

    def test_default_publish_accepts_the_exact_signature(self):
        """Именованный вызов по эталонной сигнатуре не имеет права падать.

        Урок четырёх заглушек 1.1 дословно: общая заглушка «по форме» роняла
        ``TypeError: unexpected keyword argument`` ровно там, где ставилась ради
        безопасности.
        """
        SubPluginContext().publish_metric(name="orphan", value=2.0)
        assert SubPluginContext().declare_metric(name="orphan") == "orphan"

    def test_from_parent_forwards_both_roads_and_they_work(self):
        services, hb = _boot(name="sub")
        parent = PluginContext(services=services, config={}, plugin_name="parent_plugin")
        sub = SubPluginContext.from_parent(parent, config={"nested": True})

        sub.declare_metric("sub_level")
        sub.publish_metric("sub_level", 3.5)
        _tick_levels(hb)
        assert _tree(services, "sub_level") == pytest.approx(3.5), (
            "дороги проброшены по имени, но не делегируют в механизм родителя"
        )

    def test_sub_level_is_owned_by_the_parent_plugin(self):
        """Вложенный объявляет ОТ ИМЕНИ родителя — своего владельца у него нет."""
        services, _hb = _boot(name="sub2")
        parent = PluginContext(services=services, config={}, plugin_name="parent_plugin2")
        SubPluginContext.from_parent(parent).declare_metric("sub_owned")
        parent.declare_metric("sub_owned")  # тот же владелец — не конфликт


# --------------------------------------------------------------------------- #
# Отключаемость и стойкость разъёма.
# --------------------------------------------------------------------------- #
class TestDisabledAndHostile:
    def test_publish_without_heartbeat_is_a_noop_not_an_error(self):
        services = MockProcessServices(name="bare")
        ctx = PluginContext(services=services, config={}, plugin_name="bare_plugin")
        ctx.declare_metric("bare_level")
        ctx.publish_metric("bare_level", 1.0)  # ни исключения, ни требований к дереву

    def test_services_refusing_the_port_give_one_named_warning(self):
        """``__slots__``-дубль не принимает атрибут — молчать об этом нельзя."""

        class _Slotted(MockProcessServices):
            """Дубль, который порт принимает на сборке и ОТКАЗЫВАЕТ потом.

            Отказывать с самого начала нельзя: базовый ``__init__`` сам ставит
            ``plugin_levels = None`` (порт обязан существовать всегда), и дубль
            не собрался бы вовсе — тест падал бы на конструкторе, ничего не
            проверив.
            """

            _sealed = False

            def __setattr__(self, key: str, value: Any) -> None:
                if key == PLUGIN_LEVELS_ATTR and self._sealed:
                    raise AttributeError(key)
                super().__setattr__(key, value)

        services = _Slotted(name="slotted")
        services._sealed = True
        ctx = PluginContext(services=services, config={}, plugin_name="slotted_plugin")
        ctx.declare_metric("slotted_level")
        ctx.publish_metric("slotted_level", 1.0)
        ctx.publish_metric("slotted_level", 2.0)
        said = [msg for msg in services.logs if msg.get("level") == "WARNING" and "slotted_level" in msg.get("msg", "")]
        assert len(said) == 1, f"ожидали ровно один голос, получили {len(said)}"

    def test_a_non_numeric_value_does_not_break_the_collector(self):
        """Прикладная опечатка в значении не имеет права уронить телеметрию тика."""
        services, hb = _boot(name="text")
        ctx = PluginContext(services=services, config={}, plugin_name="text_plugin")
        ctx.declare_metric("text_level")
        ctx.publish_metric("text_level", "не число")
        _tick_levels(hb)
        assert _tree(services, "text_level") == "не число"

    def test_empty_store_publishes_nothing(self):
        """Ни одного уровня — ни одного merge: не грузим дерево пустым сообщением."""
        services, hb = _boot(name="empty")
        PluginContext(services=services, config={}, plugin_name="empty_plugin").publish_metric("x", 1)
        before = len(services._state_proxy.merges)
        _tick_levels(hb)  # 'x' не объявлен
        assert len(services._state_proxy.merges) == before


# --------------------------------------------------------------------------- #
# Два потока вокруг одного хранилища.
# --------------------------------------------------------------------------- #
#: Сколько имён писатель успевает добавить до сброса. Предохранитель, а не
#: параметр механизма: без него тест падал не тем, что ищет, — ``MemoryError``.
#: Воспроизведено 2026-08-16 на этом же тесте после Р3.5-11: запись стала парой
#: ``(значение, публикатор)``, чтение — двумя проходами, писатель за 80 с успевал
#: съесть память раньше, чем читатель заканчивал свои 2000 копий. Сброс через
#: ``retract`` держит РОСТ (новые ключи — то, что и поднимает RuntimeError)
#: бесконечным при ограниченном размере.
_GROWTH_WINDOW = 20_000


class TestConcurrency:
    def test_a_copy_survives_a_writer_growing_the_store(self):
        """Без лока ``dict(...)`` растущего словаря поднимает RuntimeError.

        Писатель здесь — отдельный поток, как в проде (воркер плагина против
        потока heartbeat), и он именно РАСТИТ словарь новыми ключами: перезапись
        существующего ключа копию не ломает, и тест на ней был бы вакуумным.

        Проверяются ОБА чтения. ``publications`` — вход сборщика тика и опроса,
        то есть тот, чей отказ погасил бы телеметрию; ``snapshot`` — производная
        проекция, у которой между взятием копии и её обходом лока уже нет, и
        именно поэтому она обязана обходить КОПИЮ, а не живой словарь.
        ``retract`` крутится тем же потоком — третий писатель, появившийся с
        Р3.5-14, ходит в то же хранилище.
        """
        store = PluginLevels()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                store.publish(f"level_{i}", i, "writer_plugin")
                i += 1
                if i >= _GROWTH_WINDOW:
                    store.retract("writer_plugin")
                    i = 0

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for n in range(2000):
                try:
                    store.publications() if n % 2 else store.snapshot()
                except BaseException as exc:  # noqa: BLE001 — ловим ровно то, что ищем
                    errors.append(exc)
                    break
        finally:
            stop.set()
            thread.join(timeout=5.0)
        assert not thread.is_alive(), "поток-писатель не завершился — тест повис бы"
        assert not errors, f"чтение хранилища не пережило конкурентную запись: {errors!r}"


# --------------------------------------------------------------------------- #
# Сборщик как чистая функция — без heartbeat и без дерева.
# --------------------------------------------------------------------------- #
class TestCollector:
    def test_unowned_names_are_reported_sorted_and_not_published(self):
        payload, rejected = build_plugin_levels({("b_unknown", "pub_b"): 1, ("a_unknown", "pub_a"): 2}, None)
        assert payload == {}
        # Тройка целиком: имя, публикатор и владелец (None = не объявлено никем).
        assert rejected == (("a_unknown", "pub_a", None), ("b_unknown", "pub_b", None))

    def test_two_claimants_on_one_name_are_both_reported(self):
        """ОБА публикатора отброшены и ОБА названы — ни один не схлопнут в один.

        Вопрос, заданный вместе с ключом-парой: имя больше не уникально во входе,
        и «отброшено имя X» без публикатора не говорит оператору, КТО его
        перехватил. Схлопни сборщик две записи в одну — второй перехватчик стал
        бы невидим, а искать его пришлось бы грепом по всем плагинам процесса.
        Сортировка тоже проверяется: ключ теперь ПАРА, иначе порядок двух записей
        с одним именем зависел бы от обхода словаря.
        """
        payload, rejected = build_plugin_levels({("shared", "pub_b"): 2, ("shared", "pub_a"): 1}, None)
        assert payload == {}
        assert rejected == (("shared", "pub_a", None), ("shared", "pub_b", None))

    def test_a_foreign_owner_is_reported_with_the_owners_name(self):
        """Чужое имя и необъявленное — РАЗНЫЕ диагнозы, различимы третьим элементом."""
        _payload, rejected = build_plugin_levels({("fps", "самозванец"): 99.0}, None)
        assert len(rejected) == 1
        name, publisher, owner = rejected[0]
        assert (name, publisher) == ("fps", "самозванец")
        assert owner is not None and owner.startswith("multiprocess_framework."), owner

    def test_the_collector_does_not_mutate_its_input(self):
        levels = {("x", "p"): 1}
        build_plugin_levels(levels, None)
        assert levels == {("x", "p"): 1}

    def test_booleans_are_not_rounded_into_numbers(self):
        """``round(True, 1)`` вернул бы 1 — фронт, просочившийся в уровни, обязан
        остаться распознаваемым как фронт, а не превратиться в число."""
        services, _hb = _boot(name="bool")
        ctx = PluginContext(services=services, config={}, plugin_name="bool_plugin")
        ctx.declare_metric("bool_level")
        ctx.publish_metric("bool_level", True)
        payload, _ = build_plugin_levels({("bool_level", "bool_plugin"): True}, None)
        assert payload["bool_level"] is True


class TestWiringNotJustTheCollector:
    """Провод из ``_loop``, а не только сборщик.

    ДОБАВЛЕНО ВЛАДЕЛЬЦЕМ СПЕКИ (2026-08-16). Автор реализации назвал эту дыру сам:
    инъекция «убрать вызов публикатора уровней из ``_loop``» красила **ноль**
    тестов — и его набор, и приёмочный набор тестера зовут сборщик НАПРЯМУЮ.
    Механизм при этом остаётся идеальным, а система молча перестаёт публиковать:
    ровно класс «провод не проверен», который на этом проекте уже стоил находки
    «плагин не вызван молча».

    Адрес инъекции после Р3.5-12 — вызов ``_publish_telemetry_to_tree`` в ``_loop``
    (три прежних публикатора схлопнуты в один). Формулировка выше намеренно
    осталась про ЭФФЕКТ, а не про имя метода: имя менять можно, провод — нет.

    Тест судит ЭФФЕКТ на боевом пути: крутится настоящий ``_loop`` в потоке-демоне
    с дедлайном join (зависший тест хуже отсутствующего), и уровень обязан появиться
    в дереве без единого прямого вызова сборщика из теста.
    """

    def test_the_real_loop_publishes_plugin_levels(self):
        services, hb = _boot(name="wire")
        ctx = PluginContext(services=services, config={}, plugin_name="wire_plugin")
        ctx.declare_metric("wired_level")
        ctx.publish_metric("wired_level", 9.0)

        stop = threading.Event()
        pause = threading.Event()
        t = threading.Thread(target=hb._loop, args=(stop, pause), daemon=True)
        t.start()
        try:
            deadline = time.time() + 5.0
            pushed = None
            while time.time() < deadline:
                pushed = services._state_proxy.get("processes.wire.state.wired_level")
                if pushed is not None:
                    break
                time.sleep(0.05)
        finally:
            stop.set()
            t.join(timeout=5.0)
        assert not t.is_alive(), "поток _loop не завершился по stop_event за 5 с"
        assert pushed == 9.0, (
            f"боевой _loop не опубликовал уровень плагина (получили {pushed!r}) — "
            f"сборщик может быть исправен, а провод оборван"
        )


# --------------------------------------------------------------------------- #
# Р3.5-12 — три ловушки объединения трёх merge в один.
#
# Каждая — не гипотеза, а место, где прежний код имел ранний выход или политику,
# и где объединение могло их молча потерять. Судится ЧИСЛОМ вызовов merge и
# составом единственного payload'а, а не формой внутренних функций.
# --------------------------------------------------------------------------- #
class _ShmRouter:
    """Router с одним ненулевым счётчиком — чтобы группа ``shm`` реально ехала."""

    def get_shm_stats(self) -> dict:
        return {"frame_torn_reads": 3}


class _ZeroRouter:
    """Router со всеми нулями — политика публикатора обязана его промолчать."""

    def get_shm_stats(self) -> dict:
        return {}


def _boot_hb(services: _Services) -> ProcessHeartbeat:
    hb = ProcessHeartbeat(services)
    services._heartbeat = hb
    return hb


class TestOneMergePerTick:
    def _services_with_worker(self, name: str) -> _Services:
        services = _Services(name=name)
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        return services

    def test_workers_shm_and_levels_ride_one_merge(self):
        """Три источника → один merge и один путь ``processes.<name>``."""
        services = self._services_with_worker("one")
        services.router_manager = _ShmRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="one_plugin")
        ctx.declare_metric("one_level")
        ctx.publish_metric("one_level", 4.0)

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        path, data = services._state_proxy.merges[0]
        assert path == "processes.one"
        assert data["workers"]["w"]["status"] == "running"
        assert data["state"]["fps"] == 8.0
        assert data["state"]["one_level"] == 4.0
        assert data["state"]["shm"]["torn_reads"] == 3

    def test_no_workers_does_not_swallow_levels_and_shm(self):
        """ЛОВУШКА 1: прежний ранний выход по ``not workers`` жил в воркерном
        публикаторе и глотал только воркерные листья — ``shm`` и уровни ехали
        своими merge. В общей сборке тот же выход проглотил бы всё."""
        services = _Services(name="nw")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = _ShmRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="nw_plugin")
        ctx.declare_metric("nw_level")
        ctx.publish_metric("nw_level", 6.0)

        hb._publish_telemetry_to_tree({}, None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        _path, data = services._state_proxy.merges[0]
        assert "workers" not in data
        assert data["state"]["nw_level"] == 6.0
        assert data["state"]["shm"]["torn_reads"] == 3

    def test_all_zero_shm_still_does_not_load_the_tree(self):
        """ЛОВУШКА 2: «все счётчики нулевые → не грузим дерево» — политика
        ПУБЛИКАТОРА, и она обязана уцелеть внутри объединённой сборки, а не
        исчезнуть вместе со снятым методом. Соседний уровень при этом едет."""
        services = _Services(name="zero")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = _ZeroRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="zero_plugin")
        ctx.declare_metric("zero_level")
        ctx.publish_metric("zero_level", 1.0)

        hb._publish_telemetry_to_tree({}, None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        _path, data = services._state_proxy.merges[0]
        assert "shm" not in data["state"], data
        assert data["state"]["zero_level"] == 1.0

    def test_nothing_at_all_sends_zero_merges(self):
        """ЛОВУШКА 3: данных нет вовсе → НОЛЬ вызовов merge, а не пустой merge."""
        services = _Services(name="void")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = None
        hb = _boot_hb(services)

        hb._publish_telemetry_to_tree({}, None)

        assert services._state_proxy.merges == []

    def test_the_framework_aggregate_lies_on_top_of_plugin_levels(self):
        """Fail-safe порядок наложения (а НЕ политика разрешения конфликта).

        Спор за имя сюда не доходит — его снимает проверка владельца в сборщике,
        и это сторожит соседний тест. Здесь проверяется само расположение.

        **Покрывает РОВНО ОДИН случай из пяти** (ревью З1): порядок страхует
        только ``fps``/``latency_ms`` и только когда агрегат есть на этом же тике.
        Без воркеров, у ``effective_hz`` и у ``shm`` протёкшее значение доехало бы
        до дерева — измерено инъекцией, таблица в докстринге
        ``_publish_telemetry_to_tree``. Поэтому это тест ВТОРОЙ линии, а не
        доказательство защиты; единственный настоящий предохранитель — владение.
        Судится сборкой payload напрямую, потому что через боевой путь протечка
        (по построению отбора) не воспроизводится.
        """
        services = self._services_with_worker("order")
        hb = _boot_hb(services)
        # Подменяем шов сбора уровней так, будто отбор протёк и отдал 'fps'.
        hb._collect_plugin_levels = lambda allowed, *, voice: {"fps": 999.0}  # type: ignore[assignment]

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        _path, data = services._state_proxy.merges[0]
        assert data["state"]["fps"] == 8.0, f"протёкший уровень плагина лёг ПОВЕРХ агрегата фреймворка: {data['state']}"


# --------------------------------------------------------------------------- #
# Р3.5-14 — свежесть жизненным циклом.
# --------------------------------------------------------------------------- #
class _ShutdownPublishingPlugin(ProcessModulePlugin):
    """Плагин, который отдаёт ПОСЛЕДНЕЕ значение в собственном ``shutdown``.

    Не выдумка ради теста: ровно так устроен ``CapturePlugin`` — на остановке
    захвата он обнуляет частоту и публикует её, потому что следующего такта
    метрик уже не будет.
    """

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        ctx.declare_metric("dying_level")
        ctx.publish_metric("dying_level", 5.0)

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.publish_metric("dying_level", 0.0)


class TestLifecycleRetract:
    def test_retract_runs_after_the_plugins_own_shutdown(self):
        """Снятие ПОСЛЕ пользовательского ``shutdown``, а не до.

        До — и последнее значение, отданное в самом ``shutdown``, осталось бы
        висеть в дереве навсегда: снимать было бы уже нечего. Это единственный
        порядок, при котором работают обе половины.
        """
        services, _hb = _boot(name="dying")
        ctx = PluginContext(services=services, config={}, plugin_name="dying_plugin")
        plugin = _ShutdownPublishingPlugin()
        plugin.name = "dying_plugin"
        plugin._do_configure(ctx)
        store = getattr(services, PLUGIN_LEVELS_ATTR)
        assert store.snapshot() == {"dying_level": 5.0}

        plugin._do_shutdown(ctx)

        assert store.snapshot() == {}, (
            f"уровень пережил остановку плагина: {store.snapshot()} "
            "— снятие идёт ДО пользовательского shutdown либо не идёт вовсе"
        )

    def test_retract_takes_only_this_owners_levels(self):
        services, _hb = _boot(name="pair")
        base = PluginContext(services=services, config={})
        ctx_a = base.with_config({}, plugin_name="pair_a")
        ctx_b = base.with_config({}, plugin_name="pair_b")
        ctx_a.declare_metric("pair_level_a")
        ctx_b.declare_metric("pair_level_b")
        ctx_a.publish_metric("pair_level_a", 1.0)
        ctx_b.publish_metric("pair_level_b", 2.0)

        assert ctx_a._retract_metrics() == 1
        store = getattr(services, PLUGIN_LEVELS_ATTR)
        assert store.snapshot() == {"pair_level_b": 2.0}

    def test_retract_without_a_store_is_a_named_zero_not_an_error(self):
        """Процесс без телеметрии останавливает плагины как обычно."""
        services = MockProcessServices(name="bare_retract")
        ctx = PluginContext(services=services, config={}, plugin_name="bare_retract_plugin")
        assert ctx._retract_metrics() == 0

    def test_the_declaration_survives_the_retract(self):
        """Снимается ПУБЛИКАЦИЯ, не объявление: поднятый заново плагин объявится
        тем же владельцем (это не конфликт), а забытое объявление восстанавливать
        было бы некому."""
        services, hb = _boot(name="redeclare")
        ctx = PluginContext(services=services, config={}, plugin_name="redeclare_plugin")
        ctx.declare_metric("survivor_level")
        ctx.publish_metric("survivor_level", 3.0)
        ctx._retract_metrics()

        assert "survivor_level" in declared_metrics()
        ctx.publish_metric("survivor_level", 4.0)
        _tick_levels(hb)
        assert _tree(services, "survivor_level") == 4.0


# --------------------------------------------------------------------------- #
# Владелец считается в ОДНОМ месте — судится эффектом на боевой тройке.
# --------------------------------------------------------------------------- #
class TestOwnerIsComputedOnce:
    def test_declare_publish_and_retract_agree_on_the_owner(self):
        """Три дороги, один владелец. Разойдись хоть одна — уровень либо не
        поедет (владелец не равен публикатору), либо не снимется на остановке.
        Судится эффектом: объявил → уехало → сняли → исчезло."""
        services, hb = _boot(name="triple")
        ctx = PluginContext(services=services, config={}, plugin_name="triple_plugin")
        ctx.declare_metric("triple_level")
        ctx.publish_metric("triple_level", 7.0)

        _tick_levels(hb)
        assert _tree(services, "triple_level") == 7.0, "объявление и публикация разошлись во владельце"

        assert ctx._retract_metrics() == 1, "снятие разошлось во владельце с публикацией"
        assert _polled_state(services).get("triple_level") is None

    def test_a_context_without_a_plugin_name_owns_by_process_on_all_three(self):
        """Тот же треугольник для базового ctx (владелец — имя процесса)."""
        services, hb = _boot(name="proc_owner")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("proc_owned_level")
        ctx.publish_metric("proc_owned_level", 2.0)

        _tick_levels(hb)
        assert _tree(services, "proc_owned_level") == 2.0
        assert ctx._retract_metrics() == 1


# --------------------------------------------------------------------------- #
# Ключ-пара: перехватчик не может ни подменить, ни УНИЧТОЖИТЬ чужой уровень.
#
# Блокер, найденный инъекцией И1 (2026-08-17): хранилище ключевалось одним
# именем, публикация соседа затирала запись владельца, и сборщик отбрасывал
# затёртое по несовпадению владельца — лист исчезал ЦЕЛИКОМ. Перехватчик не мог
# подменить число, но мог его уничтожить одной опечаткой в имени.
# --------------------------------------------------------------------------- #
class TestPairKeyProtectsTheOwner:
    def test_the_interceptor_does_not_erase_the_owners_entry_in_the_store(self):
        """Уровень сборщика — следствие; здесь проверяется САМА ячейка хранилища.

        Тест на дереве (``..._owned_by_ANOTHER_PLUGIN_...``) покраснел бы и от
        неверного сборщика, и от затёртой ячейки — он не различает эти причины.
        Здесь адрес дефекта: обе записи обязаны СУЩЕСТВОВАТЬ порознь.
        """
        store = PluginLevels()
        store.publish("shared", 11.0, "plugin_a")
        store.publish("shared", 99.0, "plugin_b")

        pubs = store.publications()
        assert pubs[("shared", "plugin_a")] == 11.0, f"запись владельца затёрта соседом: {pubs}"
        assert pubs[("shared", "plugin_b")] == 99.0, pubs

    def test_two_claimants_neither_owning_are_both_rejected_and_both_voiced(self):
        """Ни один не владелец → в дереве листа нет, а голос есть по КАЖДОМУ.

        Вопрос 1 из поручения. Молчание про второго перехватчика было бы тем же
        тихим отсевом, который задача и убирает, только адресованным другому
        плагину.
        """
        services, hb = _boot(name="claimants")
        PluginContext(services=services, config={}, plugin_name="claimant_a").publish_metric("orphan_name", 1.0)
        PluginContext(services=services, config={}, plugin_name="claimant_b").publish_metric("orphan_name", 2.0)

        _tick_levels(hb)

        assert _tree(services, "orphan_name") is None
        said = " ".join(msg for msg in services.warnings() if "orphan_name" in msg)
        assert "claimant_a" in said and "claimant_b" in said, f"назван не каждый перехватчик: {services.warnings()}"

    def test_a_later_claimant_on_an_already_voiced_name_is_still_voiced(self):
        """Голос дедуплицируется по ПАРЕ (имя, публикатор), а не по имени.

        ДОБАВЛЕН ПОСЛЕ ПРОМАХА ПРЕДСКАЗАНИЯ (2026-08-17). Инъекция «дедуп по
        имени» дала НОЛЬ красных: соседний тест сажает обоих перехватчиков в ОДИН
        тик, где множество уже названных пусто, и оба варианта дедупа ведут себя
        одинаково. То есть тот тест сторожит «оба названы», но не сторожит ключ
        дедупа — расхождение названо, а не замазано.

        Разница видна только во ВРЕМЕНИ: перехватчик, появившийся ПОЗЖЕ (ленивый
        импорт, hot-apply рецепта), при дедупе по имени молча проглатывается —
        про его имя уже «сказано», хотя сказано было про другого виновника.
        """
        services, hb = _boot(name="late_claimant")
        PluginContext(services=services, config={}, plugin_name="early_thief").publish_metric("late_orphan", 1.0)
        _tick_levels(hb)
        assert any("early_thief" in m for m in services.warnings()), services.warnings()

        before = len(services.logs)
        PluginContext(services=services, config={}, plugin_name="late_thief").publish_metric("late_orphan", 2.0)
        _tick_levels(hb)

        fresh = [e["msg"] for e in services.logs[before:] if e["level"] == "WARNING"]
        assert any("late_thief" in m for m in fresh), f"поздний перехватчик того же имени промолчал: {fresh}"
        # А первый — повторно НЕ говорит: пара уже названа.
        assert not any("early_thief" in m for m in fresh), fresh

    def test_retracting_the_owner_does_not_surface_the_interceptors_value(self):
        """Вопрос 2: снятие владельца при живом перехватчике убирает лист.

        Опасность конкретна: если бы `retract` снимал ПО ИМЕНИ, а не по паре, он
        либо снёс бы и чужую запись (перехватчик молча «починился» бы), либо
        оставил её единственной — и после остановки владельца оператор увидел бы
        ЧУЖОЕ число под тем же путём, не узнав об этом ничем.
        """
        services, hb = _boot(name="retract_race")
        owner_ctx = PluginContext(services=services, config={}, plugin_name="owner_plugin")
        owner_ctx.declare_metric("guarded_level")
        owner_ctx.publish_metric("guarded_level", 11.0)
        PluginContext(services=services, config={}, plugin_name="thief_plugin").publish_metric("guarded_level", 99.0)

        _tick_levels(hb)
        assert _tree(services, "guarded_level") == pytest.approx(11.0), "предпосылка: владелец виден"

        assert owner_ctx._retract_metrics() == 1, "снято не ровно то, что опубликовал владелец"
        assert _polled_state(services).get("guarded_level") is None, (
            "после остановки владельца всплыло значение перехватчика"
        )
        # Запись перехватчика жива в хранилище, но наружу не идёт — отвергается
        # по владению, как и до снятия.
        assert store_of(services).publications() == {("guarded_level", "thief_plugin"): 99.0}

    def test_retract_takes_only_this_owners_rows_of_a_shared_name(self):
        """`retract` работает по ВТОРОМУ элементу ключа, а не по имени."""
        store = PluginLevels()
        store.publish("shared", 11.0, "plugin_a")
        store.publish("shared", 99.0, "plugin_b")
        store.publish("own", 1.0, "plugin_a")

        assert store.retract("plugin_a") == 2
        assert store.publications() == {("shared", "plugin_b"): 99.0}


def store_of(services):
    """Хранилище уровней процесса — читается тем же портом, что и у фреймворка."""
    return getattr(services, PLUGIN_LEVELS_ATTR)


# --------------------------------------------------------------------------- #
# Находки ревью 2026-08-17. Каждый тест судит ТО, ЧТО ПРОПУСТИЛ прежний объектив:
# дерево вместо payload (Н1), отказную дорогу вместо счастливой (Н2), путь листа
# вместо значения (Н3), предел вместо факта (З2), боевую форму merge вместо
# удобной (З3).
# --------------------------------------------------------------------------- #
class TestRetractedLevelLeavesTheTree:
    """Н1: «уровень мёртвого исчезает» — судится ДЕРЕВОМ, а не payload'ом.

    Прежний П6 собирал дерево ТОЛЬКО из merge'ей ПОСЛЕ остановки, поэтому
    «payload чист» и «в дереве ничего нет» были для него одним и тем же
    утверждением. Объектив теста совпал с объективом инъекции — дыру не увидел
    ни тест, ни инъекция. Здесь дерево живёт через ОБА тика.
    """

    def test_the_tree_stops_reading_after_the_owner_is_stopped(self):
        services, hb = _boot(name="dead_owner")
        ctx = PluginContext(services=services, config={}, plugin_name="mortal_plugin")
        plugin = _MinimalHazardPlugin()
        plugin.name = "mortal_plugin"
        ctx.declare_metric("probe_level")
        ctx.publish_metric("probe_level", 12.5)
        plugin._do_configure(ctx)

        _tick_levels(hb)
        assert _tree(services, "probe_level") == pytest.approx(12.5), "предпосылка: значение в дереве"

        plugin._do_shutdown(ctx)
        _tick_levels(hb)

        assert _tree(services, "probe_level") is None, (
            f"лист живёт в дереве после остановки владельца: {_tree(services, 'probe_level')!r} — "
            "снятие публикации дереву ничего не сказало"
        )

    def test_the_notice_stops_after_the_bounded_reassertion(self):
        """«Показания нет» — КОНЕЧНЫЙ факт, а не уровень.

        ОБНОВЛЕНО S-1 (2026-08-17). Прежняя редакция пинила «ровно один такт», и
        это было верное утверждение неверного контракта: имя вычёркивалось ДО
        ``proxy.merge``, обёрнутого в ``except Exception``, поэтому ЛЮБОЙ отказ
        доставки хоронил снятие навсегда и оставлял в дереве мёртвое число.
        Тест не удалён, а переведён на новую границу: повтор остался КОНЕЧНЫМ
        (``RETRACTION_REASSERT_TICKS``), и исходная опасность — «нет показания»
        превратилось в вечный уровень на мёртвом пути — держится по-прежнему,
        просто предел теперь не 1, а 3.

        Судится не только «после предела тихо», но и «до предела говорит»: без
        нижней границы тест был бы зелёным и на реализации, которая не шлёт
        снятие ВОВСЕ.
        """
        from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
            RETRACTION_REASSERT_TICKS,
        )

        services, hb = _boot(name="once_only")
        ctx = PluginContext(services=services, config={}, plugin_name="once_plugin")
        ctx.declare_metric("once_level")
        ctx.publish_metric("once_level", 3.0)
        _tick_levels(hb)
        ctx._retract_metrics()

        for i in range(RETRACTION_REASSERT_TICKS):
            before = len(services._state_proxy.merges)
            _tick_levels(hb)
            assert len(services._state_proxy.merges) > before, (
                f"такт {i + 1} из {RETRACTION_REASSERT_TICKS}: снятие перестало утверждаться "
                "раньше предела — потеря одного сообщения снова хоронила бы лист навсегда"
            )
            assert services._state_proxy.merges[-1][1].get("state", {}).get("once_level", "нет") is None, (
                f"такт {i + 1}: в payload нет утверждения None по 'once_level': {services._state_proxy.merges[-1][1]!r}"
            )

        after_notice = len(services._state_proxy.merges)
        _tick_levels(hb)
        _tick_levels(hb)

        assert len(services._state_proxy.merges) == after_notice, (
            f"после {RETRACTION_REASSERT_TICKS} успешных утверждений тик снова шлёт merge — "
            "«нет показания» превратилось в бесконечную дельту на мёртвый путь"
        )

    def test_a_relaunched_plugin_beats_the_pending_notice(self):
        """Живое значение на том же тике важнее отложенного «нет показания».

        Плагин может быть поднят заново между снятием и тиком; обнулить его
        свежее показание значило бы заменить одну ложь другой.
        """
        services, hb = _boot(name="relaunch")
        ctx = PluginContext(services=services, config={}, plugin_name="phoenix_plugin")
        ctx.declare_metric("phoenix_level")
        ctx.publish_metric("phoenix_level", 1.0)
        ctx._retract_metrics()
        ctx.publish_metric("phoenix_level", 2.0)  # поднялся заново до тика

        _tick_levels(hb)

        assert _tree(services, "phoenix_level") == pytest.approx(2.0)

    def test_the_notice_is_not_gated(self):
        """Гейт управляет ЧАСТОТОЙ уровня, а не однократным снятием.

        Пропусти снятие через гейт — и у выключенной метрики лист остался бы
        навсегда с мёртвым числом, то есть гейт порождал бы ту самую ложь,
        которую снятие убирает.
        """
        services, hb = _boot(name="gated_retract")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_mortal")
        ctx.declare_metric("gated_dead_level")
        ctx.publish_metric("gated_dead_level", 5.0)
        _tick_levels(hb)
        assert _tree(services, "gated_dead_level") == pytest.approx(5.0)

        ctx._retract_metrics()
        hb.reconfigure_telemetry({"metrics": {"gated_dead_level": {"enabled": False}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=0.0))

        assert _tree(services, "gated_dead_level") is None, (
            "закрытый гейт съел снятие — лист остался с мёртвым числом навсегда"
        )


class _BoomPlugin(ProcessModulePlugin):
    """Плагин, чей ``shutdown`` бросает. Не гипотеза: «камера не отпустила устройство»."""

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        ctx.declare_metric("boom_level")
        ctx.publish_metric("boom_level", 7.7)

    def shutdown(self, ctx: PluginContext) -> None:
        raise RuntimeError("камера не отпустила устройство")


class TestShutdownFailureStillRetracts:
    """Н2: отказная дорога остановки.

    Прежняя редакция ставила снятие ПОСЛЕ незавёрнутого ``self.shutdown(ctx)``,
    и бросок оставлял уровни навсегда: ``STOPPED`` не наступал, оркестратор
    бросок логировал и шёл дальше, тики публиковали мёртвое значение. То есть
    симптом «камера остановлена, а частота идёт» воскресал ровно там, где
    диагностика нужнее всего.
    """

    def test_levels_are_retracted_even_when_shutdown_raises(self):
        services, hb = _boot(name="boom")
        ctx = PluginContext(services=services, config={}, plugin_name="boom_plugin")
        plugin = _BoomPlugin()
        plugin.name = "boom_plugin"
        plugin._do_configure(ctx)
        _tick_levels(hb)
        assert _tree(services, "boom_level") == pytest.approx(7.7), "предпосылка"

        with pytest.raises(RuntimeError, match="камера не отпустила"):
            plugin._do_shutdown(ctx)

        # Бросок ушёл наружу как раньше — состояние НЕ STOPPED.
        assert plugin.state != PluginState.STOPPED
        # ...но уровни сняты, и дерево об этом узнало.
        assert getattr(services, PLUGIN_LEVELS_ATTR).publications() == {}
        _tick_levels(hb)
        assert _tree(services, "boom_level") is None, "уровень пережил отказавший shutdown — снятие стоит вне finally"


class TestDottedLevelNameIsRefused:
    """Н3: точка в имени уровня — отказ, а не резидуал.

    Объединение трёх merge в один сделало достижимыми ОБЕ ветки резолва точки
    (литеральный ключ на первом тике, вложенный путь со второго), и в дереве
    оставался вечно-мёртвый лист-двойник без голоса. Двойника добавила эта
    задача — она его и закрывает.
    """

    def test_declare_refuses_a_dotted_name_and_says_why(self):
        services, _hb = _boot(name="dotted")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin")
        with pytest.raises(ValueError) as exc:
            ctx.declare_metric("a.b.c")
        text = str(exc.value)
        assert "a.b.c" in text and "точку" in text, text
        assert "a_b_c" in text, f"отказ не предложил годного имени: {text}"

    def test_a_dotted_name_never_reaches_the_tree(self):
        """Отказ на объявлении достаточен: необъявленное имя до дерева не доходит.

        Второй guard в ``publish_metric`` не нужен — публикация в необъявленное
        имя уже отвергается по владению и получает голос. Проверяется свойство,
        а не отсутствие второго guard'а.
        """
        services, hb = _boot(name="dotted2")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin2")
        ctx.publish_metric("x.y", 1.0)  # объявить нельзя, публикуем всё равно

        _tick_levels(hb)

        assert _tree(services, "x.y") is None
        assert services._state_proxy.get("processes.dotted2.state.x") is None
        assert any("x.y" in msg for msg in services.warnings()), services.warnings()

    def test_stats_plane_keeps_dotted_names(self):
        """Ограничение — только у уровней: в stats имя путём дерева не становится."""
        services, _hb = _boot(name="dotted3")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin3")
        ctx.gauge("capture.fps", 12.5)  # не бросает — плоскость другая


class TestRejectionVoiceHasACeiling:
    """З2: голос обязан назвать виновника, а не воспроизвести его вход."""

    def test_a_flood_of_rejections_gives_one_bounded_line(self):
        services, hb = _boot(name="flood")
        ctx = PluginContext(services=services, config={}, plugin_name="flood_plugin")
        for i in range(200):
            ctx.publish_metric(f"flood_level_{i}", float(i))

        _tick_levels(hb)

        said = [msg for msg in services.warnings() if "flood_level_" in msg]
        assert len(said) == 1, f"ожидали одну строку, получили {len(said)}"
        assert len(said[0]) < 2000, f"строкаWARNING разрослась до {len(said[0])} символов"
        assert "и ещё" in said[0], f"масштаб отсева потерян — хвоста нет: {said[0][-200:]}"
        assert services._state_proxy.merges == [], "необъявленные имена уехали в дерево"


# --------------------------------------------------------------------------- #
# З3 — форма merge, которую реально шлёт тик, а не удобная для теста.
#
# Приёмочный П10 мержит прямо в ``processes.<p>.state`` и потому измеряет
# per-leaf дельты всегда. Тик шлёт ДРУГОЕ: ``merge("processes.<p>",
# {"state": {...}})`` — на один уровень выше. На СВЕЖЕМ поддереве это даёт одну
# ГРУБУЮ дельту, и разница видна только здесь.
# --------------------------------------------------------------------------- #
class _CapturingRouterZ3:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        self.sent.append(msg)

    def register_message_handler(self, key, handler, expects_full_message=True) -> None:
        pass


def _delta_paths(router: _CapturingRouterZ3, subscriber: str = "watcher") -> list[str]:
    out: list[str] = []
    for msg in router.sent:
        if msg.get("targets") == [subscriber]:
            out.extend(d["path"] for d in msg["data"]["deltas"])
    router.sent.clear()
    return sorted(out)


class TestProductionMergeShapeDeltas:
    def test_first_tick_gives_one_coarse_delta_then_per_leaf(self):
        """Первый тик на свежем поддереве — ОДНА грубая дельта, дальше per-leaf.

        Следствие названо, а не замаскировано: путь ``processes.<p>.state`` имеет
        ТРИ части, а сток телеметрии берёт только ``len(parts) >= 4``
        (``Plugins/io/telemetry_sink/plugin.py``), поэтому первый тик после старта
        процесса он пропускает целиком. До объединения merge это касалось
        ``fps``/``latency_ms`` (они и раньше ехали под ``processes.<p>``), а
        группа ``shm`` мержилась ГЛУБЖЕ (``…state.shm``) и была per-leaf с первого
        тика — теперь она едет вместе с остальными. Один тик, не поток.
        """
        from multiprocess_framework.modules.state_store_module.core.delta import (
            STATE_ENVELOPE_MARKER,
        )
        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        router = _CapturingRouterZ3()
        mgr = StateStoreManager(router=router)
        mgr.initialize()
        try:
            mgr.subscription_manager.subscribe("processes.P.**", "watcher")

            def _tick(payload: dict) -> list[str]:
                mgr.handle_state_merge(
                    {
                        "path": "processes.P",
                        "data": {"state": payload},
                        "source": "hb",
                        STATE_ENVELOPE_MARKER: True,
                    }
                )
                mgr.dispatcher._flush_once()
                return _delta_paths(router)

            first = _tick({"fps": 8.1, "capture_fps": 12.5})
            second = _tick({"fps": 9.1, "capture_fps": 13.5})
        finally:
            mgr.shutdown()

        assert first == ["processes.P.state"], (
            f"первый тик дал не одну грубую дельту, а {first} — следствие в ADR описано неверно"
        )
        assert second == ["processes.P.state.capture_fps", "processes.P.state.fps"], second
        # Именно тот предикат, по которому сток отбирает записи.
        assert len(first[0].split(".")) == 3, first
        assert all(len(p.split(".")) >= 4 for p in second), second
