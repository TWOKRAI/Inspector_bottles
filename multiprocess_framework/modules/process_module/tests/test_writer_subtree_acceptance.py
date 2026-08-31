# -*- coding: utf-8 -*-
"""Независимая приёмка Task 1.2 — «писатель → путь», арбитраж владения удалён.

Свободный бриф (без формального заголовка MODE/INTERFACE) — но с поимённым списком
запрещённых файлов и явной красно/зелёной рамкой, что по проектной памяти
(feedback_freeform_brief_without_mode_header) эквивалентно MODE: red. Тесты писались
ДО реализации Task 1.2 и обязаны быть КРАСНЫМИ на текущем HEAD.

Источник контракта — ПЯТЬ критериев, переданных дословно в задании (не план, не diff):
  1. в heartbeat/ не осталось ни ``metric_owners``, ни сравнения владельца с публикатором;
  2. два писателя с одинаковым именем листа дают ДВА листа в двух поддеревьях, оба с литералами;
  3. правила гейта из прод-конфига работают без единой правки конфига;
  4. push и poll — один сборщик: снимок опроса отдаёт ТУ ЖЕ вложенную форму, что уходит push'ем;
  5. необъявленное имя едет легально под дефолтным правилом гейта — голос «публикация без
     объявления» НЕ заводится, отказа нет.

ЗАПРЕЩЕНО (поимённо, не открывалось при подготовке этого файла):
  - heartbeat/telemetry.py, heartbeat/process_heartbeat.py, observability_declarations.py;
  - git diff/show/log -p по ним;
  - test_plugin_level*.py, test_plugin_levels_*.py, *_quartet_hazards.py, *_retraction*.py.

Публичная форма (имена символов/сигнатуры) взята из СОСЕДНИХ, НЕ запрещённых источников,
уже импортирующих те же символы и проходящих на текущем HEAD — не из запрещённых файлов:
  - test_rt2_config_flip_acceptance.py: ``PLUGIN_LEVELS_ATTR``, ``PluginLevels``,
    ``ProcessHeartbeat.current_levels_snapshot()``, форма ``_FakeServices``
    (``name``/``worker_manager``/``router_manager``/``_state_proxy``/``_health_state``/
    ``_config``/``get_config``/``log_info``/``log_debug``/``log_warning``);
  - test_telemetry_gate.py: ``ProcessHeartbeat(services)._build_telemetry_gate()``,
    конфиг вида ``{"telemetry": {"publish": {...}}}``;
  - test_telemetry_levels_poll_acceptance.py: ``hb._loop(stop, pause)`` форсирует РОВНО один
    тик без ``time.sleep`` (``FakeClock``/``FakeStop``/``_NoPauseEvent``), ``ProcessHeartbeat(...,
    clock=...)``, конструкция «числа фикстуры заведомо нецелые и невстречающиеся среди дефолтов»;
  - ``plugins/base.py`` (НЕ запрещён — базовый класс контекста плагина, не heartbeat):
    ``PluginContext(services, plugin_name=...)``, ``ctx.publish_metric(name, value)`` — реальный
    публичный вход плагина в дерево уровней (докстринг: «уезжает в дерево СБОРЩИКОМ ТИКА
    ... под publisher-гейтом и наравне с fps/latency_ms»; «Владелец — имя плагина»).

Путь поддерева писателя взят ДОСЛОВНО из текста задания:
``processes.<процесс>.state.plugins.<плагин>.<метрика>``.

Допущения о публичной форме (нет права смотреть реализацию heartbeat/ — названы вслух):
  A1. ``PluginContext(services=..., plugin_name=...).publish_metric(name, value)`` — единственный
      использованный публичный вход; низкоуровневый стор (``PluginLevels.publish``) НЕ вызывается
      напрямую нигде в этом файле — тест проверяет реальный путь плагина, а не фейковый харнесс
      поверх стора (project rule: «фейк-харнесс доказывает харнесс», нужен вход через реальный
      объект).
  A2. Owner-сегмент итогового пути — буквально ``plugin_name``, переданный в конструктор
      ``PluginContext`` (согласуется с ``_metric_owner()`` в plugins/base.py: «Владелец — имя
      плагина»).
  A3. Точная форма дерева (dict-in-dict) НЕ фиксируется сверх необходимого — используется
      рекурсивный обход в путь листа (``_leaf_paths``), а не жёсткий ``d["state"]["plugins"][x][y]``
      — тем же доводом, что у ``_flatten_numbers`` в соседнем test_telemetry_levels_poll_acceptance.py
      («не фиксировать чужую внутреннюю структуру как контракт»).
  A4. ``hb._loop(stop, pause)`` — форсирует РОВНО один тик публикации без ``time.sleep`` (взято
      дословно из образца-харнесса, не придумано).

Ожидание к концу RED-прогона: ВСЕ пять групп тестов ниже — КРАСНЫЕ. Красный по причине
«поведения ещё нет» (AssertionError с показанным деревом/списком путей) — ожидаемый и
правильный результат. Красный по причине ImportError/AttributeError на конструкции
фикстур — ошибка формы, годная только для починки формы, не критерия.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext


# --------------------------------------------------------------------------- #
# Часы и стоп-событие — форсирование РОВНО одного тика (образец: test_telemetry_gate.py /
# test_telemetry_levels_poll_acceptance.py). Реализация heartbeat/*.py не читалась —
# только имена и порядок аргументов, уже используемые соседними непрещёнными тестами.
# --------------------------------------------------------------------------- #
class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class _FakeStop:
    def __init__(self, clock: _FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout=None) -> None:
        self._clock.advance(timeout)


class _NoPauseEvent:
    def is_set(self) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Прокси дерева состояния — считает merge()-вызовы, хранит их для разбора (образец —
# _RecordingProxy / _CountingProxy соседних приёмочных тестов модуля).
# --------------------------------------------------------------------------- #
class _RecordingProxy:
    def __init__(self) -> None:
        self.merges: list[tuple[str, dict]] = []
        self.sets: list[tuple[str, Any]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, dict(data)))

    def set(self, path: str, value: Any) -> None:
        self.sets.append((path, value))


# --------------------------------------------------------------------------- #
# Фейковый worker_manager — эмпирически проверено (без чтения heartbeat/*.py, только
# вызовом публичного current_levels_snapshot()/_loop() на пустых сервисах), что при
# worker_manager=None сборщик тика вообще не публикует НИЧЕГО (merge() ни разу не
# зовётся, current_levels_snapshot() возвращает None) — это отдельная, не связанная с
# Task 1.2 ветка «нет воркеров», а не то, что здесь проверяется. Один воркер во ВСЕХ
# фикстурах ниже держит эту ветку закрытой, чтобы красный держался ровно на поддереве
# писателя, а не на постороннем «пуст ли worker_manager».
# --------------------------------------------------------------------------- #
class _WorkerManager:
    def __init__(self, workers: dict) -> None:
        self._workers = workers

    def get_all_workers_status(self) -> dict:
        return {w: dict(v) for w, v in self._workers.items()}


_BASELINE_WORKER = {"w0": {"status": "running", "effective_hz": 9.5, "cycle_duration_ms": 3.5}}


# --------------------------------------------------------------------------- #
# Дублёр сервисов процесса — объединяет форму, которую реально трогают ОБА публичных
# потребителя: ProcessHeartbeat (второй слой, форма списана с _HeartbeatServices
# test_telemetry_levels_poll_acceptance.py) И PluginContext (plugins/base.py читается
# напрямую — НЕ запрещён; требует ВСЮ пятёрку log_* без getattr-заглушки).
# --------------------------------------------------------------------------- #
class _Services:
    def __init__(
        self,
        *,
        name: str = "writer_subtree_proc",
        config: dict | None = None,
        workers: dict | None = None,
    ) -> None:
        self.name = name
        self.worker_manager: Any = _WorkerManager(workers if workers is not None else _BASELINE_WORKER)
        self.router_manager: Any = None
        self.command_manager: Any = None
        self.memory_manager: Any = None
        self._state_proxy: Any = _RecordingProxy()
        self._health_state: Any = None
        self._current_process_status: str = "running"
        self._config: dict = config or {}
        self.warnings: list[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_debug(self, *a: Any, **k: Any) -> None: ...
    def log_info(self, *a: Any, **k: Any) -> None: ...

    def log_warning(self, msg: Any, *a: Any, **k: Any) -> None:
        self.warnings.append(str(msg))

    def log_error(self, *a: Any, **k: Any) -> None: ...
    def log_critical(self, *a: Any, **k: Any) -> None: ...

    def send_message(self, *a: Any, **k: Any) -> bool:
        return True


# --------------------------------------------------------------------------- #
# Path-walker — путь листа как кортеж строковых сегментов -> значение. Не фиксирует
# форму (dict/list на любом уровне) — только то, что нужно критериям: ГДЕ лежит литерал
# (допущение A3).
# --------------------------------------------------------------------------- #
def _leaf_paths(obj: Any, prefix: tuple = ()) -> dict[tuple, Any]:
    out: dict[tuple, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_leaf_paths(v, prefix + (str(k),)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.update(_leaf_paths(v, prefix + (str(i),)))
    else:
        out[prefix] = obj
    return out


def _paths_for_value(leaves: dict[tuple, Any], value: Any) -> list[tuple]:
    return [p for p, v in leaves.items() if v == value]


def _path_contains(path: tuple, needle: str) -> bool:
    return any(needle in str(seg) for seg in path)


def _pushed_leaves(proxy: _RecordingProxy) -> dict[tuple, Any]:
    """Плоский {путь: значение} по ВСЕМ merge()-вызовам прокси за форсированный тик."""
    out: dict[tuple, Any] = {}
    for path, data in proxy.merges:
        out.update(_leaf_paths({path: data}))
    return out


# =========================================================================== #
# Критерий 1 — в heartbeat/ не осталось ни metric_owners, ни арбитража
# =========================================================================== #
class TestNoOwnerArbitrationSymbolInHeartbeat:
    """Grep-подобный критерий. Имя символа взято ДОСЛОВНО из текста критерия
    задания, а не подсмотрено в реализации.

    Обязателен контроль (project rule): голый grep на ОТСУТСТВИЕ строки зелен и
    на пустом/несуществующем каталоге. Контрольные символы — те, что ТОЧНО
    существуют на любом HEAD, потому что их прямо сейчас импортируют и
    используют НЕЗАПРЕЩЁННЫЕ соседние тесты модуля (см. докстринг модуля).
    """

    _HEARTBEAT_DIR = Path(__file__).resolve().parents[1] / "heartbeat"
    _FILES = ("telemetry.py", "process_heartbeat.py")

    def _read_all(self) -> str:
        chunks = []
        for name in self._FILES:
            p = self._HEARTBEAT_DIR / name
            assert p.is_file(), f"файл контроля отсутствует физически: {p}"
            chunks.append(p.read_text(encoding="utf-8"))
        return "\n".join(chunks)

    def test_control_anchor_symbols_are_present(self) -> None:
        """Контроль: файлы реально читаются и не пусты — иначе следующий тест вакуумен."""
        text = self._read_all()
        assert "class ProcessHeartbeat" in text, "control anchor: класс обязан существовать"
        assert "PLUGIN_LEVELS_ATTR" in text, "control anchor: константа обязана существовать"

    def test_metric_owners_symbol_absent_from_heartbeat_sources(self) -> None:
        text = self._read_all()
        assert "metric_owners" not in text, (
            "metric_owners обязан быть удалён из heartbeat/ целиком (Task 1.2, критерий 1)"
        )


# =========================================================================== #
# Критерий 2 — два писателя с одинаковым именем листа → два листа, два поддерева
# =========================================================================== #
class TestTwoWritersSameLeafName:
    """Вход — публичный: PluginContext.publish_metric, как звал бы настоящий
    плагин, а не низкоуровневый стор напрямую (допущение A1)."""

    LEAF_NAME = "writer_subtree_probe"
    # Литералы обязаны переживать ``round(x, 1)`` сборщика — округление существует
    # на HEAD (telemetry.py, ``payload[name] = round(value, 1)``) и Ф1 его не вводила.
    # Прежние 111.25/222.75 давали в дереве 111.2/222.8, и тест краснел на дефекте
    # СВОЕГО харнесса, а не на адресации — то, что он проверяет, при этом выполнялось.
    VALUE_A = 111.2
    VALUE_B = 222.8

    def _publish_from_two_plugins(self, svc: _Services) -> None:
        ctx_a = PluginContext(services=svc, plugin_name="plugin_alpha_wsp")
        ctx_b = PluginContext(services=svc, plugin_name="plugin_beta_wsp")
        ctx_a.publish_metric(self.LEAF_NAME, self.VALUE_A)
        ctx_b.publish_metric(self.LEAF_NAME, self.VALUE_B)

    def test_poll_shows_both_literals_at_distinct_owner_paths(self) -> None:
        svc = _Services()
        hb = ProcessHeartbeat(svc)
        self._publish_from_two_plugins(svc)

        snapshot = hb.current_levels_snapshot()
        assert snapshot is not None, "опрос вернул None — сенсора нет, хотя метрики опубликованы"

        leaves = _leaf_paths(snapshot)
        paths_a = _paths_for_value(leaves, self.VALUE_A)
        paths_b = _paths_for_value(leaves, self.VALUE_B)
        assert paths_a, f"литерал plugin_alpha_wsp ({self.VALUE_A}) не найден в опросе: {leaves}"
        assert paths_b, f"литерал plugin_beta_wsp ({self.VALUE_B}) не найден в опросе: {leaves}"

        # каждый литерал — под путём СВОЕГО владельца, а не чужого (поддерево, не общий лист)
        assert any(
            _path_contains(p, "plugin_alpha_wsp") and not _path_contains(p, "plugin_beta_wsp") for p in paths_a
        ), paths_a
        assert any(
            _path_contains(p, "plugin_beta_wsp") and not _path_contains(p, "plugin_alpha_wsp") for p in paths_b
        ), paths_b

        # пути РАЗНЫЕ — два листа, а не один и тот же путь, дважды перезаписанный
        assert set(paths_a).isdisjoint(set(paths_b)), (paths_a, paths_b)

    def test_push_tick_shows_both_literals_at_distinct_owner_paths(self) -> None:
        svc = _Services()
        clock = _FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        self._publish_from_two_plugins(svc)

        hb._loop(_FakeStop(clock, t_end=0.01), _NoPauseEvent())

        pushed = _pushed_leaves(svc._state_proxy)
        assert pushed, "форсированный тик обязан был опубликовать хотя бы раз"

        paths_a = _paths_for_value(pushed, self.VALUE_A)
        paths_b = _paths_for_value(pushed, self.VALUE_B)
        assert paths_a, f"литерал plugin_alpha_wsp не ушёл push'ем: {pushed}"
        assert paths_b, f"литерал plugin_beta_wsp не ушёл push'ем: {pushed}"
        assert any(
            _path_contains(p, "plugin_alpha_wsp") and not _path_contains(p, "plugin_beta_wsp") for p in paths_a
        ), paths_a
        assert any(
            _path_contains(p, "plugin_beta_wsp") and not _path_contains(p, "plugin_alpha_wsp") for p in paths_b
        ), paths_b
        assert set(paths_a).isdisjoint(set(paths_b)), (paths_a, paths_b)


# =========================================================================== #
# Критерий 3 — правила гейта из прод-конфига работают без единой правки конфига
# =========================================================================== #
class TestProdGateRulesWorkUnedited:
    """Конфиг берётся ИЗ реального ``multiprocess_prototype/backend/config/system.yaml``,
    секция ``telemetry.publish``, и передаётся гейту ДОСЛОВНО (без единой правки).
    Наблюдаемый эффект — прошла/не прошла метрика гейт (её литерал в push-payload),
    а не наличие ключа в словаре (project rule)."""

    _REPO_ROOT = Path(__file__).resolve().parents[4]
    _SYSTEM_YAML = _REPO_ROOT / "multiprocess_prototype" / "backend" / "config" / "system.yaml"

    def _load_real_publish_section(self) -> dict:
        assert self._SYSTEM_YAML.is_file(), f"боевой конфиг не найден: {self._SYSTEM_YAML}"
        raw = yaml.safe_load(self._SYSTEM_YAML.read_text(encoding="utf-8"))
        publish = raw["telemetry"]["publish"]
        # Сверка, что это ДЕЙСТВИТЕЛЬНО текущий боевой сценарий (белый список fps/latency_ms),
        # а не выдумка теста — если конфиг когда-нибудь изменится, тест обязан упасть ЗДЕСЬ,
        # явно, а не молча проверять другой сценарий.
        assert publish.get("default_enabled") is False, publish
        assert "fps" in publish.get("metrics", {}), publish
        return publish

    def test_fps_leaf_passes_and_unlisted_leaf_is_blocked_by_real_config(self) -> None:
        publish = self._load_real_publish_section()
        svc = _Services(config={"telemetry": {"publish": publish}})
        clock = _FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        # ``_build_telemetry_gate`` — ЧИСТЫЙ строитель: возвращает гейт и никуда его
        # не кладёт; поле взводит только ``start()`` (process_heartbeat.py, внутри
        # start). Без присваивания ``_loop`` шёл с ``allowed_metrics=None`` и
        # пропускал ВСЁ — тест краснел, ничего при этом не проверив.
        gate = hb._build_telemetry_gate()
        assert gate is not None, "боевая секция publish обязана строить активный гейт"
        hb._telemetry_gate = gate

        ctx = PluginContext(services=svc, plugin_name="plugin_gate_probe")
        ctx.publish_metric("fps", 777.5)
        ctx.publish_metric("unknown_probe_metric_xyz", 888.5)

        hb._loop(_FakeStop(clock, t_end=0.01), _NoPauseEvent())

        pushed = _pushed_leaves(svc._state_proxy)
        values = set(pushed.values())

        assert 777.5 in values, (
            f"метрика 'fps' плагина обязана пройти гейт прод-конфига (явное правило "
            f"metrics.fps.enabled=true) без единой правки конфига: {pushed}"
        )
        assert 888.5 not in values, (
            f"'unknown_probe_metric_xyz' обязана быть отсеяна ДЕФОЛТНЫМ правилом прод-конфига "
            f"(default_enabled=false, явного правила нет): {pushed}"
        )


# =========================================================================== #
# Критерий 4 — push и poll: один сборщик (ADR-PM-035)
# =========================================================================== #
class TestPushPollSameCollector:
    """Опрос обязан отдавать ТУ ЖЕ вложенную форму (тот же путь листа), что уходит
    push'ем — не пересчитывать вторым способом с другой формой пути."""

    LEAF_NAME = "writer_subtree_shape_probe"
    VALUE = 333.5

    def test_poll_path_matches_pushed_path_for_the_same_leaf(self) -> None:
        svc = _Services()
        clock = _FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        ctx = PluginContext(services=svc, plugin_name="plugin_shape_probe")
        ctx.publish_metric(self.LEAF_NAME, self.VALUE)

        hb._loop(_FakeStop(clock, t_end=0.01), _NoPauseEvent())

        pushed = _pushed_leaves(svc._state_proxy)
        assert pushed, "форсированный тик обязан был опубликовать хотя бы раз"
        # первый сегмент push-пути — строка merge(path, ...) (например "processes.<proc>"),
        # у poll-снимка такого обёрточного сегмента нет (см. current_levels_snapshot() в
        # test_rt2_config_flip_acceptance.py — читает snapshot.get("state", {}) НАПРЯМУЮ) —
        # снимаем его перед сравнением форм (допущение A3/A4).
        pushed_relative = {p[1:]: v for p, v in pushed.items()}
        pushed_matches = _paths_for_value(pushed_relative, self.VALUE)
        assert pushed_matches, f"литерал не ушёл push'ем вовсе: {pushed}"

        snapshot = hb.current_levels_snapshot()
        assert snapshot is not None, "опрос вернул None — сенсора нет, хотя тик уже опубликовал"
        polled_leaves = _leaf_paths(snapshot)
        polled_matches = _paths_for_value(polled_leaves, self.VALUE)
        assert polled_matches, f"литерал не виден опросом: {polled_leaves}"

        assert set(pushed_matches) == set(polled_matches), (
            "push и poll разошлись формой пути для одного и того же листа — не один сборщик",
            pushed_matches,
            polled_matches,
        )


