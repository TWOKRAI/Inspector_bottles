# -*- coding: utf-8 -*-
"""``SceneSourcePlugin`` — источник кадров сцены симулятора (Task 2.2 line-sim).

Source-плагин (форма — ``Plugins/sources/synthetic_frame_source``): фон + один
тестовый спрайт-заглушка, положение которого следует за энкодером ленты из
общего мира (``sim.belt.*`` в дереве ``StateStore``, Task 2.1/2.1b). Реальные
объекты, спавн/деспавн и слои — Ф3.

**Чтение мира — подпиской, не ``get()`` (Решение ведущего, план line-sim,
Task 2.2).** ``StateProxy.get()`` без предварительной подписки на путь ВСЕГДА
уходит в синхронный IPC-раундтрип (до 5 с, см. ``state_proxy.py:288-320``), а
``produce()`` вызывается на каждый кадр — синхронный ``get`` с приёмного
потока (или из воркера, но это дорого) недопустим. Поэтому ``configure()``
подписывается на ``sim.belt.**`` (``sync=False`` — тот же приём и то же
обоснование, что у ``TelemetrySinkPlugin.start``: подписка регистрируется ДО
того, как у процесса вообще есть приёмный поток, синхронный раундтрип ждать
некому), а колбэк только кладёт последнее значение в поле плагина под
``Lock`` — ни одного IPC на кадр.

**Обе формы дельт паблишера (``SimRobotHostPlugin._publish_once``).** Первый
``set()`` пути ``sim.belt.encoder`` в пустое дерево — дельта СОЗДАНИЯ узла
целиком (``new_value`` — весь словарь ``{value, mm_s, t}``); все последующие —
ПОЛИСТОВЫЕ дельты (``sim.belt.encoder.value`` / ``.mm_s`` / ``.t``), потому
что ``TreeStore._merge_recursive`` на существующем узле раздаёт дифф по
листьям. :meth:`_on_deltas` обрабатывает обе формы одним и тем же кодом.

**Протухшее значение — предупреждение, не экстраполяция.** Позиция спрайта
всегда берётся из ПОСЛЕДНЕЙ ДОСТАВЛЕННОЙ дельты (нет отдельного пути
«время идёт — двигай спрайт по времени»), поэтому «заморозка» между двумя
кадрами на неизменном мире — не отдельный код, а прямое следствие того, что
между ними не пришло новой дельты. Единственный НАБЛЮДАЕМЫЙ эффект протухания
в этой версии — предупреждение через ``ctx.log_warning`` (де-дублировано по
``t``, чтобы не заспамить лог на неизменном протухшем значении).

**Спрайт — один пиксельный столбец, а не полоса (интерпретация, НЕ буквальная
часть DESIGN брифа — см. отчёт разработчика).** Тестер меряет положение
диффом ТЕКУЩЕГО кадра против ЭТАЛОНА, снятого на ``spawn_encoder`` (позиция
0). Если бы спрайт на позиции 0 был виден, любой более поздний кадр давал бы
ДВА пика диффа (опустевшее место + новое) и взвешенный центр масс не совпадал
бы с ожидаемой формулой в пределах допуска (±2 px). Отсюда — задний край
привязки: видимый столбец = ``round(x_px) - 1``, и на ``x_px=0`` столбец -1 не
существует (спрайт «ещё не въехал» в кадр, эталон на spawn — чистый фон).
Значение южнее 0 (назад по ленте) тоже невидимо; значение восточнее правого
края (протухший/далёкий отсчёт) зажимается к последней видимой колонке — не
пропадает совсем, потому что деспавна в этой версии нет (Ф3).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)
from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from Services.robot_comm.core.registers import FACTOR_MM

if TYPE_CHECKING:
    from multiprocess_framework.modules.state_store_module.core.delta import Delta

#: Дефолты конфига — форма как у ``synthetic_frame_source``.
_DEFAULT_WIDTH = 640
_DEFAULT_HEIGHT = 480
_DEFAULT_SPAWN_ENCODER = 0
_DEFAULT_PX_PER_MM = 1.0
_DEFAULT_STALE_MS = 500
_DEFAULT_SEED = 0

#: Путь мира (Task 2.1/2.1b, паблишер — ``Plugins.sim.robot_host``).
_ENCODER_PATH = "sim.belt.encoder"
_WORLD_PATTERN = "sim.belt.**"

#: BGR — красный, заведомо отличим от серого фона при любом ``seed``
#: (см. :meth:`SceneSourcePlugin.configure`).
_SPRITE_COLOR = (0, 0, 255)

#: Максимальное значение счётчика кадров (rollover, как у остальных источников сима).
_FRAME_ID_MODULO = 100_000


@register_plugin(
    "scene_source",
    category="source",
    description="Источник кадров сцены сима: фон + тестовый спрайт по энкодеру ленты",
)
class SceneSourcePlugin(ProcessModulePlugin):
    """Фон + один спрайт, следующий за энкодером общего мира.

    Lifecycle:
        configure() -- параметры кадра/сцены, разбор конфига
        start()     -- подписка на мир (``sim.belt.**``, sync=False)
        produce()   -- вернуть кадр с текущим положением спрайта
    """

    name = "scene_source"
    category = "source"

    inputs: list = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр сцены сима"),
    ]
    commands: dict = {}

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, завести фон и накопитель мира."""
        self._ctx = ctx
        cfg = ctx.config
        self._width: int = cfg.get("resolution_width", _DEFAULT_WIDTH)
        self._height: int = cfg.get("resolution_height", _DEFAULT_HEIGHT)
        self._spawn_encoder: int = cfg.get("spawn_encoder", _DEFAULT_SPAWN_ENCODER)
        self._px_per_mm: float = cfg.get("px_per_mm", _DEFAULT_PX_PER_MM)
        self._stale_ms: float = cfg.get("stale_ms", _DEFAULT_STALE_MS)

        # seed стенда (план line-sim, Task 2.2): в этой версии определяет только
        # оттенок фона (детерминированно, без cv2/random) — ponytail: реальные
        # текстуры/раскладка сцены отложены до Ф3, здесь параметр только
        # «подключён», а не заглушка без эффекта.
        seed = int(cfg.get("seed", _DEFAULT_SEED))
        base_gray = 64 + (seed % 128)
        self._base_frame = np.full((self._height, self._width, 3), base_gray, dtype=np.uint8)

        self._lock = threading.Lock()
        self._world: dict[str, Any] = {}
        self._last_warned_t: float | None = None
        self._frame_count = 0

        ctx.log_info(
            f"scene_source: {self._width}x{self._height}, spawn_encoder={self._spawn_encoder}, "
            f"px_per_mm={self._px_per_mm}, stale_ms={self._stale_ms}"
        )

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: подписаться на мир. Без ``state_proxy`` — спрайт живёт в spawn."""
        if ctx.state_proxy is None:
            ctx.log_warning("scene_source: ctx.state_proxy is None — мир недоступен, спрайт остаётся в spawn")
            return
        ctx.state_proxy.subscribe(_WORLD_PATTERN, self._on_deltas, exclude_self=True, sync=False)

    # ------------------------------------------------------------------ #
    # Подписка на мир
    # ------------------------------------------------------------------ #

    def _on_deltas(self, deltas: list["Delta"]) -> None:
        """Колбэк подписки: только копим последнее значение, без I/O.

        Обе формы дельт паблишера (см. докстринг модуля) сводятся к одному и
        тому же результату — ``self._world`` держит ЛИСТЬЯ (``value``/``mm_s``/
        ``t``), как и накопитель ``TelemetrySinkPlugin._cache_put``.
        """
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

    # ------------------------------------------------------------------ #
    # Рендер
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Вернуть один кадр сцены с текущим положением спрайта."""
        with self._lock:
            snapshot = dict(self._world)

        value = snapshot.get("value", self._spawn_encoder)
        t = snapshot.get("t")
        if t is not None:
            age_ms = (time.monotonic() - t) * 1000.0
            if age_ms > self._stale_ms:
                self._warn_stale(t, age_ms)

        x_px = (value - self._spawn_encoder) * FACTOR_MM * self._px_per_mm
        frame = self._base_frame.copy()
        col = self._sprite_column(x_px, self._width)
        if col is not None:
            frame[:, col] = _SPRITE_COLOR

        self._frame_count = (self._frame_count % _FRAME_ID_MODULO) + 1
        return [
            {
                "frame": frame,
                "seq_id": self._frame_count,
                "frame_id": self._frame_count,
                "timestamp": time.monotonic(),
                "width": self._width,
                "height": self._height,
                "channels": 3,
                "dtype": "uint8",
            }
        ]

    @staticmethod
    def _sprite_column(x_px: float, width: int) -> int | None:
        """Видимая колонка спрайта — см. докстринг модуля («интерпретация»).

        Задний край: колонка = ``round(x_px) - 1``. ``x_px <= 0`` (спрайт ещё
        не въехал) -> ``None`` (не рисуем). ``x_px`` за правым краем -> зажим
        к последней колонке (не пропадает, деспавна нет — Ф3).
        """
        col = int(round(x_px)) - 1
        if col < 0:
            return None
        if col >= width:
            return width - 1
        return col

    def _warn_stale(self, t: float, age_ms: float) -> None:
        """Предупредить о протухшем значении мира — не чаще одного раза на ``t``."""
        if t == self._last_warned_t:
            return
        self._last_warned_t = t
        self._ctx.log_warning(
            f"scene_source: значение мира устарело на {age_ms:.0f} мс (> stale_ms={self._stale_ms}) — "
            f"позиция спрайта не экстраполируется"
        )
