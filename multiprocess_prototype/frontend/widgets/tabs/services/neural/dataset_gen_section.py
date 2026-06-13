# -*- coding: utf-8 -*-
"""Секция «Генерация датасета» — UI поверх Services/dataset_gen.

Две подвкладки:
  «Генерация» — пресет, объёмы train/val/test, превью-сетка, фоновая генерация
    (движок ~1с init, генерация десятки секунд → QThread-воркер + прогресс);
  «Данные и параметры» — редактирование путей (классы/фоны) и размера кадра
    с сохранением в пресет (ruamel, комментарии не теряются) + три панели
    просмотра: «Фон» / «Класс» / «Наложение» с листанием всех вариантов.

Пути в пресетах dataset_gen относительные — от каталога YAML-файла;
при отображении и сохранении это учитывается (_resolve/_relativize).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.main import PROJECT_ROOT

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_PANEL_SIZE = 240  # сторона панели-«дисплея», px


# ---------------------------------------------------------------------------
# Помощники данных (модульные — покрываются тестами без Qt)
# ---------------------------------------------------------------------------


def _imread_any(path: Path) -> np.ndarray | None:
    """Прочитать изображение (BGR или BGRA) с unicode-путём (Windows)."""
    try:
        import cv2

        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:  # noqa: BLE001 — битый файл показываем как «нет изображения»
        return None


def scan_classes(classes_dir: Path) -> dict[str, list[Path]]:
    """Листовые папки-классы → их спрайты (зеркало правил каталога dataset_gen)."""
    result: dict[str, list[Path]] = {}
    if not classes_dir.is_dir():
        return result
    for child in sorted(classes_dir.rglob("*")):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        images = sorted(p for p in child.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
        has_subdirs = any(c.is_dir() and not c.name.startswith((".", "_")) for c in child.iterdir())
        if images and not has_subdirs:
            result[child.name] = images
    return result


def scan_backgrounds(backgrounds_dir: Path | None) -> list[Path]:
    """Файлы фонов рекурсивно (None/пусто → процедурные фоны движка)."""
    if backgrounds_dir is None or not backgrounds_dir.is_dir():
        return []
    return sorted(p for p in backgrounds_dir.rglob("*") if p.suffix.lower() in _IMAGE_SUFFIXES)


def compose_overlay(bg_bgr: np.ndarray | None, sprite: np.ndarray | None, canvas: int = 256) -> np.ndarray:
    """Наложение спрайта на фон по центру (alpha-blend), BGR-результат.

    Сырая композиция без аугментаций — «как сочетаются данные»; реальная
    генерация (поворот/свет/шум) — кнопка «Превью» на вкладке «Генерация».
    """
    import cv2

    if bg_bgr is not None:
        h, w = bg_bgr.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        base = cv2.resize(bg_bgr[y0 : y0 + side, x0 : x0 + side, :3], (canvas, canvas))
    else:
        base = np.full((canvas, canvas, 3), 64, dtype=np.uint8)
    if sprite is None:
        return base

    target = int(canvas * 0.7)
    sh, sw = sprite.shape[:2]
    scale = target / max(sh, sw)
    sprite = cv2.resize(sprite, (max(1, int(sw * scale)), max(1, int(sh * scale))))
    sh, sw = sprite.shape[:2]
    y0, x0 = (canvas - sh) // 2, (canvas - sw) // 2
    roi = base[y0 : y0 + sh, x0 : x0 + sw]
    if sprite.ndim == 3 and sprite.shape[2] == 4:
        alpha = sprite[:, :, 3:4].astype(np.float32) / 255.0
        roi[:] = (sprite[:, :, :3].astype(np.float32) * alpha + roi.astype(np.float32) * (1 - alpha)).astype(np.uint8)
    else:
        roi[:] = sprite[:, :, :3]
    return base


def load_preset_fields(preset_path: Path) -> dict[str, Any]:
    """Прочитать из пресета поля формы: classes_dir / backgrounds_dir / size (H, W).

    Относительные пути резолвятся от каталога пресета (контракт dataset_gen).
    """
    import yaml

    raw = yaml.safe_load(preset_path.read_text(encoding="utf-8")) or {}
    catalog = raw.get("catalog") or {}
    output = raw.get("output") or {}

    def _resolve(value: Any) -> Path | None:
        if not value:
            return None
        p = Path(str(value))
        return p if p.is_absolute() else (preset_path.parent / p).resolve()

    size = output.get("size") or [128, 128]
    return {
        "classes_dir": _resolve(catalog.get("classes_dir")),
        "backgrounds_dir": _resolve(catalog.get("backgrounds_dir")),
        "size_h": int(size[0]),
        "size_w": int(size[1]),
    }


def save_preset_fields(
    preset_path: Path,
    classes_dir: Path,
    backgrounds_dir: Path | None,
    size_hw: tuple[int, int],
) -> None:
    """Записать поля формы в пресет round-trip'ом (ruamel — комментарии сохраняются).

    Пути пишутся относительно каталога пресета, если это возможно (переносимость
    репозитория); иначе — абсолютными.
    """
    from ruamel.yaml import YAML

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    data = yaml_rt.load(preset_path.read_text(encoding="utf-8")) if preset_path.exists() else None
    if data is None:
        data = {}

    def _relativize(p: Path) -> str:
        try:
            return Path(os.path.relpath(p, preset_path.parent)).as_posix()
        except ValueError:  # другой диск Windows — relpath невозможен
            return str(p)

    data.setdefault("catalog", {})
    data["catalog"]["classes_dir"] = _relativize(classes_dir)
    data["catalog"]["backgrounds_dir"] = _relativize(backgrounds_dir) if backgrounds_dir else None
    data.setdefault("output", {})
    data["output"]["size"] = [int(size_hw[0]), int(size_hw[1])]
    with preset_path.open("w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)


def _np_to_pixmap(image: np.ndarray) -> QPixmap:
    """BGR/BGRA → QPixmap (копия буфера — np-массив временный)."""
    import cv2

    if image.ndim == 3 and image.shape[2] == 4:
        rgba = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        qimg = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format.Format_RGBA8888)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


# ---------------------------------------------------------------------------
# Воркер генерации/превью
# ---------------------------------------------------------------------------


class _GenWorker(QObject):
    """Воркер генерации/превью (живёт в QThread; сигналы — в GUI-поток)."""

    progress = Signal(int, int)  # done, total
    finished = Signal(str)  # путь результата (папка датасета | png превью)
    failed = Signal(str)

    def __init__(self, preset: str, mode: str, out_dir: str, splits: dict[str, int]) -> None:
        super().__init__()
        self._preset = preset
        self._mode = mode  # "preview" | "generate"
        self._out_dir = out_dir
        self._splits = splits

    def run(self) -> None:
        try:
            from Services.dataset_gen import DatasetEngine, export_splits, save_preview_grid

            engine = DatasetEngine.from_yaml(self._preset)
            if self._mode == "preview":
                out = Path(tempfile.gettempdir()) / "dataset_gen_preview.png"
                save_preview_grid(engine, str(out), n=16)
                self.finished.emit(str(out))
                return
            export_splits(
                engine,
                self._out_dir,
                splits=self._splits,
                progress_cb=lambda done, total: self.progress.emit(done, total),
            )
            self.finished.emit(self._out_dir)
        except Exception as exc:  # noqa: BLE001 — текст ошибки уходит в статус-лейбл
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Панель-«дисплей»
# ---------------------------------------------------------------------------


class _ImagePanel(QWidget):
    """Мини-дисплей: заголовок + изображение фиксированного размера."""

    def __init__(self, title: str, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(f"<b>{title}</b>")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)
        self._image = QLabel("—")
        self._image.setObjectName(object_name)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setFixedSize(_PANEL_SIZE, _PANEL_SIZE)
        self._image.setStyleSheet("border: 1px solid #555;")
        layout.addWidget(self._image, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_array(self, image: np.ndarray | None) -> None:
        if image is None:
            self._image.setText("нет изображения")
            self._image.setPixmap(QPixmap())
            return
        pixmap = _np_to_pixmap(image).scaled(
            self._image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self._image.setPixmap(pixmap)

    def set_text(self, text: str) -> None:
        self._image.setPixmap(QPixmap())
        self._image.setText(text)


# ---------------------------------------------------------------------------
# Основной виджет секции
# ---------------------------------------------------------------------------


class DatasetGenWidget(QWidget):
    """Секция: подвкладки «Генерация» и «Данные и параметры»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _GenWorker | None = None
        self._classes: dict[str, list[Path]] = {}
        self._bg_files: list[Path] = []
        self._sprite_idx = 0
        self._bg_idx = 0
        self._build_ui()
        self._reload_presets()
        self._load_preset_to_form()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Пресет:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("nn_dataset_preset")
        self.preset_combo.currentIndexChanged.connect(lambda _i: self._load_preset_to_form())
        preset_row.addWidget(self.preset_combo, stretch=1)
        browse_preset = QPushButton("Обзор…")
        browse_preset.setToolTip("Выбрать свой YAML-пресет генератора")
        browse_preset.clicked.connect(self._on_browse_preset)
        preset_row.addWidget(browse_preset)
        root.addLayout(preset_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_generate_tab(), "Генерация")
        self.tabs.addTab(self._build_data_tab(), "Данные и параметры")
        root.addWidget(self.tabs, stretch=1)

        self.status_label = QLabel("Готово к работе.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _build_generate_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit(str(PROJECT_ROOT / "data" / "dataset_gen" / "generated"))
        out_row.addWidget(self.out_edit, stretch=1)
        browse_out = QPushButton("Обзор…")
        browse_out.clicked.connect(self._on_browse_out)
        out_row.addWidget(browse_out)
        form.addRow("Выходная папка:", out_row)

        splits_row = QHBoxLayout()
        self.train_spin = self._spin(300)
        self.val_spin = self._spin(50)
        self.test_spin = self._spin(50)
        for label, spin in (("train", self.train_spin), ("val", self.val_spin), ("test", self.test_spin)):
            splits_row.addWidget(QLabel(f"{label}:"))
            splits_row.addWidget(spin)
        splits_row.addStretch()
        form.addRow("Кадров на класс:", splits_row)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.preview_btn = QPushButton("Превью генерации")
        self.preview_btn.setObjectName("nn_dataset_preview")
        self.preview_btn.setToolTip("Сетка 16 кадров с реальными аугментациями (без записи на диск)")
        self.preview_btn.clicked.connect(lambda: self._start_worker("preview"))
        btn_row.addWidget(self.preview_btn)
        self.generate_btn = QPushButton("Сгенерировать")
        self.generate_btn.setObjectName("nn_dataset_generate")
        self.generate_btn.clicked.connect(lambda: self._start_worker("generate"))
        btn_row.addWidget(self.generate_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.preview_label = QLabel("Нажмите «Превью генерации», чтобы увидеть сетку кадров.")
        self.preview_label.setObjectName("nn_dataset_preview_img")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(240)
        layout.addWidget(self.preview_label, stretch=1)
        return tab

    def _build_data_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        paths_box = QGroupBox("Параметры пресета")
        form = QFormLayout(paths_box)

        cls_row = QHBoxLayout()
        self.classes_edit = QLineEdit()
        self.classes_edit.setObjectName("nn_dataset_classes_dir")
        cls_row.addWidget(self.classes_edit, stretch=1)
        cls_browse = QPushButton("Обзор…")
        cls_browse.clicked.connect(lambda: self._browse_dir_into(self.classes_edit))
        cls_row.addWidget(cls_browse)
        form.addRow("Папка классов:", cls_row)

        bg_row = QHBoxLayout()
        self.backgrounds_edit = QLineEdit()
        self.backgrounds_edit.setObjectName("nn_dataset_backgrounds_dir")
        bg_row.addWidget(self.backgrounds_edit, stretch=1)
        bg_browse = QPushButton("Обзор…")
        bg_browse.clicked.connect(lambda: self._browse_dir_into(self.backgrounds_edit))
        bg_row.addWidget(bg_browse)
        self.procedural_check = QCheckBox("процедурные фоны")
        self.procedural_check.setToolTip("Без папки фонов: градиент/металл/лента — генерирует движок")
        self.procedural_check.toggled.connect(self._on_procedural_toggled)
        bg_row.addWidget(self.procedural_check)
        form.addRow("Папка фонов:", bg_row)

        size_row = QHBoxLayout()
        self.size_h_spin = self._spin(128, maximum=4096)
        self.size_w_spin = self._spin(128, maximum=4096)
        size_row.addWidget(QLabel("H:"))
        size_row.addWidget(self.size_h_spin)
        size_row.addWidget(QLabel("W:"))
        size_row.addWidget(self.size_w_spin)
        size_row.addStretch()
        form.addRow("Размер кадра:", size_row)

        save_row = QHBoxLayout()
        self.apply_btn = QPushButton("Обновить списки")
        self.apply_btn.setToolTip("Перечитать классы и фоны по указанным путям (без сохранения)")
        self.apply_btn.clicked.connect(self._rescan_data)
        save_row.addWidget(self.apply_btn)
        self.save_btn = QPushButton("Сохранить в пресет")
        self.save_btn.setObjectName("nn_dataset_save")
        self.save_btn.clicked.connect(self._on_save_preset)
        save_row.addWidget(self.save_btn)
        self.save_as_btn = QPushButton("Сохранить как…")
        self.save_as_btn.clicked.connect(self._on_save_preset_as)
        save_row.addWidget(self.save_as_btn)
        save_row.addStretch()
        form.addRow("", save_row)
        layout.addWidget(paths_box)

        nav_row = QHBoxLayout()
        nav_row.addWidget(QLabel("Класс:"))
        self.class_combo = QComboBox()
        self.class_combo.setObjectName("nn_dataset_class_combo")
        self.class_combo.currentIndexChanged.connect(self._on_class_changed)
        nav_row.addWidget(self.class_combo, stretch=1)
        self.sprite_prev = QPushButton("◀ спрайт")
        self.sprite_prev.clicked.connect(lambda: self._step_sprite(-1))
        nav_row.addWidget(self.sprite_prev)
        self.sprite_next = QPushButton("спрайт ▶")
        self.sprite_next.clicked.connect(lambda: self._step_sprite(1))
        nav_row.addWidget(self.sprite_next)
        self.bg_prev = QPushButton("◀ фон")
        self.bg_prev.clicked.connect(lambda: self._step_bg(-1))
        nav_row.addWidget(self.bg_prev)
        self.bg_next = QPushButton("фон ▶")
        self.bg_next.clicked.connect(lambda: self._step_bg(1))
        nav_row.addWidget(self.bg_next)
        layout.addLayout(nav_row)

        panels_row = QHBoxLayout()
        self.bg_panel = _ImagePanel("Фон", "nn_display_bg")
        self.class_panel = _ImagePanel("Класс", "nn_display_class")
        self.overlay_panel = _ImagePanel("Наложение", "nn_display_overlay")
        for panel in (self.bg_panel, self.class_panel, self.overlay_panel):
            panels_row.addWidget(panel)
        panels_row.addStretch()
        layout.addLayout(panels_row)

        self.data_info = QLabel("")
        self.data_info.setObjectName("nn_dataset_data_info")
        layout.addWidget(self.data_info)
        layout.addStretch()
        return tab

    @staticmethod
    def _spin(value: int, maximum: int = 100_000) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, maximum)
        spin.setValue(value)
        return spin

    # ------------------------------------------------------------------ #
    # Пресеты
    # ------------------------------------------------------------------ #

    def _reload_presets(self) -> None:
        from Services.dataset_gen import PRESETS_DIR

        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for path in sorted(PRESETS_DIR.glob("*.yaml")):
            self.preset_combo.addItem(path.name, str(path))
        self.preset_combo.blockSignals(False)

    def _select_preset(self, path: str) -> None:
        idx = self.preset_combo.findData(path)
        if idx < 0:
            self.preset_combo.addItem(Path(path).name, path)
            idx = self.preset_combo.count() - 1
        self.preset_combo.setCurrentIndex(idx)

    def _current_preset(self) -> Path | None:
        data = self.preset_combo.currentData()
        return Path(data) if data else None

    def _load_preset_to_form(self) -> None:
        """Пресет → поля формы → пересканировать данные и панели."""
        preset = self._current_preset()
        if preset is None or not preset.exists():
            return
        try:
            fields = load_preset_fields(preset)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"Не удалось прочитать пресет: {exc}")
            return
        self.classes_edit.setText(str(fields["classes_dir"] or ""))
        backgrounds = fields["backgrounds_dir"]
        self.backgrounds_edit.setText(str(backgrounds or ""))
        self.procedural_check.setChecked(backgrounds is None)
        self.size_h_spin.setValue(fields["size_h"])
        self.size_w_spin.setValue(fields["size_w"])
        self._rescan_data()

    def _on_save_preset(self) -> None:
        preset = self._current_preset()
        if preset is None:
            self.status_label.setText("Не выбран пресет для сохранения.")
            return
        self._save_to(preset)

    def _on_save_preset_as(self) -> None:
        from Services.dataset_gen import PRESETS_DIR

        path, _ = QFileDialog.getSaveFileName(self, "Сохранить пресет как", str(PRESETS_DIR), "YAML (*.yaml)")
        if not path:
            return
        source = self._current_preset()
        target = Path(path)
        if source is not None and source.exists() and source != target:
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")  # база с комментариями
        self._save_to(target)
        self._select_preset(str(target))

    def _save_to(self, preset: Path) -> None:
        classes_dir = Path(self.classes_edit.text().strip())
        backgrounds = None if self.procedural_check.isChecked() else self.backgrounds_edit.text().strip()
        try:
            save_preset_fields(
                preset,
                classes_dir=classes_dir,
                backgrounds_dir=Path(backgrounds) if backgrounds else None,
                size_hw=(self.size_h_spin.value(), self.size_w_spin.value()),
            )
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"Ошибка сохранения пресета: {exc}")
            return
        self.status_label.setText(f"Пресет сохранён: {preset}")

    # ------------------------------------------------------------------ #
    # Данные: сканирование и панели
    # ------------------------------------------------------------------ #

    def _on_procedural_toggled(self, checked: bool) -> None:
        self.backgrounds_edit.setEnabled(not checked)
        self._rescan_data()

    def _rescan_data(self) -> None:
        classes_dir = Path(self.classes_edit.text().strip()) if self.classes_edit.text().strip() else None
        self._classes = scan_classes(classes_dir) if classes_dir else {}
        bg_text = self.backgrounds_edit.text().strip()
        bg_dir = None if self.procedural_check.isChecked() or not bg_text else Path(bg_text)
        self._bg_files = scan_backgrounds(bg_dir)
        self._bg_idx = 0
        self._sprite_idx = 0

        self.class_combo.blockSignals(True)
        self.class_combo.clear()
        self.class_combo.addItems(list(self._classes))
        self.class_combo.blockSignals(False)

        n_sprites = sum(len(v) for v in self._classes.values())
        bg_note = f"{len(self._bg_files)} файлов" if self._bg_files else "процедурные (движок)"
        self.data_info.setText(f"Классов: {len(self._classes)} (спрайтов: {n_sprites}) · Фоны: {bg_note}")
        self._update_panels()

    def _on_class_changed(self, _index: int) -> None:
        self._sprite_idx = 0
        self._update_panels()

    def _step_sprite(self, delta: int) -> None:
        sprites = self._current_sprites()
        if sprites:
            self._sprite_idx = (self._sprite_idx + delta) % len(sprites)
            self._update_panels()

    def _step_bg(self, delta: int) -> None:
        if self._bg_files:
            self._bg_idx = (self._bg_idx + delta) % len(self._bg_files)
            self._update_panels()

    def _current_sprites(self) -> list[Path]:
        return self._classes.get(self.class_combo.currentText(), [])

    def _update_panels(self) -> None:
        """Обновить три панели: фон / класс / наложение."""
        bg = _imread_any(self._bg_files[self._bg_idx]) if self._bg_files else None
        sprites = self._current_sprites()
        sprite = _imread_any(sprites[self._sprite_idx]) if sprites else None

        if bg is not None:
            self.bg_panel.set_array(bg)
        else:
            self.bg_panel.set_text("процедурные фоны\n(движок, см. «Превью генерации»)")
        if sprite is not None:
            self.class_panel.set_array(sprite)
        else:
            self.class_panel.set_text("нет спрайтов")
        self.overlay_panel.set_array(compose_overlay(bg, sprite) if (bg is not None or sprite is not None) else None)

        sprite_pos = f"{self._sprite_idx + 1}/{len(sprites)}" if sprites else "—"
        bg_pos = f"{self._bg_idx + 1}/{len(self._bg_files)}" if self._bg_files else "—"
        self.sprite_prev.setToolTip(f"Спрайт {sprite_pos}")
        self.sprite_next.setToolTip(f"Спрайт {sprite_pos}")
        self.bg_prev.setToolTip(f"Фон {bg_pos}")
        self.bg_next.setToolTip(f"Фон {bg_pos}")

    # ------------------------------------------------------------------ #
    # Генерация (QThread-воркер)
    # ------------------------------------------------------------------ #

    def _splits(self) -> dict[str, int]:
        splits = {
            "train": self.train_spin.value(),
            "val": self.val_spin.value(),
            "test": self.test_spin.value(),
        }
        return {name: count for name, count in splits.items() if count > 0}

    def _on_browse_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Пресет генератора", str(PROJECT_ROOT), "YAML (*.yaml *.yml)")
        if path:
            self._select_preset(path)

    def _on_browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выходная папка", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def _browse_dir_into(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выбор папки", edit.text() or str(PROJECT_ROOT))
        if path:
            edit.setText(path)
            self._rescan_data()

    def _start_worker(self, mode: str) -> None:
        preset = self._current_preset()
        if preset is None:
            self.status_label.setText("Не выбран пресет.")
            return
        splits = self._splits()
        if mode == "generate" and not splits:
            self.status_label.setText("Все объёмы сплитов нулевые — нечего генерировать.")
            return

        self._set_busy(True, mode)
        self._worker = _GenWorker(str(preset), mode, self.out_edit.text(), splits)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(lambda result: self._on_finished(mode, result))
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_finished(self, mode: str, result: str) -> None:
        self._set_busy(False)
        if mode == "preview":
            pixmap = QPixmap(result)
            if not pixmap.isNull():
                self.preview_label.setPixmap(
                    pixmap.scaled(
                        self.preview_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self.status_label.setText("Превью генерации обновлено (16 кадров).")
        else:
            self.status_label.setText(f"Датасет сгенерирован: {result}")

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status_label.setText(f"Ошибка: {message}")

    def _set_busy(self, busy: bool, mode: str = "") -> None:
        self.preview_btn.setEnabled(not busy)
        self.generate_btn.setEnabled(not busy)
        self.progress.setVisible(busy and mode == "generate")
        if busy:
            self.progress.setValue(0)
            self.status_label.setText("Инициализация движка…" if mode == "preview" else "Генерация…")

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None


class _DatasetGenSection:
    """SectionProtocol: «Генерация датасета»."""

    def __init__(self) -> None:
        self._widget: QWidget | None = None

    @property
    def key(self) -> str:
        return "__nn_dataset_gen__"

    @property
    def title(self) -> str:
        return "Генерация датасета"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = DatasetGenWidget()
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...


def build_dataset_gen_section(_services: Any, _runtime: Any, *, parent_key: str) -> SectionSpec:
    """SectionSpec секции «Генерация датасета» (lazy)."""
    section = _DatasetGenSection()
    return SectionSpec(
        key=section.key,
        title=section.title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
        lazy=True,
    )
