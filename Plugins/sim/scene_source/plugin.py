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

**Task 3.6 — фон-текстура ленты.** Ключ конфига ``background_texture`` (путь,
относительный — от корня репозитория, тем же ``_resolve_preset_path``, что и
``preset_path``) читается через ``imread_unicode``/BGR->RGB и передаётся в
``SceneCompositor`` как ``background_tile``. Файл не читается (нет файла, битые байты)
— ровно один ``ctx.log_error`` в ``configure()``, движок остаётся живым на сплошном
фоне (``background_bgr``); из ``produce()`` по этой причине ошибок нет. Ветка «движок
недоступен» (``_background_only_frame``) текстуру не использует — это отдельный,
более редкий отказ (каталог классов недоступен), out of scope для 3.6.
"""

from __future__ import annotations

import collections
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)
from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from Services.dataset_gen.core.catalog import imread_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, SceneCompositor, ScenePreset
from Services.line_sim.core import BeltGeometry, JobDone, MatchResult, TruthLedger, match_job

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
_DEFAULT_DEFECT_PROBABILITY = 0.0
_DEFAULT_CAMERA_ID = 0

#: Task 3.5 (контракт лида §4): сопоставление «задание выполнено» ↔ объект сцены.
_DEFAULT_MATCH_RADIUS_MM = 5.0
_DEFAULT_DUP_WINDOW_S = 10.0  # тот же дефолт, что у SimJournal
_RECENT_MAXLEN = 32

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

#: Максимальное значение счётчика кадров (rollover, как у остальных источников сима).
_FRAME_ID_MODULO = 100_000

#: Корень репозитория, вычисленный от расположения ЭТОГО файла
#: (Plugins/sim/scene_source/plugin.py -> parents[3]) — фикс ревью P5: относительный
#: `preset_path` раньше резолвился против CWD процесса (только `ScenePreset.from_yaml`
#: резолвит от каталога YAML, а плагин строит `ScenePreset(catalog_dir=...)` напрямую),
#: поэтому один и тот же конфиг давал движок то готовым, то insensitive к фону в
#: зависимости от того, откуда запущен процесс (repro: cwd=repo root -> движок готов;
#: cwd=apps/line_sim -> недоступен).
_REPO_ROOT = Path(__file__).resolve().parents[3]


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
        belt_direction = int(cfg.get("belt_direction", 1))
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
        defect_probability = float(cfg.get("defect_probability", _DEFAULT_DEFECT_PROBABILITY))
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
        self._match_radius_mm = float(cfg.get("match_radius_mm", _DEFAULT_MATCH_RADIUS_MM))
        self._dup_window_s = float(cfg.get("dup_window_s", _DEFAULT_DUP_WINDOW_S))
        self._jobs: collections.deque[JobDone] = collections.deque()
        self._removed: collections.deque[tuple[float, Any]] = collections.deque()
        self._recent: collections.deque[dict] = collections.deque(maxlen=_RECENT_MAXLEN)

        # Task 5.2 (контракт лида §2): правда на проводе — свой лок (НЕ self._lock мира),
        # чтобы truth.status/truth.reset из потока команд не ждали лок мира и наоборот.
        self._truth = TruthLedger()
        self._truth_lock = threading.Lock()
        self._truth_publish_s = float(cfg.get("truth_publish_s", _DEFAULT_TRUTH_PUBLISH_S))
        self._truth_last_pub: float | None = None
        for level_name in _TRUTH_LEVELS:
            ctx.declare_metric(level_name)

        # Task 3.6: фон-текстура строится ДО try-блока сборки движка — нечитаемый файл
        # не должен ронять движок целиком (он остаётся живым на сплошном фоне).
        background_texture = cfg.get("background_texture")
        background_tile = self._load_background_tile(ctx, background_texture)

        self._spawner: ObjectSpawner | None = None
        self._compositor: SceneCompositor | None = None
        try:
            preset = ScenePreset(catalog_dir=preset_path, defect_probability=defect_probability)
            factory = ObjectFactory(preset)
            self._spawner = ObjectSpawner(factory, scene_length_mm=scene_length_mm, **spawner_kwargs)
            self._compositor = SceneCompositor(
                self._spawner,
                px_per_mm=px_per_mm,
                belt_y_px=belt_y_px,
                background_bgr=_BACKGROUND_BGR,
                background_tile=background_tile,
                belt_direction=belt_direction,
                entry_x_px=entry_x_px,
            )
        except Exception as exc:  # noqa: BLE001 — любой сбой сборки движка не должен ронять configure()
            ctx.log_error(
                f"scene_source: движок сцены недоступен (preset_path={preset_path!r}): {exc!r} — "
                "кадры будут только фоном"
            )

        if background_tile is not None:
            tile_h, tile_w = background_tile.shape[:2]
            background_desc = f"текстура ({background_texture}, {tile_w}x{tile_h})"
        else:
            background_desc = f"цвет {_BACKGROUND_BGR}"

        ctx.log_info(
            f"scene_source: {self._width}x{self._height}, px_per_mm={px_per_mm}, belt_y_px={belt_y_px}, "
            f"spawner_kwargs={spawner_kwargs}, preset_path={preset_path!r}, фон={background_desc}, "
            f"движок={'готов' if self._compositor is not None else 'недоступен (fallback на фон)'}"
        )

    @staticmethod
    def _resolve_preset_path(preset_path: str | None) -> str | None:
        """Относительный `preset_path` — от КОРНЯ РЕПОЗИТОРИЯ (`_REPO_ROOT`), не от CWD
        процесса (фикс ревью P5). `None` и уже абсолютный путь возвращаются как есть."""
        if preset_path is None or Path(preset_path).is_absolute():
            return preset_path
        return str((_REPO_ROOT / preset_path).resolve())

    def _load_background_tile(self, ctx: PluginContext, texture_path: str | None) -> np.ndarray | None:
        """Загрузить фон-текстуру (Task 3.6): `None` -> `None`; путь резолвится от
        корня репозитория тем же `_resolve_preset_path`, что и `preset_path`. ЛЮБАЯ
        причина нечитаемости (нет файла — `OSError` из `np.fromfile`, битые байты —
        `ValueError` из `imread_unicode`) даёт ровно один `ctx.log_error` и откат на
        `None` (сплошной фон) — этот метод НЕ внутри try/except сборки движка, сбой
        текстуры не должен глушить остальную сборку."""
        if texture_path is None:
            return None
        resolved = self._resolve_preset_path(texture_path)
        try:
            bgr = imread_unicode(resolved, cv2.IMREAD_COLOR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception as exc:  # noqa: BLE001 — файл не найден/битый — откат на цвет, не падение
            ctx.log_error(
                f"scene_source: фон-текстура недоступна (background_texture={resolved!r}): {exc!r} — "
                "используется сплошной фон"
            )
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
                except Exception as exc:  # noqa: BLE001 — сбой фабрики не должен ронять кадровый цикл
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
        except Exception as exc:  # noqa: BLE001 — кривые аргументы -> ответ, не исключение
            return {"status": "error", "message": f"scene.job_done: кривые аргументы {data!r}: {exc!r}"}
        self._jobs.append(job)
        return {"status": "ok"}

    def cmd_status(self, data: dict | None = None) -> dict:
        """`scene.status` (поток команд): число активных объектов + последние исходы.

        `active_objects()` — копия списка (`list(...)`, одна C-операция под GIL), спавнер
        отсюда не мутируется."""
        active = len(self._spawner.active_objects()) if self._spawner is not None else 0
        with self._lock:
            recent = list(self._recent)
        return {"status": "ok", "active": active, "recent": recent}

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