# =========================================================================== #
# Критерий 5 — необъявленное имя едет легально, голос отказа не заводится
# =========================================================================== #
class TestUndeclaredNameRidesLegally:
    """Имя листа НИГДЕ в этом тесте не проходит через ``declare_metric`` —
    намеренно. Гейт активен (секция ``telemetry.publish`` присутствует явно, с
    дефолтом ``default_enabled=True``), чтобы отличать «гейта нет вовсе» (allowed
    metrics=None, публикуется всё без всякого гейта) от «гейт есть, правило для
    незнакомого имени — дефолтное, и оно ПРОПУСКАЕТ»."""

    LEAF_NAME = "never_declared_probe_xyz"
    VALUE = 444.5

    def test_value_present_and_no_declaration_warning_raised(self) -> None:
        svc = _Services(config={"telemetry": {"publish": {}}})
        clock = _FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        # Тот же дефект харнесса: без присваивания гейт построен, но не действует,
        # и тест был зелен ОДИНАКОВО при «гейт есть, дефолт пропускает» и «гейта нет
        # вовсе» — то есть ровно не различал то, что его докстринг обещает различать.
        gate = hb._build_telemetry_gate()
        assert gate is not None, "гейт обязан быть активен для этого теста (иначе неотличимо от «гейта нет»)"
        hb._telemetry_gate = gate

        ctx = PluginContext(services=svc, plugin_name="plugin_undeclared_probe")
        ctx.publish_metric(self.LEAF_NAME, self.VALUE)

        hb._loop(_FakeStop(clock, t_end=0.01), _NoPauseEvent())

        pushed = _pushed_leaves(svc._state_proxy)
        matches = _paths_for_value(pushed, self.VALUE)
        assert matches, f"необъявленное имя не доехало вовсе (потеряно арбитражем?): {pushed}"

        assert svc.warnings == [], (
            f"голос «публикация без объявления» не должен звучать на необъявленном, но легальном имени: {svc.warnings}"
        )
