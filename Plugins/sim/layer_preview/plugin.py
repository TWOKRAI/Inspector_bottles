# -*- coding: utf-8 -*-
"""``LayerPreviewPlugin`` — команды ``preset.preview`` / ``layout`` / ``sprites`` в отдельном процессе (ревью 1.2a S1).

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

``preset.layout`` (Task 1.3h-a): ``seed`` (целое >= 0, по умолчанию 0) / ``preset`` — каждый слой
пресета отдельной RGBA-картинкой в номинале (без augment, угол объекта 0), см.
``Services.line_sim.core.preview.render_layout``. Ответ ``ok`` + ``class_name`` + ``canvas_px`` +
``layers``; те же ``bad_request`` / ``invalid`` и та же ограда путей, что у ``preset.preview``.

``preset.sprites`` (Task 1.3h-c): PNG-файлы каталога ``sprites_dir`` (ключ конфига, по умолчанию ``data/line_sim``;
относительный — от корня репозитория) для редактора слоёв; тело запроса — ``{}``. Ответ ``ok`` + ``dir`` +
``files`` (``[{path, sprite_source}]``: ``path`` — от ``sprites_dir``, ``sprite_source`` — от каталога файла пресета
хоста, у пресета без файла — от корня репо; прямые слэши; рекурсивно, ``.png`` без учёта регистра, по ``path``,
не больше 500 — иначе ``truncated: true``) + ``layer_template`` (полный ``LayerSpec`` с дефолтами). Ограда
путей — та же, что у ``preset.layout``: файл, чей ``resolve()`` вне неё (симлинк наружу), в список не попадает.
Ошибки: ``bad_request`` (тело не dict; ``sprites_dir`` вне ограды — проверяется РАНЬШЕ существования),
``io_error`` (каталога нет / не каталог / не читается; путь в ``message``). RGBA не проверяется — это делает
``preset.layout``. Запись ``{path, sprite_source}`` строит ``sprite_entry`` (её же позовёт запись 1.3h-d).
"""

from __future__ import annotations

import base64
import os
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
from Services.line_sim import LayerSpec
from Services.line_sim.core.preview import PREVIEW_DEFAULT_SEEDS, PREVIEW_DEFAULT_TILE_PX, render_layout

SPRITES_DIR_DEFAULT = "data/line_sim"  # каталог PNG по умолчанию (от корня репо; `data/` в .gitignore)
SPRITES_MAX_FILES = 500  # потолок списка ``preset.sprites``; лишнее отрезается с ``truncated: true``


