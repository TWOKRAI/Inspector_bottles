# -*- coding: utf-8 -*-
"""Независимая приёмка К2/К4 задачи «порт наблюдений: миграция читателей»
(ветка feat/observation-port). Источник контракта: ТЕКСТ критериев К2/К4 из
брифа задачи — не диффы/планы/чужие тесты (запрещены явно), и не реализация
файлов из списка «строго запрещено открывать»:

    - multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py
      и весь каталог его тестов — К2 тестируется ЧЕРЕЗ ПУБЛИЧНЫЙ КОНТРАКТ
      (``README.md`` + ``interfaces.py`` модуля, оба РАЗРЕШЕНЫ и прочитаны),
      класс ``TelemetryReadModel`` импортирован и используется только методами
      ``ingest``/``get``/``snapshot`` — исходный код файла не открывался вовсе;
    - multiprocess_prototype/backend/state/manager_setup.py,
      multiprocess_prototype/backend/state/bootstrap.py,
      multiprocess_framework/modules/process_module/managers/telemetry_reload.py —
      не читались и не импортировались.

Разрешённые к чтению файлы использованы как БИБЛИОТЕКА для фикстур (тот же
приём, что и в ``test_observation_namespace_acceptance.py``, взятом ТОЛЬКО как
образец обвязки, а не как источник ожиданий):

    - ``plugins/base.py`` (PluginContext.declare_metric/publish_metric);
    - ``heartbeat/process_heartbeat.py`` / ``heartbeat/telemetry.py`` —
      импортируется класс ``ProcessHeartbeat`` для форсирования тика;
    - ``state_store_module`` целиком — РЕАЛЬНЫЙ ``TreeStore`` (не фейк-merge).

Решения по неоднозначностям (раскрыты по прямому требованию брифа):

  - К2 «публичный вход read-model» — README модуля документирует
    ``ingest(path, value)`` / ``get(path)`` / ``snapshot(prefix)`` как ЕДИНЫЙ
    публичный контракт (``ITelemetryReadModel``, ``interfaces.py``, разрешён).
    Тест конструирует ``TelemetryReadModel()`` и кормит его РАЗОБРАННЫМИ
    (path, value) — ровно то, что документация называет «поток уже разобранных
    дельт» (обёртка-парсер конверта — вне модуля, её тестировать не берусь: она
    не названа в списке разрешённых/запрещённых файлов брифа явно, и К2 говорит
    буквально про read-model, а не про конверт).
  - К2 «писатель доступен как источник строки» — трактовано как «полный путь,
    несущий сегмент писателя, различим в ВЫДАЧЕ read-model»: два разных
    писателя с ОДНОИМЁННОЙ метрикой должны остаться ДВУМЯ разными записями
    (не слипнуться в одну), и это проверяется и через ``get(полный_путь)``, и
    через ``snapshot(prefix)`` (ключи которого обязаны нести полный путь, а не
    голое имя метрики — иначе два писателя с одинаковым именем листа
    неразличимы в снимке).
  - К4 «засев состояния процесса» — трактован буквально по формулировке
    критерия («лист... равного None»): смоделирован ПРЯМОЙ записью в
    ``TreeStore`` плоского пути со значением ``None`` — представляет собой
    любого немигрированного писателя/остаток протокола ДО перехода на
    поддерево писателя. Код, который РЕАЛЬНО мог оставить такую запись в проде
    (``manager_setup.py``/``bootstrap.py``), не открывался и не имитировался
    иначе как этой прямой записью — сознательно узкая, буквальная имитация,
    а не попытка воспроизвести весь боевой путь.

НЕДОСТИЖИМО НА СТЕНДЕ (см. итоговый отчёт тестера целиком для полного
раздела) — коротко здесь: ``TelemetryReadModel`` конструируется БЕЗ реального
конверта/подписки/IPC (тесты кормят ``ingest`` напрямую, а не через реальный
``state.changed``-поток) — не доказывает, что РЕАЛЬНЫЙ подписчик (GUI/backend_ctl)
действительно передаёт read-model'и новые плагинные пути, только что сам
read-model, если ему их передать, отдаёт их правильно.
"""

from __future__ import annotations

# Харнесс тика (FakeClock/FakeStop/_TreeBackedProxy/HeartbeatServices) удалён
# ВМЕСТЕ с тестом К4 — им пользовался только он. Оставшиеся тесты К2 работают с
# read-model напрямую, через её публичный контракт. Причина переезда К4 и его
# новый адрес — в комментарии в конце файла.
from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel


# --------------------------------------------------------------------------- #
# К2 — read-model отдаёт ОБЕ формы (старые фреймворковые + новые плагинные)
# --------------------------------------------------------------------------- #


