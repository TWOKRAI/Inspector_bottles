# -*- coding: utf-8 -*-
"""``SceneSourcePlugin`` — источник кадров сцены симулятора (Task 2.2 → Task 3.4 line-sim).

Source-плагин (форма — ``Plugins/sources/synthetic_frame_source``): фон + реальные
объекты движка ``Services.line_sim`` (Task 3.4), положение которых следует за энкодером
ленты из общего мира (``sim.belt.*`` в дереве ``StateStore``, Task 2.1/2.1b).

**Чтение мира — подпиской, не ``get()`` (Решение ведущего, план line-sim,
Task 2.2).** ``StateProxy.get()`` без предварительной подписки на путь ВСЕГДА
уходит в синхронный IPC-раундтрип (до 5 с, см. ``state_proxy.py:288-320``), а
``produce()`` вызывается на каждый кадр — синхронный ``get`` с приёмного
потока (или из воркера, но это дорого) недопустим. Поэтому :meth:`start`
подписывается на ``sim.belt.**`` (``sync=False`` — тот же приём и то же
обоснование, что у ``TelemetrySinkPlugin.start``: подписка регистрируется ДО
того, как у процесса вообще есть приёмный поток, синхронный раундтрип ждать
некому), а колбэк только кладёт последнее значение в поле плагина под
``Lock`` — ни одного IPC на кадр. **Не тронуто Task 3.4** — вся эта машинерия
(``_on_deltas``, обе формы дельт, предупреждение о протухании) осталась как есть,
Task 3.4 меняет только то, ЧТО рисуется в кадре и куда деваются паспорта.

**Обе формы дельт паблишера.** Живой ``SimRobotHostPlugin._publish_once``
зовёт ``state_proxy.set()`` на КАЖДОМ тике публикации, и КАЖДЫЙ такой
``set()`` шлёт дельту ЦЕЛИКОМ по пути ``sim.belt.encoder`` (``new_value`` —
весь словарь ``{value, mm_s, t}``), а не только первый раз. Полистовые дельты
(``sim.belt.encoder.value`` / ``.mm_s`` / ``.t``) приходят из СОВСЕМ ДРУГОГО
источника — из РЕПЛЕЯ начального состояния при (пере)подписке:
``state_store_manager.py`` (``_replay_initial_state``, ~строка 430) отдаёт уже
существующее поддерево новому подписчику полистово, с источником
``src="__replay__"``. :meth:`_on_deltas` обрабатывает обе формы одним и тем же
кодом независимо от их происхождения.

**Протухшее значение — предупреждение, не экстраполяция.** Позиция объектов
всегда считается из ПОСЛЕДНЕЙ ДОСТАВЛЕННОЙ дельты (нет отдельного пути
«время идёт — двигай сцену по времени»), поэтому «заморозка» между двумя
кадрами на неизменном мире — не отдельный код, а прямое следствие того, что
между ними не пришло новой дельты. Единственный НАБЛЮДАЕМЫЙ эффект протухания
в этой версии — предупреждение через ``ctx.log_warning`` (де-дублировано по
``t``, чтобы не заспамить лог на неизменном протухшем значении).

**Task 3.4 — реальный движок вместо заглушки-спрайта.** ``configure()`` строит
``ScenePreset``/``ObjectFactory``/``ObjectSpawner``/``SceneCompositor`` из
``Services.line_sim`` (см. ``Services/line_sim/README.md``); ``rng =
np.random.default_rng(seed)`` живёт здесь (единственный producer — этот плагин,
у него часы и rng, ``SceneCompositor.render()`` их не трогает). Если движок
собрать не удалось (каталог классов из ``preset_path`` не существует или пресет
без конфигурации не может выбрать класс) — плагин НЕ падает: логирует ошибку
ОДИН раз в ``configure()`` и до конца жизни процесса отдаёт кадры одного фона.
Паспорта объектов публикуются в общий мир (``sim.objects``) ТОЛЬКО когда меняется
МНОЖЕСТВО активных ``object_id`` (спавн/деспавн) — позиция в мир не пишется,
её считает потребитель из энкодера и ``passport.spawn_encoder`` (LS-009).
"""

from __future__ import annotations

import collections
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import yaml

from multiprocess_framework.modules.recipe.service import compute_rev
from multiprocess_framework.modules.recipe.yaml_io import update_yaml_preserving
from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)
from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from Services.dataset_gen.core.catalog import imread_unicode
from Services.layer_render import ScrollingTile, SolidFill, background_layers_from_config
from Services.line_sim import ObjectFactory, ObjectSpawner, SceneCompositor, ScenePreset, confine_preset_paths
from Services.line_sim.core import (
    REPO_ROOT,
    BeltGeometry,
    JobDone,
    MatchResult,
    TruthLedger,
    apply_defect_override,
    load_scene_preset,
    match_job,
    resolve_repo_path,
)
from Services.line_sim.core.spawner import validate_flow, validate_lateral_offset_px

if TYPE_CHECKING:
    from multiprocess_framework.modules.state_store_module.core.delta import Delta

#: Дефолты конфига — форма как у ``synthetic_frame_source``.
_DEFAULT_WIDTH = 640
_DEFAULT_HEIGHT = 480
_DEFAULT_SPAWN_ENCODER = 0
_DEFAULT_PX_PER_MM = 1.0
_DEFAULT_STALE_MS = 500
_DEFAULT_SEED = 0
_DEFAULT_SPAWN_INTERVAL_S = (2.0, 4.0)
_DEFAULT_CAMERA_ID = 0

#: Task 3.5 (контракт лида §4): сопоставление «задание выполнено» ↔ объект сцены.
_DEFAULT_MATCH_RADIUS_MM = 5.0
_DEFAULT_DUP_WINDOW_S = 10.0  # тот же дефолт, что у SimJournal
_RECENT_MAXLEN = 32

#: Task 6.1: очередь управления (pause/flow/defect_now) — ограничена явно (контракт
#: лида, edge case §3), чтобы она не росла без предела, если produce() не зовут (движок
#: не собран, `self._spawner is None` — тогда _drain_control() каждый кадр выбрасывает
#: накопленное без применения). Тот же порядок величины, что _RECENT_MAXLEN — четырёх
#: ручек стенда оператор физически не нажмёт быстрее этого числа раз между кадрами.
_CONTROL_MAXLEN = 64

#: Task 5.2 (контракт лида §2) + 5.1b (§3): правда на проводе — TruthLedger + шесть
#: уровней (пятый исходный + ``truth_false_alarm_frozen_xy`` — причина «те же X/Y с
#: новым энкодером», переехавшая сюда из SimJournal, Контракт лида 5.1b §2).
_DEFAULT_TRUTH_PUBLISH_S = 1.0
_TRUTH_LEVELS: tuple[str, ...] = (
    "truth_caught",
    "truth_dup_jobs",
    "truth_missed",
    "truth_false_alarm",
    "truth_false_alarm_frozen_xy",
    "truth_on_belt",
)

#: Путь мира (Task 2.1/2.1b, паблишер — ``Plugins.sim.robot_host``).
_ENCODER_PATH = "sim.belt.encoder"
_WORLD_PATTERN = "sim.belt.**"