@register_plugin("layer_preview", category="control", description="Превью пресета слоёв line_sim (процесс layers)")
class LayerPreviewPlugin(ProcessModulePlugin):
    """Side-effect плагин: команды ``preset.preview`` и ``preset.layout``."""

    name = "layer_preview"
    category = "control"

    inputs: list = []
    outputs: list = []
    commands: dict = {
        "preset.preview": "cmd_preset_preview",
        "preset.layout": "cmd_preset_layout",
        "preset.sprites": "cmd_preset_sprites",
    }

    def configure(self, ctx: PluginContext) -> None:
        cfg = dict(ctx.config)
        self._preset_path: str | None = resolve_repo_path(cfg.get("preset_path"))
        self._sprites_dir: str = resolve_repo_path(cfg.get("sprites_dir") or SPRITES_DIR_DEFAULT)
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

    def cmd_preset_layout(self, data: dict | None = None) -> dict:
        """``preset.layout`` — см. докстринг модуля."""
        data = data if data is not None else {}
        if not isinstance(data, dict):
            return _bad_request("preset.layout: ожидается dict")
        seed = data.get("seed", 0)
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            return _bad_request("preset.layout: seed — целое >= 0")
        preset_dict = data.get("preset")
        if preset_dict is not None and not isinstance(preset_dict, dict):
            return _bad_request("preset.layout: preset — dict или отсутствует")
        try:
            preset = self._client_preset(preset_dict) if preset_dict is not None else self._configured_preset()
            layout = render_layout(preset, seed)
        except Exception as exc:  # noqa: BLE001 — любой сбой сборки раскладки -> invalid с текстом
            return {"status": "error", "code": "invalid", "message": str(exc)}
        return {"status": "ok", **layout}

    def cmd_preset_sprites(self, data: dict | None = None) -> dict:
        """``preset.sprites`` — см. докстринг модуля."""
        data = data if data is not None else {}
        if not isinstance(data, dict):
            return _bad_request("preset.sprites: ожидается dict")
        roots = [root.resolve() for root in self._allowed_roots()]
        sprites_dir = Path(self._sprites_dir).resolve()
        # Ограда — ДО проверки существования: каталог вне ограды и отсутствующий — bad_request.
        if not _inside(sprites_dir, roots):
            return _bad_request("preset.sprites: sprites_dir вне разрешённых каталогов (корень репо, каталог пресета)")
        try:
            if not sprites_dir.is_dir():
                return _io_error(f"preset.sprites: не каталог или отсутствует: {sprites_dir}")
            os.listdir(sprites_dir)  # нечитаемый каталог -> OSError; os.walk молча пропустил бы его
        except OSError as exc:
            return _io_error(f"preset.sprites: каталог не читается: {sprites_dir} ({exc})")
        base_dir = self._preset_dir() or REPO_ROOT
        entries = []
        # os.walk без followlinks не заходит в симлинк-каталог, но на Windows заходит в junction (петля
        # `loop -> ..` даёт ~32 дубля файла): junction выкидываем из обхода сами (hazard-тест).
        # Полный обход ради сортировки до усечения; ponytail: огромное дерево — дорого, потолок 500 — на ответе.
        for dirpath, dirnames, filenames in os.walk(sprites_dir):
            dirnames[:] = [name for name in dirnames if not os.path.isjunction(Path(dirpath, name))]
            for filename in filenames:
                file = Path(dirpath, filename)
                if file.suffix.lower() != ".png" or not file.is_file():
                    continue
                try:
                    if not _inside(file.resolve(), roots):
                        continue  # симлинк наружу: preset.commit такой путь отверг бы
                    entries.append(sprite_entry(file, sprites_dir, base_dir))
                except (OSError, RuntimeError, ValueError):
                    continue  # петля симлинков / relpath между дисками — файл вне ограды
        entries.sort(key=lambda entry: entry["path"])
        return {
            "status": "ok",
            "dir": _dir_for_reply(sprites_dir),
            "files": entries[:SPRITES_MAX_FILES],
            "truncated": len(entries) > SPRITES_MAX_FILES,
            "layer_template": LayerSpec(name="_", mode="static", sprite_source="_").model_dump(mode="json"),
        }

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
        preset = ScenePreset.from_dict({**preset_dict, "base_dir": str(self._preset_dir() or REPO_ROOT)})
        confine_preset_paths(preset, self._allowed_roots())
        return apply_defect_override(preset, self._defect_override)

    def _preset_dir(self) -> Path | None:
        """Каталог файла пресета хоста; ``None`` у каталожного пресета (``base_dir`` тогда — корень репозитория)."""
        return Path(self._preset_path).parent.resolve() if self._is_file else None

    def _allowed_roots(self) -> list[Path]:
        """Ограда путей картинок — ОДНО правило для ``preset.layout``/``preview`` и ``preset.sprites``."""
        preset_dir = self._preset_dir()
        return [REPO_ROOT] if preset_dir is None else [REPO_ROOT, preset_dir]


def sprite_entry(file: Path, sprites_dir: Path, base_dir: Path) -> dict[str, str]:
    """Запись списка спрайтов ``{path, sprite_source}`` для файла в ``sprites_dir``.

    ``path`` — от ``sprites_dir`` (подпись в списке), ``sprite_source`` — от ``base_dir`` (каталог файла пресета
    хоста; значение, которое страница вписывает в слой). Прямые слэши на любой ОС. Единственное место, где
    считается ``sprite_source``: Task 1.3h-d (загрузка PNG из браузера) зовёт эту же функцию для сохранённого файла.
    ``ValueError`` — ``relpath`` между дисками (файл вне ограды); решает вызывающий.
    """
    return {
        "path": os.path.relpath(file, sprites_dir).replace(os.sep, "/"),
        "sprite_source": os.path.relpath(file, base_dir).replace(os.sep, "/"),
    }


def _inside(path: Path, roots: list[Path]) -> bool:
    """``path`` (уже ``resolve()``) лежит в одном из ``roots`` (уже ``resolve()``)."""
    return any(path.is_relative_to(root) for root in roots)


def _dir_for_reply(sprites_dir: Path) -> str:
    """Каталог для ответа: от корня репозитория (прямые слэши), если он внутри репо, иначе абсолютный."""
    if sprites_dir.is_relative_to(REPO_ROOT):
        return sprites_dir.relative_to(REPO_ROOT).as_posix()
    return str(sprites_dir)


def _bad_request(message: str) -> dict[str, Any]:
    return {"status": "error", "code": "bad_request", "message": message}


def _io_error(message: str) -> dict[str, Any]:
    return {"status": "error", "code": "io_error", "message": message}
