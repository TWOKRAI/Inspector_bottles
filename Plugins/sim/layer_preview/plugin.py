# -*- coding: utf-8 -*-
"""``LayerPreviewPlugin`` — команда ``preset.preview`` в отдельном процессе (ревью 1.2a S1).

Превью реального пресета стоит ~87 мс (почти всё — ``ObjectFactory.make`` на полном спрайте).
В процессе сцены это время держало бы единственный поток команд — тот же, что дренирует
дельты энкодера и ``scene.job_done``. Поэтому превью — свой процесс ``layers`` из
``GenericProcess`` с этим плагином (конструктор фреймворка, без своих потоков/очередей).
Плагин без портов (side-effect, как ``pult_web``); живую ленту не видит вовсе.

Конфиг: ``preset_path`` (относительный — от корня репозитория, ``resolve_repo_path``) и опц.
``defect_probability`` — то же правило, что у ``scene_source`` (``load_scene_preset`` /
``apply_defect_override`` из ``Services.line_sim.core``; плагин ``scene_source`` не
импортируется). Держать равными значениям ``scene_source`` в ``pipeline.yaml``.

``preset.preview``: ``seeds`` / ``tile_px`` / ``preset`` — пределы и форма ответа см.
``Services.line_sim.core.preview``. Без ``preset`` — пресет файла: файл перечитывается,
когда сменился ``compute_rev`` его байт (commit через ``scene_source`` виден без рестарта);
пресет-каталог (не ``.yaml``) строится один раз. С ``preset`` клиента — ``base_dir``
принудительно каталог файла (у каталожного — корень репозитория), пути картинок — только в
корне репозитория или каталоге файла (``confine_preset_paths``). Ответы: ``ok`` +
``png_b64`` + ``tiles``; ``bad_request`` (форма/пределы); ``invalid`` (пресет/картинки).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)
from multiprocess_framework.modules.recipe.service import compute_rev
from Services.line_sim.core import (
    REPO_ROOT,
    PreviewLimitError,
    ScenePreset,
    apply_defect_override,
    confine_preset_paths,
    load_scene_preset,
    render_preview_grid,
    resolve_repo_path,
    validate_preview_request,
)
from Services.line_sim.core.preview import PREVIEW_DEFAULT_SEEDS, PREVIEW_DEFAULT_TILE_PX


@register_plugin("layer_preview", category="control", description="Превью пресета слоёв line_sim (процесс layers)")
class LayerPreviewPlugin(ProcessModulePlugin):
    """Side-effect плагин: одна команда ``preset.preview``."""

    name = "layer_preview"
    category = "control"

    inputs: list = []
    outputs: list = []
    commands: dict = {"preset.preview": "cmd_preset_preview"}

    def configure(self, ctx: PluginContext) -> None:
        cfg = dict(ctx.config)
        self._preset_path: str | None = resolve_repo_path(cfg.get("preset_path"))
        self._is_file = self._preset_path is not None and self._preset_path.lower().endswith((".yaml", ".yml"))
        self._defect_override: float | None = float(cfg["defect_probability"]) if "defect_probability" in cfg else None
        # (rev байт файла | None у каталожного, пресет с override) — только поток команд.
        self._file_state: tuple[str | None, ScenePreset] | None = None
        ctx.log_info(f"layer_preview: preset_path={self._preset_path!r}, override={self._defect_override!r}")

    def start(self, ctx: PluginContext) -> None:
        """Нечего запускать: команды обслуживает поток команд процесса."""

    def cmd_preset_preview(self, data: dict | None = None) -> dict:
        """``preset.preview`` — см. докстринг модуля."""
        data = data if data is not None else {}
        if not isinstance(data, dict):
            return _bad_request("preset.preview: ожидается dict")
        seeds = data.get("seeds", list(PREVIEW_DEFAULT_SEEDS))
        tile_px = data.get("tile_px", PREVIEW_DEFAULT_TILE_PX)
        try:
            validate_preview_request(seeds, tile_px)
        except PreviewLimitError as exc:
            return _bad_request(str(exc))
        preset_dict = data.get("preset")
        if preset_dict is not None and not isinstance(preset_dict, dict):
            return _bad_request("preset.preview: preset — dict или отсутствует")
        try:
            preset = self._client_preset(preset_dict) if preset_dict is not None else self._configured_preset()
            png, tiles = render_preview_grid(preset, seeds, tile_px)
        except Exception as exc:  # noqa: BLE001 — любой сбой сборки превью -> invalid с текстом
            return {"status": "error", "code": "invalid", "message": str(exc)}
        return {"status": "ok", "png_b64": base64.b64encode(png).decode("ascii"), "tiles": tiles}

    def _configured_preset(self) -> ScenePreset:
        """Пресет конфига с override; файл — перечитывается при смене ``rev`` его байт."""
        rev = compute_rev(Path(self._preset_path).read_bytes()) if self._is_file else None
        state = self._file_state
        if state is not None and state[0] == rev:
            return state[1]
        preset = load_scene_preset(self._preset_path, self._defect_override)
        self._file_state = (rev, preset)
        return preset

    def _client_preset(self, preset_dict: dict) -> ScenePreset:
        """Пресет клиента: ``base_dir`` — каталог файла (каталожный — корень репозитория), ограда
        путей ДО чтения картинок, затем override стенда."""
        preset_dir = Path(self._preset_path).parent.resolve() if self._is_file else None
        preset = ScenePreset.from_dict({**preset_dict, "base_dir": str(preset_dir or REPO_ROOT)})
        confine_preset_paths(preset, [REPO_ROOT] if preset_dir is None else [REPO_ROOT, preset_dir])
        return apply_defect_override(preset, self._defect_override)


def _bad_request(message: str) -> dict[str, Any]:
    return {"status": "error", "code": "bad_request", "message": message}