#: Путь мира для паспортов активных объектов (Task 3.4) — этот плагин пишет,
#: он же единственный писатель.
_OBJECTS_PATH = "sim.objects"

#: Фон сцены — концептуально BGR (тот же параметр, что принимает `SceneCompositor`).
_BACKGROUND_BGR = (60, 60, 60)

#: Не чаще раза в секунду — иначе падающая фабрика заливает лог на каждый кадр.
_FACTORY_ERROR_LOG_INTERVAL_S = 1.0

_ENGINE_DOWN_MESSAGE = "движок не запущен — применится после перезапуска"
_MISSING_KEY = object()

#: Максимальное значение счётчика кадров (rollover, как у остальных источников сима).
_FRAME_ID_MODULO = 100_000

#: Корень репозитория — `Services.line_sim.core.REPO_ROOT` (правило резолвинга путей конфига
#: общее с `Plugins.sim.layer_preview`); имя оставлено — его импортируют тесты.
_REPO_ROOT = REPO_ROOT


@register_plugin(
    "scene_source",
    category="source",
    description="Источник кадров сцены сима: движок line_sim (объекты на ленте) по энкодеру",
)
class SceneSourcePlugin(ProcessModulePlugin):
    """Фон + объекты движка line_sim, следующие за энкодером общего мира.

    Lifecycle:
        configure() -- параметры кадра/сцены, сборка движка (или fallback на фон)
        start()     -- подписка на мир (``sim.belt.**``, sync=False)
        produce()   -- tick() спавнера + render() компоновщика -> кадр BGR
    """

    name = "scene_source"
    category = "source"

    inputs: list = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр сцены сима"),
    ]
    commands: dict = {
        "scene.job_done": "cmd_job_done",
        "scene.status": "cmd_status",
        "truth.status": "cmd_truth_status",
        "truth.reset": "cmd_truth_reset",
        "preset.get": "cmd_preset_get",
        "preset.commit": "cmd_preset_commit",
        "scene.pause": "cmd_pause",
        "scene.flow": "cmd_flow",
        "scene.defect_rate": "cmd_defect_rate",
        "scene.defect_now": "cmd_defect_now",
    }

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, собрать движок сцены (или fallback на фон)."""
        self._ctx = ctx
        cfg = ctx.config
        self._width: int = cfg.get("resolution_width", _DEFAULT_WIDTH)
        self._height: int = cfg.get("resolution_height", _DEFAULT_HEIGHT)
        self._spawn_encoder: int = cfg.get("spawn_encoder", _DEFAULT_SPAWN_ENCODER)
        self._stale_ms: float = cfg.get("stale_ms", _DEFAULT_STALE_MS)
        self._camera_id = cfg.get("camera_id", _DEFAULT_CAMERA_ID)

        px_per_mm = float(cfg.get("px_per_mm", _DEFAULT_PX_PER_MM))
        belt_y_px = float(cfg.get("belt_y_px", self._height / 2.0))
        # Task 5.3b (контракт лида §4.2.2): направление ленты в кадре + точка входа
        # объекта (off=0). belt_direction=-1 -> объект входит с правого края кадра
        # (entry_x_px = resolution_width), т.к. +x кадра = -Y робота (калибровка
        # рецепта), а лента везёт в +Y. Валидация (не ±1) уходит в тот же путь, что и
        # прочие сбои сборки движка (see try/except ниже — SceneCompositor кидает
        # ValueError, сборка откатывается на фон).
        # Без int(): «abc», 1.5, True должны дойти до SceneCompositor внутри try ниже и
        # откатить сборку на фон с записью в лог, а не уронить configure() (ревью 5.3b п.3).
        belt_direction = cfg.get("belt_direction", 1)
        entry_x_px = 0.0 if belt_direction == 1 else float(self._width)

        # Task 3.3a: два режима шага спавна — ровно один задан в конфиге. Оба заданы ->
        # ValueError, НЕ пойманный ниже try/except (это ошибка конфигурации стенда, а не
        # сбой сборки движка, который допустимо проглотить и упасть на фон).
        interval_cfg = cfg.get("spawn_interval_s")
        spacing_cfg = cfg.get("spawn_spacing_mm")
        if interval_cfg is not None and spacing_cfg is not None:
            raise ValueError(
                "scene_source: заданы оба spawn_interval_s и spawn_spacing_mm — "
                "ровно один из них должен быть в конфиге стенда"
            )
        spawner_kwargs: dict[str, tuple[float, float]]
        if spacing_cfg is not None:
            spawner_kwargs = {"spacing_mm": (float(spacing_cfg[0]), float(spacing_cfg[1]))}
        else:
            interval_cfg = interval_cfg if interval_cfg is not None else _DEFAULT_SPAWN_INTERVAL_S
            spawner_kwargs = {"interval_s": (float(interval_cfg[0]), float(interval_cfg[1]))}

        scene_length_mm = float(cfg.get("scene_length_mm", (self._width / max(px_per_mm, 1e-9)) * 2.0))
        preset_path = self._resolve_preset_path(cfg.get("preset_path"))
        seed = int(cfg.get("seed", _DEFAULT_SEED))

        self._rng = np.random.default_rng(seed)
        self._lock = threading.Lock()
        self._world: dict[str, Any] = {}
        self._world_ready = False  # review Task 3.3a, находка 4 — см. produce()/_on_deltas()
        self._last_warned_t: float | None = None
        self._last_factory_error_t: float | None = None
        self._last_object_ids: frozenset[str] = frozenset()
        self._frame_count = 0

        # Task 3.5: задания робота. `_jobs` — ЕДИНСТВЕННАЯ передача между потоком команд
        # (append) и воркером produce() (popleft); оба атомарны в CPython. Спавнер меняет
        # только produce(). `_removed` — снятые объекты (момент снятия, паспорт) для исхода
        # `dup`; `_recent` читает поток команд — пишется и копируется под `self._lock`.
        geometry_cfg = cfg.get("geometry") or {"origin_x_mm": 0.0, "origin_y_mm": 0.0}
        self._geometry = BeltGeometry.from_dict(geometry_cfg)
        self._px_per_mm = px_per_mm
        # Поперечное смещение дисков: ValueError НЕ пойман try/except сборки движка ниже —
        # кривой ключ или смещение без frame_down (истина робота молча врала бы) = ошибка
        # конфигурации стенда, а не повод откатиться на фон.
        lateral_offset_px = validate_lateral_offset_px(cfg.get("lateral_offset_px", (0.0, 0.0)))
        if lateral_offset_px[1] > 0.0 and not self._geometry.has_frame_down:
            raise ValueError(
                f"scene_source: lateral_offset_px={list(lateral_offset_px)!r} требует geometry.frame_down_ux/"
                f"frame_down_uy (единичный вектор «вниз по кадру» в системе робота), получено geometry={geometry_cfg!r}"
            )
        self._match_radius_mm = float(cfg.get("match_radius_mm", _DEFAULT_MATCH_RADIUS_MM))
        self._dup_window_s = float(cfg.get("dup_window_s", _DEFAULT_DUP_WINDOW_S))
        self._jobs: collections.deque[JobDone] = collections.deque()
        self._removed: collections.deque[tuple[float, Any]] = collections.deque()
        self._recent: collections.deque[dict] = collections.deque(maxlen=_RECENT_MAXLEN)

        # Task 6.1: очередь управления ручками стенда (pause/flow/defect_now) — тот же
        # приём, что `_jobs` (append из потока команд, popleft из воркера, оба атомарны
        # в CPython): ни одна из этих команд не зовёт ObjectSpawner напрямую, разбор —
        # в _drain_control(), в начале produce(). maxlen — см. докстринг _CONTROL_MAXLEN.
        self._control: collections.deque[dict] = collections.deque(maxlen=_CONTROL_MAXLEN)
        # Нажатия «выпусти брак», ещё не отданные фабрике: флаг форс-брака одноразовый,
        # поэтому нажатия копятся счётчиком и тратятся по одному за кадр. Меняется только
        # воркером (`_drain_control`), поток команд его не трогает.
        self._defect_now_credits = 0

        # Task 5.2 (контракт лида §2): правда на проводе — свой лок (НЕ self._lock мира),
        # чтобы truth.status/truth.reset из потока команд не ждали лок мира и наоборот.
        self._truth = TruthLedger()
        self._truth_lock = threading.Lock()
        self._truth_publish_s = float(cfg.get("truth_publish_s", _DEFAULT_TRUTH_PUBLISH_S))
        self._truth_last_pub: float | None = None
        for level_name in _TRUTH_LEVELS:
            ctx.declare_metric(level_name)

        # layer-render 1.3: одиночная фон-текстура удалена — один способ задать фон (LR-002).
        # Любое значение ключа (в т.ч. None) — ошибка схемы, выходит из configure() до сборки движка.
        if "background_texture" in cfg:
            raise ValueError(
                "scene_source: ключ background_texture удалён (layer-render 1.3) — "
                "задайте фон через background_layers: [{solid: [R, G, B]}, {tile: <путь>}]"
            )
        # layer-render 1.1: стек слоёв `background_layers` — ошибка схемы выходит из configure()
        # (вне try/except сборки движка); нечитаемый тайл слоя — один log_error, слой выброшен.
        background_items = cfg.get("background_layers")
        background_layers: list[SolidFill | ScrollingTile] | None = None
        layer_tile_info: list[str | None] = []  # по одному на вызов загрузки (порядок tile в конфиге)
        if background_items is not None:

            def load_layer_image(path: str) -> np.ndarray | None:
                image = self._load_layer_image(ctx, path)
                if image is None:
                    layer_tile_info.append(None)
                else:
                    mode = "RGBA" if image.shape[2] == 4 else "RGB"
                    layer_tile_info.append(f"tile({path}, {image.shape[1]}x{image.shape[0]}, {mode})")
                return image

            background_layers = background_layers_from_config(background_items, load_layer_image)

        # Task 1.2a: команды пресета. Свой лок (НЕ self._lock мира, НЕ self._truth_lock) —
        # сериализует только commit'ы между собой (сравнение rev + запись файла).
        # `_pending_factory` — единственная передача «новая фабрика» из потока команд в воркер
        # produce(): deque(maxlen=1) — append (затирает не применённую) и popleft атомарны в
        # CPython, тот же приём, что `_jobs` (голое поле «прочитал-обнулил» теряло бы commit,
        # пришедший между чтением и обнулением в воркере).
        self._preset_path: str | None = (
            preset_path if preset_path is not None and preset_path.lower().endswith((".yaml", ".yml")) else None
        )
        self._defect_override: float | None = float(cfg["defect_probability"]) if "defect_probability" in cfg else None
        self._preset_lock = threading.Lock()
        self._pending_factory: collections.deque[ObjectFactory] = collections.deque(maxlen=1)
        self._preset: ScenePreset | None = None
        self._live_factory: ObjectFactory | None = None

        self._spawner: ObjectSpawner | None = None
        self._compositor: SceneCompositor | None = None
        try:
            preset = load_scene_preset(preset_path, self._defect_override)
            self._preset = preset
            factory = ObjectFactory(preset)
            self._spawner = ObjectSpawner(
                factory, scene_length_mm=scene_length_mm, lateral_offset_px=lateral_offset_px, **spawner_kwargs
            )
            self._compositor = SceneCompositor(
                self._spawner,
                px_per_mm=px_per_mm,
                belt_y_px=belt_y_px,
                background_bgr=_BACKGROUND_BGR,
                background_layers=background_layers,
                belt_direction=belt_direction,
                entry_x_px=entry_x_px,
            )
            self._live_factory = factory
        except Exception as exc:  # noqa: BLE001 — любой сбой сборки движка не должен ронять configure()  # no-health: ДОЛГ — отказ движка виден только в log_error, health не видит (OPEN_QUESTIONS, Task 5.5c)
            ctx.log_error(
                f"scene_source: движок сцены недоступен (preset_path={preset_path!r}): {exc!r} — "
                "кадры будут только фоном"
            )

        if background_layers is not None:
            tile_infos = iter(layer_tile_info)
            parts = []
            for item in background_items:
                if "solid" in item:
                    parts.append("solid({},{},{})".format(*item["solid"]))
                elif (info := next(tile_infos)) is not None:
                    parts.append(info)
            background_desc = f"слои[{', '.join(parts)}]"
        else:
            background_desc = f"цвет {_BACKGROUND_BGR}"

        ctx.log_info(
            f"scene_source: {self._width}x{self._height}, px_per_mm={px_per_mm}, belt_y_px={belt_y_px}, "
            f"spawner_kwargs={spawner_kwargs}, preset_path={preset_path!r}, фон={background_desc}, "
            f"движок={'готов' if self._compositor is not None else 'недоступен (fallback на фон)'}"
        )

    @staticmethod
    def _resolve_preset_path(preset_path: str | None) -> str | None:
        """Тонкий делегат `Services.line_sim.core.resolve_repo_path` (тесты зовут это имя)."""
        return resolve_repo_path(preset_path)

    def _load_layer_image(self, ctx: PluginContext, tile_path: str) -> np.ndarray | None:
        """Загрузить картинку слоя `tile` (layer-render 1.1): RGB или RGBA uint8. Путь резолвится от
        корня репозитория; ЛЮБАЯ причина нечитаемости (нет файла, битые байты, не 8 бит, не 3/4 канала)
        даёт ровно один `ctx.log_error` и `None` — слой выбрасывается, движок живёт."""
        resolved = self._resolve_preset_path(tile_path)
        try:
            image = imread_unicode(resolved, cv2.IMREAD_UNCHANGED)
            if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
                raise ValueError(f"ожидался uint8 (H, W, 3|4), получено dtype={image.dtype} shape={image.shape}")
            code = cv2.COLOR_BGRA2RGBA if image.shape[2] == 4 else cv2.COLOR_BGR2RGB
            return cv2.cvtColor(image, code)
        except Exception as exc:  # noqa: BLE001 — файл не найден/битый — слой выбрасывается, не падение  # no-health: ДОЛГ — выброшенный слой виден только в log_error, health не видит (OPEN_QUESTIONS, Task 5.5c)
            ctx.log_error(f"scene_source: тайл слоя фона недоступен (tile={resolved!r}): {exc!r} — слой выброшен")
            return None

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: подписаться на мир. Без ``state_proxy`` — энкодер остаётся в spawn."""
        if ctx.state_proxy is None:
            ctx.log_warning("scene_source: ctx.state_proxy is None — мир недоступен, энкодер остаётся в spawn")
            return
        ctx.state_proxy.subscribe(_WORLD_PATTERN, self._on_deltas, exclude_self=True, sync=False)

    # ------------------------------------------------------------------ #
    # Подписка на мир (не тронуто Task 3.4 — см. докстринг модуля)
    # ------------------------------------------------------------------ #

    def _on_deltas(self, deltas: list["Delta"]) -> None:
        """Колбэк подписки: только копим последнее значение, без I/O.

        `_world_ready` (review Task 3.3a, находка 4) взводится, когда в `self._world`
        появляется реальный ключ `value` — ЛЮБОЙ из двух форм дельты (целиком словарём по
        `_ENCODER_PATH` или полистово по `_ENCODER_PATH + ".value"`). Не путать с «энкодер
        не сдвинулся» (тот вариант уже отвергнут в Task 3.3 — ломает законный паттерн
        «энкодер держат константой»): здесь речь про «мира ещё не было ВООБЩЕ», не про
        застой уже пришедшего значения."""
        with self._lock:
            for d in deltas:
                if d.new_value is MISSING:
                    continue
                if d.path == _ENCODER_PATH:
                    if isinstance(d.new_value, dict):
                        self._world.update(d.new_value)
                elif d.path.startswith(_ENCODER_PATH + "."):
                    leaf = d.path[len(_ENCODER_PATH) + 1 :]
                    self._world[leaf] = d.new_value
            if "value" in self._world:
                self._world_ready = True

    # ------------------------------------------------------------------ #
    # Рендер (Task 3.4 — движок line_sim вместо заглушки-спрайта)
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Вернуть один кадр сцены: tick() спавнера + render() компоновщика, либо фон.

        Спавнер НЕ тикает, пока мира ещё не было (`_world_ready is False`) — review Task
        3.3a, находка 4: без этой проверки первые кадры (до первой дельты от `robot_host`)
        тикают на `spawn_encoder` из конфига (обычно `0`) и порождают призрачный объект на
        `spawn_encoder=0`, который потом либо никогда не деспавнится (если реальный энкодер
        стартует далеко от 0), либо путает счёт `spacing_mm`. Это НЕ вариант «не спавнить,
        пока энкодер не сдвинулся» (тот отвергнут в Task 3.3 — ломает тесты, держащие
        энкодер константой намеренно): здесь проверяется факт «была хотя бы одна дельта»,
        не движение уже пришедшего значения. Рендер компоновщика продолжает работать всегда
        (активных объектов ещё нет — кадр останется фоном, независимо от `now_encoder`)."""
        self._drain_jobs()
        self._drain_control()
        self._apply_pending_factory()
        now_encoder = self._read_world_encoder()

        if self._spawner is not None and self._compositor is not None:
            if self._world_ready:
                # Task 5.2 (контракт лида §2): снимок id ДО тика (после _drain_jobs — объекты,
                # снятые заданием в этом же кадре, уже не в active_objects()) и ПОСЛЕ — разница
                # даёт on_spawn/on_despawn для TruthLedger. Считается и когда tick() бросил: деспавн
                # в tick() идёт ДО factory.make(), так что в кадре со сбоем фабрики объект мог уже
                # уйти со сцены — пропусти здесь diff, и он навсегда останется «на ленте» (ревью 5.2).
                before_ids = {obj.passport.object_id for obj in self._spawner.active_objects()}
                try:
                    self._spawner.tick(now_encoder=now_encoder, now_wall_s=time.monotonic(), rng=self._rng)
                except Exception as exc:  # noqa: BLE001 — сбой фабрики не должен ронять кадровый цикл  # no-health: ДОЛГ — вечный отказ фабрики виден только в log_error, health не видит (OPEN_QUESTIONS, Task 5.5c)
                    self._warn_factory_error(exc)
                after_passports = {obj.passport.object_id: obj.passport for obj in self._spawner.active_objects()}
                self._update_truth_belt(before_ids, after_passports)
            frame_rgb, _passports_in_view = self._compositor.render(
                now_encoder, camera_rect=(0.0, 0.0, float(self._width), float(self._height))
            )
            self._sync_world_objects()
        else:
            frame_rgb = self._background_only_frame()

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        self._publish_truth_metrics()

        self._frame_count = (self._frame_count % _FRAME_ID_MODULO) + 1
        return [
            {
                "frame": frame_bgr,
                "camera_id": self._camera_id,
                "seq_id": self._frame_count,
                "frame_id": self._frame_count,
                "timestamp": time.monotonic(),
                "width": self._width,
                "height": self._height,
                "channels": 3,
                "dtype": "uint8",
            }
        ]

    # ------------------------------------------------------------------ #
    # Задания робота (Task 3.5 — контракт лида §4)
    # ------------------------------------------------------------------ #

    def cmd_job_done(self, data: dict | None = None) -> dict:
        """`scene.job_done` (поток команд): только поставить задание в очередь.

        Спавнер отсюда НЕ трогается — разбор в начале следующего `produce()`."""
        try:
            job = JobDone.from_dict(data or {})
        except Exception as exc:  # noqa: BLE001 — кривые аргументы -> ответ, не исключение  # no-health: ошибка уходит вызывающему в ответе команды
            return {"status": "error", "message": f"scene.job_done: кривые аргументы {data!r}: {exc!r}"}
        self._jobs.append(job)
        return {"status": "ok"}

    def cmd_status(self, data: dict | None = None) -> dict:
        """`scene.status` (поток команд): число активных объектов + последние исходы +
        (Task 6.1) `paused`/`flow`/`defect_probability`/`force_defect_pending` — снимок
        РЕАЛЬНОГО состояния движка (после применения на `produce()`, не сырая заявка
        клиента из очереди управления).

        `active_objects()` — копия списка (`list(...)`, одна C-операция под GIL), спавнер
        отсюда не мутируется. Движок не собран -> `paused=False`, `flow={}`,
        `force_defect_pending=False`, `defect_probability` — по override/пресету, как обычно."""
        active = len(self._spawner.active_objects()) if self._spawner is not None else 0
        with self._lock:
            recent = list(self._recent)
        if self._live_factory is not None:
            # Ф2 (ревью итерация 2): применённое, не заявленное -- живая фабрика уже несёт
            # результат последнего _apply_pending_factory() (commit/defect_rate), заявка,
            # ещё сидящая в _pending_factory, здесь не видна до следующего produce().
            defect_probability = self._live_factory.defect_probability
        elif self._preset is not None:
            defect_probability = (
                self._defect_override if self._defect_override is not None else self._preset.defect_probability
            )
        else:
            defect_probability = self._defect_override if self._defect_override is not None else 0.0
        if self._spawner is not None:
            spawner_flow = self._spawner.flow
            flow = {spawner_flow["mode"]: [spawner_flow["lo"], spawner_flow["hi"]]}
            paused = self._spawner.paused
        else:
            flow = {}
            paused = False
        force_defect_pending = self._live_factory.force_defect_pending if self._live_factory is not None else False
        return {
            "status": "ok",
            "active": active,
            "recent": recent,
            "paused": paused,
            "flow": flow,
            "defect_probability": defect_probability,
            "force_defect_pending": force_defect_pending,
        }

    def cmd_truth_status(self, data: dict | None = None) -> dict:
        """`truth.status` (поток команд): снимок счётчиков `TruthLedger` — §2 контракта."""
        with self._truth_lock:
            counters = self._truth.counters()
        return {"status": "ok", "counters": counters}

    def cmd_truth_reset(self, data: dict | None = None) -> dict:
        """`truth.reset` (поток команд): `ledger.reset()` — объекты под учётом остаются,
        см. `TruthLedger.reset()` (§2 контракта)."""
        with self._truth_lock:
            self._truth.reset()
        return {"status": "ok"}

    # ------------------------------------------------------------------ #
    # Ручки стенда (Task 6.1 — контракт лида, plans/line-sim/phase-6-contract-6.1.md):
    # поток, доля брака, пауза, «выпусти брак сейчас». Ни одна не зовёт ObjectSpawner
    # напрямую из потока команд (дисциплина потоков, докстринг модуля spawner.py) —
    # pause/flow/defect_now кладут намерение в self._control, разбирает _drain_control()
    # в начале produce(). Валидация — здесь, ДО постановки в очередь (кривой аргумент
    # отвечает ошибкой немедленно, не тратя такт воркера).
    # ------------------------------------------------------------------ #

    def cmd_pause(self, data: dict | None = None) -> dict:
        """`scene.pause {"paused": bool}` — останавливает/возобновляет НОВЫЙ спавн
        (деспавн не трогается, см. `ObjectSpawner.set_paused`). Кладёт намерение в
        очередь управления — спавнер меняется только на следующем `produce()`.
        Движок не собран (`self._spawner is None`) -> `{"status": "ok", "applied": False}`,
        в очередь ничего не кладётся -- как уже делает `scene.defect_rate` (Ф3а, ревью
        итерация 2). Очередь переполнена -> `overloaded`, см. `_push_control` (Ф3б)."""
        if not isinstance(data, dict) or not isinstance(data.get("paused"), bool):
            return self._invalid(f"scene.pause: ожидается {{'paused': bool}}, получено {data!r}")
        if self._spawner is None:
            return {"status": "ok", "applied": False}
        overload = self._push_control({"op": "pause", "paused": data["paused"]})
        return overload if overload is not None else {"status": "ok"}

    def cmd_flow(self, data: dict | None = None) -> dict:
        """`scene.flow` — РОВНО один из `{"interval_s": [lo, hi]}` / `{"spacing_mm": [lo,
        hi]}`. Валидация — той же `validate_flow`, что и `ObjectSpawner.__init__`/
        `set_flow`, ДО постановки в очередь: кривой аргумент не долетает до спавнера
        вовсе, ничего не ломает через тик.

        Присутствие ключа определяется через `in data`, НЕ `is not None` (Ф4, ревью
        итерация 2) — `{"interval_s": [...], "spacing_mm": None}` обязан считаться ДВУМЯ
        присутствующими ключами (`invalid`), а не «ровно один задан»: раньше явный `null`
        второго ключа маскировался под «не задан» и проходил валидацию.

        Движок не собран -> `{"status": "ok", "applied": False}` (Ф3а), очередь
        переполнена -> `overloaded` (Ф3б, `_push_control`)."""
        if not isinstance(data, dict):
            return self._invalid(f"scene.flow: ожидается dict, получено {data!r}")
        interval_present = "interval_s" in data
        spacing_present = "spacing_mm" in data
        if interval_present == spacing_present:
            return self._invalid(f"scene.flow: ожидается ровно один из interval_s/spacing_mm, получено {data!r}")
        try:
            if interval_present:
                raw_interval = data["interval_s"]
                interval_s = (float(raw_interval[0]), float(raw_interval[1]))
                spacing_mm = None
            else:
                raw_spacing = data["spacing_mm"]
                spacing_mm = (float(raw_spacing[0]), float(raw_spacing[1]))
                interval_s = None
            validate_flow(interval_s, spacing_mm)
        except Exception as exc:  # noqa: BLE001 — кривые аргументы -> ответ с кодом, не исключение  # no-health: ошибка уходит вызывающему в ответе команды
            return self._invalid(f"scene.flow: {exc!r}")
        kwargs = {"interval_s": interval_s} if interval_s is not None else {"spacing_mm": spacing_mm}
        if self._spawner is None:
            return {"status": "ok", "applied": False}
        overload = self._push_control({"op": "flow", "kwargs": kwargs})
        return overload if overload is not None else {"status": "ok"}

    def cmd_defect_rate(self, data: dict | None = None) -> dict:
        """`scene.defect_rate {"probability": p}` (Task 6.1 шаг 6) — НЕ заводит своего
        механизма подмены фабрики: пересобирает `ObjectFactory` из ТЕКУЩЕГО пресета в
        памяти (`apply_defect_override`) и кладёт её в СУЩЕСТВУЮЩИЙ `_pending_factory`
        (maxlen=1, тот же механизм, что `preset.commit`) — гонка `defect_rate`↔`commit`
        в одном кадре разрешается «в силе последняя», как и было. `self._defect_override`
        обновляется сразу (плагин-уровневое поле, не спавнер — не нарушает дисциплину
        потоков), чтобы последующий `preset.commit`/`scene.status` не отдал старую долю.
        Файл пресета НЕ переписывается. Движок не собран (`_spawner is None`) ->
        `{"status": "ok", "applied": False}`, фабрика не строится — нечего применять."""
        if not isinstance(data, dict):
            return self._invalid(f"scene.defect_rate: ожидается dict, получено {data!r}")
        probability = data.get("probability")
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            return self._invalid(f"scene.defect_rate: probability должен быть числом 0..1, получено {probability!r}")
        probability = float(probability)
        if not (0.0 <= probability <= 1.0):
            return self._invalid(f"scene.defect_rate: probability={probability} вне диапазона [0, 1]")
        if self._spawner is None or self._preset is None:
            return {"status": "ok", "applied": False}
        self._defect_override = probability
        factory = ObjectFactory(apply_defect_override(self._preset, probability))
        self._pending_factory.append(factory)  # затирает не применённую — в силе последняя
        return {"status": "ok"}

    def cmd_defect_now(self, data: dict | None = None) -> dict:
        """`scene.defect_now {}` (Task 6.1 шаг 7) — кладёт намерение в очередь управления;
        разбор зовёт `spawner.force_defect_next()`. Нажатия НЕ схлопываются (два подряд
        дают два дефектных объекта — FIFO очереди, каждое своя запись); на паузе объект
        не создаётся, но нажатие не теряется (гарантия `ObjectFactory`/`ObjectSpawner`,
        LS-006/LS-007 — флаг гасится только после успешной сборки).

        Принимает только `None`/`{}` (Ф4, ревью итерация 2) — раньше не валидировал ничего
        и клал в очередь ЛЮБОЙ payload, включая мусор. Движок не собран ->
        `{"status": "ok", "applied": False}` (Ф3а), очередь переполнена -> `overloaded`
        (Ф3б, `_push_control`)."""
        if data is not None and data != {}:
            return self._invalid(f"scene.defect_now: ожидается None или пустой dict, получено {data!r}")
        if self._spawner is None:
            return {"status": "ok", "applied": False}
        overload = self._push_control({"op": "defect_now"})
        return overload if overload is not None else {"status": "ok"}

    # ------------------------------------------------------------------ #
    # Команды пресета (Task 1.2a — план line-sim-layer-editor, «Устройство»)
    # ------------------------------------------------------------------ #

    def cmd_preset_get(self, data: dict | None = None) -> dict:
        """`preset.get` (поток команд): пресет, `rev` (sha256 байт файла), путь, классы, `engine`.

        Плагин из `.yaml` — пресет читается С ДИСКА (не из памяти и без override конфига
        стенда: редактор правит файл). `rev` читается ПЕРВЫМ, пресет — после: если файл
        сменил кто-то мимо команды между двумя чтениями, клиент получит старый `rev` и его
        commit честно упадёт в `conflict`, а не перезапишет чужую правку. Плагин из
        каталога — `rev`/`path` `None`, пресет — тот, что в памяти. `class_names` — живой
        фабрики (пусто, если движок недоступен). `engine` — собрался ли движок в `configure()`:
        `False` -> commit пишет файл, но применится только после перезапуска (ревью S2)."""
        class_names = list(self._live_factory.class_names) if self._live_factory is not None else []
        engine = self._spawner is not None
        if self._preset_path is None:
            preset = self._preset.to_dict() if self._preset is not None else None
            return {
                "status": "ok",
                "preset": preset,
                "rev": None,
                "path": None,
                "class_names": class_names,
                "engine": engine,
            }
        try:
            with self._preset_lock:
                rev = self._file_rev()
                preset_dict = ScenePreset.from_yaml(self._preset_path).to_dict()
        except OSError as exc:  # no-health: ошибка уходит вызывающему в ответе команды
            return {"status": "error", "code": "io_error", "message": f"preset.get: {exc}"}
        except Exception as exc:  # noqa: BLE001 — битый файл на диске -> ответ, не исключение  # no-health: ошибка уходит вызывающему в ответе команды
            return {"status": "error", "code": "invalid", "message": f"preset.get: {exc}"}
        return {
            "status": "ok",
            "preset": preset_dict,
            "rev": rev,
            "path": self._preset_path,
            "class_names": class_names,
            "engine": engine,
        }

    def cmd_preset_commit(self, data: dict | None = None) -> dict:
        """`preset.commit` (поток команд): проверить, записать изменившиеся ключи, отдать фабрику воркеру.

        `data = {"preset": dict, "base_rev": str}`. `base_dir` клиента отбрасывается —
        относительные пути резолвятся от каталога файла пресета; КАЖДЫЙ путь картинки
        клиента после `resolve()` обязан лежать в корне репозитория или в каталоге файла
        пресета — иначе `invalid` с одним и тем же текстом ДО любого чтения (ревью S3).
        Валидация (ограда путей, `ScenePreset`, сборка `ObjectFactory` с тем же правилом
        override, что в `configure()`) — ВНЕ лока; под `_preset_lock` — сверка `rev`,
        проверка записи (`os.access`, файл 0444 -> `io_error`), запись и передача фабрики.

        Пишутся только top-level ключи, чьё значение отличается от файла (сравнение
        нормализованных dict `ScenePreset.to_dict()` — дефолты не считаются правкой), через
        `recipe.yaml_io.update_yaml_preserving` (атомарно, комментарии нетронутых ключей
        живы; внутри заменённого ключа — теряются). Ничего не изменилось —
        `{"status": "ok", "rev": <текущий>, "changed": False}` без записи и без подмены.
        Движок не собрался в `configure()` — файл всё равно пишется, `applied: False`
        (ревью S2). Проигравший гонку `rev` фабрику не оставляет — `conflict` до передачи.
        В файл пишется пресет клиента, НЕ вариант с override конфига стенда."""
        if self._preset_path is None:
            return self._bad_request("preset.commit: плагин собран не из .yaml-пресета — писать некуда")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("preset"), dict)
            or not isinstance(data.get("base_rev"), str)
        ):
            return self._bad_request("preset.commit: ожидается {'preset': dict, 'base_rev': str}")
        try:
            preset = self._preset_from_client(data["preset"])
            factory = ObjectFactory(apply_defect_override(preset, self._defect_override))
        except Exception as exc:  # noqa: BLE001 — любой сбой проверки -> invalid с текстом  # no-health: ошибка уходит вызывающему в ответе команды
            return {"status": "error", "code": "invalid", "message": str(exc)}
        new_dict = preset.to_dict()
        new_dict.pop("base_dir", None)

        path = Path(self._preset_path)
        engine = self._spawner is not None
        with self._preset_lock:
            try:
                raw = path.read_bytes()
            except OSError as exc:  # no-health: ошибка уходит вызывающему в ответе команды
                return {"status": "error", "code": "io_error", "message": f"preset.commit: {exc}"}
            current_rev = compute_rev(raw)
            if current_rev != data["base_rev"]:
                return {"status": "error", "code": "conflict", "current_rev": current_rev}
            on_disk = self._normalized_file_dict(raw, path)
            changed = {key: value for key, value in new_dict.items() if on_disk.get(key, _MISSING_KEY) != value}
            if not changed:
                # Ничего не записано, но пресет клиента по построению РАВЕН файлу, а поле
                # плагина могло протухнуть от внешней правки файла мимо команды (ревью
                # итерация 2, остаточный путь Ф1: угол на диске 30, в памяти 0 -> любая
                # последующая пересборка фабрики откатывала бы объект к 0).
                self._preset = preset
                return {"status": "ok", "rev": current_rev, "changed": False}
            if not os.access(path, os.W_OK):
                return {
                    "status": "error",
                    "code": "io_error",
                    "message": f"preset.commit: файл только для чтения: {path}",
                }
            try:
                update_yaml_preserving(path, changed)
                new_rev = self._file_rev()
            except OSError as exc:  # no-health: ошибка уходит вызывающему в ответе команды
                return {"status": "error", "code": "io_error", "message": f"preset.commit: {exc}"}
            # Ф1 (ревью итерация 2): без этого self._preset остаётся тем, что собрал
            # configure() -- любой ПОСЛЕДУЮЩИЙ scene.defect_rate пересобирает фабрику из
            # УСТАРЕВШЕГО пресета и откатывает содержательную правку этого commit'а.
            # `preset` -- БЕЗ override (тот же объект, что ушёл в файл строкой выше), а не
            # `factory`/`apply_defect_override(...)` -- иначе доля брака начнёт наслаиваться
            # на себя на следующем commit'е. Не зависит от `engine` -- поле плагина, не
            # состояние движка.
            self._preset = preset
            if engine:
                self._pending_factory.append(factory)  # затирает ещё не применённую — в силе последняя
        result = {"status": "ok", "rev": new_rev, "changed": True, "applied": engine}
        if not engine:
            result["message"] = _ENGINE_DOWN_MESSAGE
        return result

    def _apply_pending_factory(self) -> None:
        """Воркер produce(): применить фабрику последнего commit'а (если есть) ДО `tick()`."""
        if self._spawner is None:
            return
        try:
            factory = self._pending_factory.popleft()
        except IndexError:  # no-health: пустая очередь фабрик — control-flow
            return
        self._spawner.set_factory(factory)
        self._live_factory = factory

    def _preset_from_client(self, preset_dict: dict) -> ScenePreset:
        """`ScenePreset` из dict клиента с ПРИНУДИТЕЛЬНЫМ `base_dir` (каталог файла пресета, у
        плагина из каталога — корень репозитория) и оградой путей (ревью S3): каждый путь
        картинки (`catalog_dir`, `sprite_source` кроме `class://`) после `resolve()` — внутри
        `_REPO_ROOT` или каталога файла пресета. Проверка — ДО любого чтения картинок
        (`ObjectFactory` зовётся после), текст отказа один (`OUTSIDE_ROOTS_MESSAGE`) — нет
        оракула «файл существует»; сама ограда — `Services.line_sim.confine_preset_paths`, общая
        с `Plugins.sim.layer_preview`. Пресет из файла конфига сюда не идёт — ему доверяем."""
        preset_dir = Path(self._preset_path).parent.resolve() if self._preset_path is not None else None
        preset = ScenePreset.from_dict({**preset_dict, "base_dir": str(preset_dir or _REPO_ROOT)})
        confine_preset_paths(preset, [_REPO_ROOT] if preset_dir is None else [_REPO_ROOT, preset_dir])
        return preset

    @staticmethod
    def _normalized_file_dict(raw: bytes, path: Path) -> dict:
        """Пресет файла в форме `to_dict()` без `base_dir` — база сравнения «что изменилось».
        Файл не разбирается в пресет — `{}`: тогда пишутся все ключи клиента."""
        try:
            data = yaml.safe_load(raw.decode("utf-8"))
            normalized = ScenePreset.from_dict({**data, "base_dir": str(path.parent.resolve())}).to_dict()
        except Exception:  # noqa: BLE001 — битый файл на диске — сравнивать не с чем  # no-health: битый пресет → пустой словарь, вызывающий решает
            return {}
        normalized.pop("base_dir", None)
        return normalized

    def _file_rev(self) -> str:
        """`rev` ТЕКУЩИХ байт файла пресета (`recipe.service.compute_rev`) — читается каждый раз,
        не кэшируется: запись мимо команды тоже меняет rev и даёт `conflict`."""
        assert self._preset_path is not None
        return compute_rev(Path(self._preset_path).read_bytes())

    @staticmethod
    def _bad_request(message: str) -> dict:
        return {"status": "error", "code": "bad_request", "message": message}

    @staticmethod
    def _invalid(message: str) -> dict:
        """Ответ на кривые аргументы ручек стенда (Task 6.1) — `code` обязателен у всех
        четырёх команд (контракт лида шаг 3), тот же образец, что `preset.commit`."""
        return {"status": "error", "code": "invalid", "message": message}

    def _push_control(self, op: dict) -> dict | None:
        """Поставить намерение в очередь управления (Ф3б, ревью итерация 2) — вызывается
        ТОЛЬКО когда `self._spawner is not None` (иначе `applied: False`, см. вызывающих).

        Переполнение (`len(self._control) >= _CONTROL_MAXLEN`) отвечает `overloaded` и
        НИЧЕГО не кладёт — `deque(maxlen=...)` при `append` сам по себе молча роняет
        САМУЮ СТАРУЮ заявку слева (например снятие паузы), что теряет заявку без единого
        сигнала клиенту. Явная проверка перед `append` возвращает контроль клиенту вместо
        того. `maxlen` у `deque` остаётся страховкой (двойная защита), не единственной."""
        if len(self._control) >= _CONTROL_MAXLEN:
            return {
                "status": "error",
                "code": "overloaded",
                "message": "scene_source: очередь управления переполнена — заявка отклонена",
            }
        self._control.append(op)
        return None

    def _drain_control(self) -> None:
        """Разобрать очередь управления ручками стенда целиком (воркер produce(), рядом
        с `_drain_jobs()`/`_apply_pending_factory()`, Task 6.1) — В ПОРЯДКЕ ПОСТУПЛЕНИЯ
        (FIFO), поэтому «в силе последняя» для pause/flow получается сама собой, а
        нажатия defect_now не схлопываются (каждое — отдельный вызов `force_defect_next()`).

        Не зависит от `_world_ready` — намерение, пришедшее до первой дельты мира,
        применяется на первом же produce() (спавнер уже создан в `configure()`,
        независимо от того, пришла ли дельта энкодера). Движок не собран (`_spawner is
        None`) -> очередь просто выбрасывается без применения (см. докстринг
        `_CONTROL_MAXLEN`) — спавнера, которому адресовано намерение, не существует.

        `defect_now` — особый случай: `ObjectFactory.force_defect_next()` булев ОДНОРАЗОВЫЙ
        флаг, не счётчик нажатий (Task 3.2), поэтому два нажатия подряд схлопнулись бы в
        один дефектный объект (контракт лида, критерий 3: два нажатия дают ДВА дефекта).
        Нажатия копятся ОТДЕЛЬНЫМ счётчиком `_defect_now_credits`, а не задержкой в голове
        очереди: очередь всегда разбирается до конца, кредит тратится по одному за кадр,
        как только фабрика свободна.

        Почему не «ждать в голове очереди» (инъекция лида 2026-09-28, дефект найден
        воспроизведением, не чтением): на паузе фабрика форс-брак не тратит НИКОГДА, и всё,
        что встало за не выпущенным `defect_now` — в том числе снятие той самой паузы — не
        применялось. Пульт в этом состоянии не мог снять паузу ничем, кроме рестарта
        процесса. Регрессия — `tests/test_lead_6_1.py`."""
        while self._control:
            op = self._control.popleft()
            if self._spawner is None:
                continue  # некому применять -- см. докстринг _CONTROL_MAXLEN
            kind = op["op"]
            if kind == "pause":
                self._spawner.set_paused(op["paused"])
            elif kind == "flow":
                self._spawner.set_flow(**op["kwargs"])
            elif kind == "defect_now":
                # потолок тот же, что у очереди: копить нажатия без предела незачем
                self._defect_now_credits = min(self._defect_now_credits + 1, _CONTROL_MAXLEN)
        if (
            self._spawner is not None
            and self._defect_now_credits > 0
            and not (self._live_factory is not None and self._live_factory.force_defect_pending)
        ):
            self._spawner.force_defect_next()
            self._defect_now_credits -= 1

    def _drain_jobs(self) -> None:
        """Разобрать очередь заданий целиком (воркер produce(), ДО `spawner.tick()`).

        Не зависит от `_world_ready`: задание разбирается и до прихода мира. Движок не
        собран -> каждое задание получает `no_object`."""
        if not self._jobs:
            return
        now = time.monotonic()
        while self._removed and now - self._removed[0][0] > self._dup_window_s:
            self._removed.popleft()

        while self._jobs:
            job = self._jobs.popleft()
            if self._spawner is None:
                # Task 5.2 (контракт лида §2): движок не собран -> каждое задание получает
                # no_object на проводе И в TruthLedger (растёт только false_alarm).
                result = MatchResult(outcome="no_object", object_id=None, residual_mm=None)
            else:
                result = match_job(
                    [obj.passport for obj in self._spawner.active_objects()],
                    job,
                    self._geometry,
                    removed=[passport for _t, passport in self._removed],
                    match_radius_mm=self._match_radius_mm,
                    px_per_mm=self._px_per_mm,
                )
                if result.outcome == "matched" and result.object_id is not None:
                    passport = self._spawner.remove(result.object_id)
                    if passport is not None:
                        self._removed.append((now, passport))
            outcome, object_id, residual_mm = result.outcome, result.object_id, result.residual_mm
            with self._truth_lock:
                # Task 5.1b (контракт лида §3): job идёт в TruthLedger в ОБЕИХ ветках
                # (движок собран/не собран) — причина «те же X/Y» считается по job.t
                # независимо от того, нашёлся ли кандидат в match_job.
                self._truth.on_match(result, job)
            entry = {"index": job.index, "outcome": outcome, "object_id": object_id, "residual_mm": residual_mm}
            with self._lock:
                self._recent.append(entry)
            residual_desc = "—" if residual_mm is None else f"{residual_mm:.2f} мм"
            self._ctx.log_info(
                f"scene_source: задание #{job.index} ({job.x_mm:.1f}, {job.y_mm:.1f}) мм, "
                f"ecap={job.ecap} -> {outcome}, объект={object_id}, невязка={residual_desc}"
            )

    def _read_world_encoder(self) -> float:
        """Снимок текущего значения энкодера из мира + предупреждение о протухании."""
        with self._lock:
            snapshot = dict(self._world)

        value = snapshot.get("value", self._spawn_encoder)
        t = snapshot.get("t")
        if t is not None:
            age_ms = (time.monotonic() - t) * 1000.0
            if age_ms > self._stale_ms:
                self._warn_stale(t, age_ms)
        return float(value)

    def _background_only_frame(self) -> np.ndarray:
        """Кадр одного фона В RGB (не BGR!) — движок недоступен, см. `configure()`.

        Фикс ревью P5: `produce()` прогоняет ОБЕ ветки через один и тот же
        `cv2.COLOR_RGB2BGR` (как для кадра компоновщика), поэтому этот массив обязан
        быть RGB, а не BGR — иначе конвертация переставляет каналы ВТОРОЙ раз и
        fallback-кадр выходит с противоположным порядком каналов относительно
        `_BACKGROUND_BGR` (repro: `_BACKGROUND_BGR=(200,10,30)` → движок даёт
        `[200,10,30]`, fallback без этого фикса давал `[30,10,200]`; на дефолтном
        сером `(60,60,60)` разница незаметна, отсюда и не была поймана раньше).
        Тот же приём переворота каналов, что `SceneCompositor.render()` — см. его
        докстринг."""
        frame = np.empty((self._height, self._width, 3), dtype=np.uint8)
        b, g, r = _BACKGROUND_BGR
        frame[:, :, 0], frame[:, :, 1], frame[:, :, 2] = r, g, b
        return frame

    def _sync_world_objects(self) -> None:
        """Опубликовать `sim.objects` ТОЛЬКО когда меняется множество активных id
        (спавн/деспавн) — не на каждый кадр (LS-009). Позиция в мир не пишется."""
        assert self._spawner is not None  # вызывается только когда движок собран
        current = {obj.passport.object_id: obj.passport for obj in self._spawner.active_objects()}
        current_ids = frozenset(current)
        if current_ids == self._last_object_ids:
            return
        self._last_object_ids = current_ids
        if self._ctx.state_proxy is not None:
            self._ctx.state_proxy.set(_OBJECTS_PATH, {oid: passport.to_dict() for oid, passport in current.items()})

    def _update_truth_belt(self, before_ids: set[str], after: dict[str, Any]) -> None:
        """Task 5.2 (контракт лида §2): id, появившиеся между снимком до и после
        `spawner.tick()`, -> `ledger.on_spawn(passport)`; id, исчезнувшие -> `ledger.
        on_despawn(id)`. Объект, снятый заданием в ЭТОМ ЖЕ кадре (`_drain_jobs` идёт до
        `tick()`), уже отсутствует и в `before_ids` — diff его не видит, поэтому такой
        объект не попадает в `on_despawn` дважды (он уже решён через `on_match`)."""
        after_ids = set(after)
        new_ids = after_ids - before_ids
        gone_ids = before_ids - after_ids
        if not new_ids and not gone_ids:
            return
        with self._truth_lock:
            for object_id in new_ids:
                self._truth.on_spawn(after[object_id])
            for object_id in gone_ids:
                self._truth.on_despawn(object_id)

    def _publish_truth_metrics(self) -> None:
        """Task 5.2 (контракт лида §2) + 5.1b (§3): шесть уровней `truth_*` на своём
        такте, не чаще раза в `truth_publish_s` (``publish_metric`` просит звать на
        своём такте, а не на кадре — см. ``multiprocess_framework/modules/
        process_module/plugins/base.py``). Первый `produce()` публикует
        (``_truth_last_pub is None``)."""
        now = time.monotonic()
        if self._truth_last_pub is not None and (now - self._truth_last_pub) < self._truth_publish_s:
            return
        self._truth_last_pub = now
        with self._truth_lock:
            counters = self._truth.counters()
        self._ctx.publish_metric("truth_caught", counters["caught"])
        self._ctx.publish_metric("truth_dup_jobs", counters["dup_jobs"])
        self._ctx.publish_metric("truth_missed", counters["missed"])
        self._ctx.publish_metric("truth_false_alarm", counters["false_alarm"])
        self._ctx.publish_metric("truth_false_alarm_frozen_xy", counters["false_alarm_frozen_xy"])
        self._ctx.publish_metric("truth_on_belt", counters["on_belt"])

    def _warn_factory_error(self, exc: Exception) -> None:
        """`spawner.tick()` упал (обычно — сбой фабрики) — кадр отдаётся с прежней сценой,
        предупреждение де-дублировано (не чаще раза в секунду, `_FACTORY_ERROR_LOG_INTERVAL_S`)."""
        now = time.monotonic()
        if (
            self._last_factory_error_t is not None
            and (now - self._last_factory_error_t) < _FACTORY_ERROR_LOG_INTERVAL_S
        ):
            return
        self._last_factory_error_t = now
        self._ctx.log_error(f"scene_source: spawner.tick() упал: {exc!r} — кадр отдаётся с прежней сценой")

    def _warn_stale(self, t: float, age_ms: float) -> None:
        """Предупредить о протухшем значении мира — не чаще одного раза на ``t``."""
        if t == self._last_warned_t:
            return
        self._last_warned_t = t
        self._ctx.log_warning(
            f"scene_source: значение мира устарело на {age_ms:.0f} мс (> stale_ms={self._stale_ms}) — "
            f"позиция объектов не экстраполируется"
        )