class TestK2ReadModelServesBothPathForms:
    def test_old_framework_suffixes_still_served_with_literals(self) -> None:
        """Регресс-якорь: старые фреймворковые пути (.state.fps/.state.latency_ms/
        .state.uptime) НЕ переезжали — read-model обязан продолжать отдавать их
        литералами через публичный ``ingest``/``get``."""
        m = TelemetryReadModel()
        m.ingest("processes.camera_0.state.fps", 25.3)
        m.ingest("processes.camera_0.state.latency_ms", 41.7)
        m.ingest("processes.camera_0.state.uptime", 120.0)

        assert m.get("processes.camera_0.state.fps") == 25.3
        assert m.get("processes.camera_0.state.latency_ms") == 41.7
        assert m.get("processes.camera_0.state.uptime") == 120.0

    def test_new_plugin_path_is_served_with_its_literal(self) -> None:
        """Новый адрес плагинной метрики (.state.plugins.<писатель>.<метрика>)
        обязан отдаваться read-model'ью literal-значением через ``get`` —
        ровно тем же публичным входом, что и старые пути."""
        m = TelemetryReadModel()
        new_path = "processes.camera_0.state.plugins.capture.drops"
        m.ingest(new_path, 9)

        assert m.get(new_path) == 9, (
            f"read-model не отдал литерал по новому плагинному пути {new_path!r} — "
            f"ingest/get не видят форму .state.plugins.<писатель>.<метрика>"
        )

    def test_two_writers_with_the_same_leaf_name_stay_distinguishable(self) -> None:
        """К2 «писатель доступен как источник строки»: ДВА писателя с ОДНОИМЁННОЙ
        метрикой (fps) не должны слипнуться в одну запись read-model — оба пути
        читаются РАЗДЕЛЬНО через get(), и оба присутствуют СВОИМИ полными путями
        в snapshot() (не голым именем метрики)."""
        m = TelemetryReadModel()
        path_a = "processes.camera_0.state.plugins.capture.fps"
        path_b = "processes.camera_0.state.plugins.color_mask.fps"
        m.ingest(path_a, 11.0)
        m.ingest(path_b, 22.0)

        # Позитив: оба читаются раздельно и несут СВОИ литералы.
        assert m.get(path_a) == 11.0
        assert m.get(path_b) == 22.0
        assert m.get(path_a) != m.get(path_b)

        # Позитив: snapshot() различает писателя ПО ПОЛНОМУ ПУТИ (не по имени листа).
        snap = m.snapshot("processes.camera_0")
        assert snap.get(path_a) == 11.0, (
            f"snapshot('processes.camera_0') не содержит полный путь писателя "
            f"'capture' ({path_a!r}) со своим литералом — snapshot={snap!r}"
        )
        assert snap.get(path_b) == 22.0, (
            f"snapshot('processes.camera_0') не содержит полный путь писателя "
            f"'color_mask' ({path_b!r}) со своим литералом — snapshot={snap!r}"
        )

    def test_history_accumulates_for_both_old_and_new_path_forms_with_default_suffixes(self) -> None:
        """К2 расширенно (не отдельный критерий, а необходимое следствие «read-model
        отдаёт обе формы» — README называет ``tracked_suffixes`` вторым публичным
        механизмом read-model'и наравне с get/snapshot). Дефолтные суффиксы
        отражают ШТАТНЫЕ фреймворковые метрики (README: «gated-метрики
        build_worker_telemetry») и могли остаться заточенными под СТАРУЮ форму
        адреса — тогда история (спарклайн GUI) для новых плагинных путей молча
        перестаёт копиться, хотя ``get``/``snapshot`` их всё ещё видят.

        Дефолтный конструктор — БЕЗ явного ``tracked_suffixes``: доверяем только
        документированному дефолтному поведению (``DEFAULT_TRACKED_SUFFIXES`` не
        импортировался и не читался этим тестом — иначе это было бы чтением
        запрещённой реализации через её ЗНАЧЕНИЕ, а не только контракт).

        Квантор "копится" — минимум ДВА ``ingest`` на путь (правило проекта)."""
        m = TelemetryReadModel()
        old_path = "processes.camera_0.state.fps"
        new_path = "processes.camera_0.state.plugins.capture.fps"

        m.ingest(old_path, 10.0)
        m.ingest(old_path, 20.0)
        m.ingest(new_path, 10.0)
        m.ingest(new_path, 20.0)

        old_hist = m.history(old_path)
        new_hist = m.history(new_path)

        # Позитив (регресс-якорь): старый путь копит историю дефолтным конструктором.
        assert len(old_hist) >= 1, (
            "регресс методологии теста: история СТАРОГО пути тоже пуста при "
            "дефолтном конструкторе — до сравнения со старым/новым дело не дошло"
        )
        # То, ради чего тест: новый плагинный путь ТОЖЕ обязан копить историю.
        assert len(new_hist) >= 1, (
            f"история НОВОГО плагинного пути {new_path!r} пуста при дефолтных "
            f"tracked_suffixes (старый путь {old_path!r} при этом копится: "
            f"{old_hist!r}) — дефолтный суффикс, видимо, заточен под старую "
            f"форму адреса (оканчивается на '.state.fps') и не матчит хвост "
            f"'.state.plugins.<писатель>.fps'"
        )


# --------------------------------------------------------------------------- #
# К4 — плоского листа-призрака (равного None) не остаётся навсегда
# --------------------------------------------------------------------------- #


# К4 ПЕРЕЕХАЛ, и это правка КООРДИНАТОРА, а не тестера (решение владельца при
# приёмке Task 1.4). Прежняя формулировка теста
# ``test_flat_none_ghost_does_not_survive_a_full_publish_cycle_forever``
# пришпиливала механизм, которого в системе нет и не планировалось: она писала
# плоский ``None`` РУКОЙ в TreeStore и ждала, что его СНИМЕТ цикл публикации.
# Публикатор мержит только своё поддерево ``state.plugins.<писатель>.*`` и
# сиблинга ``state.frame_count`` не видит — то есть тест в такой формулировке
# остался бы красным навсегда, независимо от качества исправления. Настоящая
# причина призрака — ЗАСЕВ начального дерева в прототипе
# (``multiprocess_prototype/backend/state/bootstrap.py``), и чинится он
# удалением засева, а не публикацией.
#
# Переформулированный тест гоняет НАСТОЯЩИЙ путь засева и живёт там, где ему
# место по слоям (framework не имеет права импортировать прототип):
#   multiprocess_prototype/backend/state/tests/test_observation_port_ghost_seed.py
#
# Тестер этого знать не мог: ``bootstrap.py`` был у него в списке запрещённых
# файлов, и он честно раскрыл в шапке, что имитирует засев прямой записью.
