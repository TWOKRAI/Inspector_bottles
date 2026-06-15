# -*- coding: utf-8 -*-
"""Секция «Вырез эталона (диск)» — интерактивная подготовка RGBA-эталонов.

Шаг 0 ML-конвейера (перед «Генерация датасета»): открыть реальный снимок белого
диска с глифом, авто-вырезать диск кругом (вне круга прозрачно), покрутить угол
глазами до 0° и сохранить эталон в каталог классов dataset_gen
(`<out>/<класс>/NNN.png` + meta.yaml). Дальше — штатная аугментация: соседняя
секция «Генерация датасета» крутит/клеит этот эталон на фон.

Зачем интерактивно (а не tools/cut_real_disks.py): тот батч-инструмент берёт угол
из имени файла, а у реальных снимков угол произвольный и заранее неизвестен —
нужно поймать 0° слайдером.

Обработка целиком локальная (детекция круга, вырез, поворот, запись) — backend/IPC
не нужен. Ядро выреза переиспользуется из Services/dataset_gen/core/realcut.py;
чистые хелперы вынесены наружу Qt и покрываются тестами без виджета.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.main import PROJECT_ROOT

_IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"
_IMG_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
_DISPLAY_SIZE = 480  # сторона дисплея-превью, px
_DEFAULT_OUT = PROJECT_ROOT / "data" / "dataset_gen" / "manual_sprites"
_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
_TOP_SLOT_ID = "disk_cutter"  # id слота в верхней панели дисплеев (где камера)


# ---------------------------------------------------------------------------
# Чистые хелперы (вне Qt — покрываются тестами без виджета)
# ---------------------------------------------------------------------------


def load_sprite(path: Path) -> np.ndarray | None:
    """Снимок → RGBA-эталон (диск вырезан кругом, вне круга прозрачно).

    np.fromfile+imdecode (unicode-пути Windows) → detect_disk → BGR→RGB →
    cut_disk_rgba. Возвращает RGBA 2r×2r (порядок каналов RGB, как у PIL) или
    None, если файл не прочитался.
    """
    import cv2

    from Services.dataset_gen.core.realcut import cut_disk_rgba, detect_disk

    data = np.fromfile(str(path), dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    circle = detect_disk(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return cut_disk_rgba(rgb, circle)


def rotate_sprite(rgba: np.ndarray, angle: float) -> np.ndarray:
    """Повернуть RGBA-эталон на произвольный угол (CCW, размер сохраняется).

    Углы за пределами диска остаются прозрачными (borderValue alpha=0).
    """
    import cv2

    if abs(angle) < 1e-6:
        return rgba
    h, w = rgba.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(angle), 1.0)
    return cv2.warpAffine(
        rgba,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _checkerboard(side: int, cell: int = 16) -> np.ndarray:
    """Серая шахматка side×side×3 (RGB) — подложка, чтобы видеть прозрачность."""
    board = np.full((side, side, 3), 200, dtype=np.uint8)
    ys, xs = np.indices((side, side))
    dark = ((xs // cell) + (ys // cell)) % 2 == 1
    board[dark] = 160
    return board


def render_preview(rgba: np.ndarray, angle: float, *, grid: bool, box: int = _DISPLAY_SIZE) -> np.ndarray:
    """RGBA-эталон под углом → RGB-превью на шахматке (+ опц. сетка/вертикаль).

    Только для экрана: сетка и направляющая в файл НЕ попадают (см. bake_sprite).
    """
    import cv2

    rotated = rotate_sprite(rgba, angle)
    rotated = cv2.resize(rotated, (box, box), interpolation=cv2.INTER_AREA)

    base = _checkerboard(box)
    alpha = rotated[:, :, 3:4].astype(np.float32) / 255.0
    base = (rotated[:, :, :3].astype(np.float32) * alpha + base.astype(np.float32) * (1 - alpha)).astype(np.uint8)

    if grid:
        step = box // 8
        for i in range(step, box, step):
            base[i, :, :] = (90, 90, 90)
            base[:, i, :] = (90, 90, 90)
        # центральная вертикаль/горизонталь поярче — ориентир для 0°
        cx = box // 2
        base[:, cx, :] = (255, 80, 80)
        base[cx, :, :] = (255, 80, 80)
    return base


def bake_sprite(rgba: np.ndarray, angle: float, size: int) -> np.ndarray:
    """Финальный эталон для записи: поворот на angle → ресайз до size (RGBA).

    БЕЗ шахматки/сетки — только повёрнутый вырезанный диск.
    """
    import cv2

    rotated = rotate_sprite(rgba, angle)
    return cv2.resize(rotated, (size, size), interpolation=cv2.INTER_AREA)


def next_index(class_dir: Path) -> int:
    """Следующий свободный индекс эталона по числу *.png в папке класса."""
    if not class_dir.is_dir():
        return 0
    return sum(1 for p in class_dir.iterdir() if p.suffix.lower() == ".png")


def list_images(folder: Path) -> list[Path]:
    """Отсортированный список изображений в папке — плейлист авто-перехода."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _IMG_SUFFIXES)


def save_sprite(rgba: np.ndarray, out_dir: Path, class_name: str, size: int, angle: float = 0.0) -> Path:
    """Сохранить эталон в каталог классов: <out>/<class>/NNN.png + meta.yaml.

    Эталон пекётся на текущий угол (bake_sprite), запись через PIL (unicode-safe
    имена классов). meta.yaml пишется один раз, если его ещё нет. Возвращает путь
    сохранённого PNG.
    """
    from PIL import Image

    from Services.dataset_gen.core.metadata import ClassMeta, write_meta

    class_dir = out_dir / class_name
    class_dir.mkdir(parents=True, exist_ok=True)
    idx = next_index(class_dir)
    target = class_dir / f"{idx:03d}.png"

    Image.fromarray(bake_sprite(rgba, angle, size), mode="RGBA").save(target)

    if not any((class_dir / name).exists() for name in ("meta.yaml", "meta.yml", "meta.json")):
        write_meta(class_dir, ClassMeta(display_name=class_name, tags=["disk", "real"]))
    return target


# ---------------------------------------------------------------------------
# Виджет секции
# ---------------------------------------------------------------------------


class DiskCutterWidget(QWidget):
    """Открыть фото → вырез диска → слайдер угла → «Готово» (сохранение эталона)."""

    def __init__(self, parent: QWidget | None = None, *, image_panel: Any = None) -> None:
        super().__init__(parent)
        self._sprite: np.ndarray | None = None  # текущий вырезанный RGBA-эталон
        self._playlist: list[Path] = []  # все изображения папки (авто-переход)
        self._idx: int = -1  # индекс текущего в плейлисте
        self._image_panel = image_panel  # верхняя панель дисплеев (где камера) или None
        self._top_attached = False  # активен ли наш слот-редактор в верхней панели
        self._cmp_slots: list[str] = []  # замороженные слоты-сравнения в верхней панели
        self._cmp_count = 0  # счётчик id сравнений (монотонный)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        open_row = QHBoxLayout()
        self.open_btn = QPushButton("Открыть фото…")
        self.open_btn.setObjectName("disk_cutter_open")
        self.open_btn.clicked.connect(self._on_open)
        open_row.addWidget(self.open_btn)
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setObjectName("disk_cutter_prev")
        self.prev_btn.setToolTip("Предыдущее изображение (без сохранения)")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        open_row.addWidget(self.prev_btn)
        self.next_btn = QPushButton("Пропустить ▶")
        self.next_btn.setObjectName("disk_cutter_next")
        self.next_btn.setToolTip("Следующее изображение (без сохранения)")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(lambda: self._step(1))
        open_row.addWidget(self.next_btn)
        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet("color: #777;")
        open_row.addWidget(self.file_label, stretch=1)
        root.addLayout(open_row)

        # Превью показывается в ВЕРХНЕЙ панели дисплеев (слот «Вырез эталона»),
        # а не здесь — так можно открывать несколько видов рядом и сравнивать.
        self.hint = QLabel("Превью — в верхней панели дисплеев, слот «Вырез эталона».")
        self.hint.setObjectName("disk_cutter_hint")
        self.hint.setStyleSheet("color: #888;")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # Сравнение: заморозить текущий вид отдельным дисплеем в верхней панели
        cmp_row = QHBoxLayout()
        self.cmp_add_btn = QPushButton("В сравнение →")
        self.cmp_add_btn.setObjectName("disk_cutter_cmp_add")
        self.cmp_add_btn.setToolTip("Заморозить текущий вид отдельным дисплеем сверху — чтобы сравнивать")
        self.cmp_add_btn.clicked.connect(self._add_comparison)
        cmp_row.addWidget(self.cmp_add_btn)
        self.cmp_clear_btn = QPushButton("Очистить сравнения")
        self.cmp_clear_btn.setObjectName("disk_cutter_cmp_clear")
        self.cmp_clear_btn.clicked.connect(self._clear_comparisons)
        cmp_row.addWidget(self.cmp_clear_btn)
        cmp_row.addStretch()
        root.addLayout(cmp_row)
        if self._image_panel is None:  # без верхней панели сравнивать негде
            self.cmp_add_btn.setEnabled(False)
            self.cmp_clear_btn.setEnabled(False)
            self.cmp_add_btn.setToolTip("Недоступно: верхняя панель дисплеев не передана")

        # Поворот
        rot_box = QGroupBox("Поворот (поймайте 0°)")
        rot_layout = QVBoxLayout(rot_box)
        slider_row = QHBoxLayout()
        self.angle_slider = QSlider(Qt.Orientation.Horizontal)
        self.angle_slider.setObjectName("disk_cutter_angle")
        self.angle_slider.setRange(-180, 180)
        self.angle_slider.setValue(0)
        self.angle_slider.valueChanged.connect(self._on_angle_changed)
        slider_row.addWidget(self.angle_slider, stretch=1)
        self.angle_label = QLabel("0°")
        self.angle_label.setMinimumWidth(48)
        self.angle_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider_row.addWidget(self.angle_label)
        rot_layout.addLayout(slider_row)

        btn_row = QHBoxLayout()
        for label, delta in (("−90", -90), ("−1", -1), ("+1", 1), ("+90", 90)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, d=delta: self._nudge(d))
            btn_row.addWidget(btn)
        reset_btn = QPushButton("Сброс 0°")
        reset_btn.clicked.connect(lambda: self.angle_slider.setValue(0))
        btn_row.addWidget(reset_btn)
        self.grid_check = QCheckBox("Сетка")
        self.grid_check.setObjectName("disk_cutter_grid")
        self.grid_check.toggled.connect(lambda _c: self._refresh_preview())
        btn_row.addWidget(self.grid_check)
        btn_row.addStretch()
        rot_layout.addLayout(btn_row)
        root.addWidget(rot_box)

        # Сохранение
        save_box = QGroupBox("Сохранение эталона")
        form = QFormLayout(save_box)
        self.class_edit = QLineEdit()
        self.class_edit.setObjectName("disk_cutter_class")
        self.class_edit.setPlaceholderText("например: б")
        form.addRow("Класс:", self.class_edit)

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit(str(_DEFAULT_OUT))
        self.out_edit.setObjectName("disk_cutter_out")
        out_row.addWidget(self.out_edit, stretch=1)
        out_browse = QPushButton("Обзор…")
        out_browse.clicked.connect(self._on_browse_out)
        out_row.addWidget(out_browse)
        form.addRow("Папка вывода:", out_row)

        self.size_spin = QSpinBox()
        self.size_spin.setObjectName("disk_cutter_size")
        self.size_spin.setRange(32, 4096)
        self.size_spin.setValue(256)
        form.addRow("Размер, px:", self.size_spin)

        self.done_btn = QPushButton("Готово (сохранить)")
        self.done_btn.setObjectName("disk_cutter_done")
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self._on_done)
        form.addRow("", self.done_btn)
        root.addWidget(save_box)

        self.status_label = QLabel("Готово к работе.")
        self.status_label.setObjectName("disk_cutter_status")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch()

    # ------------------------------------------------------------------ #
    # Логика
    # ------------------------------------------------------------------ #

    def _angle(self) -> float:
        return float(self.angle_slider.value())

    # ---- верхняя панель дисплеев (где камера) ---- #

    def attach_top_display(self) -> None:
        """Завести наш слот в верхней панели дисплеев и показать текущее превью."""
        if self._image_panel is None or self._top_attached:
            return
        try:
            self._image_panel.add_slot(_TOP_SLOT_ID, "Вырез эталона")
            self._top_attached = True
            self._refresh_preview()
        except Exception:  # noqa: BLE001 — панель опциональна, тулза работает и без неё
            self._top_attached = False

    def detach_top_display(self) -> None:
        """Убрать слот-редактор и все сравнения из верхней панели (уход со вкладки)."""
        self._clear_comparisons()
        if self._image_panel is None or not self._top_attached:
            return
        try:
            self._image_panel.remove_slot(_TOP_SLOT_ID)
        except Exception:  # noqa: BLE001
            pass
        self._top_attached = False

    def _add_comparison(self) -> None:
        """Заморозить текущий вид как отдельный слот верхней панели (для сравнения)."""
        if self._image_panel is None or self._sprite is None:
            self.status_label.setText("Нечего добавить: откройте фото.")
            return
        self._cmp_count += 1
        cmp_id = f"{_TOP_SLOT_ID}_cmp_{self._cmp_count}"
        name = self._playlist[self._idx].name if 0 <= self._idx < len(self._playlist) else "—"
        label = f"{self.class_edit.text().strip() or '?'} · {name} · {int(self._angle())}°"
        try:
            self._image_panel.add_slot(cmp_id, label)
            frozen = render_preview(self._sprite, self._angle(), grid=False)  # без сетки — чистый вид
            self._image_panel.display_frame(cmp_id, np.ascontiguousarray(frozen[..., ::-1]))
            self._cmp_slots.append(cmp_id)
            self.status_label.setText(f"В сравнение: {label} (всего {len(self._cmp_slots)})")
        except Exception:  # noqa: BLE001 — панель опциональна
            pass

    def _clear_comparisons(self) -> None:
        """Убрать все слоты-сравнения из верхней панели."""
        if self._image_panel is None or not self._cmp_slots:
            return
        for cmp_id in self._cmp_slots:
            try:
                self._image_panel.remove_slot(cmp_id)
            except Exception:  # noqa: BLE001
                pass
        self._cmp_slots.clear()

    # ---- открытие / навигация ---- #

    def _on_open(self) -> None:
        start_dir = str(_SNAPSHOTS_DIR) if _SNAPSHOTS_DIR.is_dir() else str(PROJECT_ROOT)
        path, _ = QFileDialog.getOpenFileName(self, "Открыть фото диска", start_dir, _IMAGE_FILTER)
        if not path:
            return
        chosen = Path(path)
        # Плейлист = все изображения папки (для авто-перехода после «Готово»).
        self._playlist = list_images(chosen.parent) or [chosen]
        self._idx = self._playlist.index(chosen) if chosen in self._playlist else 0
        self._load_current()

    def _step(self, delta: int) -> None:
        """Ручная навигация по плейлисту (без сохранения)."""
        if not self._playlist:
            return
        self._idx = max(0, min(len(self._playlist) - 1, self._idx + delta))
        self._load_current()

    def _load_current(self, status_prefix: str = "") -> None:
        """Загрузить текущий элемент плейлиста: вырез круга → превью."""
        self._update_nav_buttons()
        if not (0 <= self._idx < len(self._playlist)):
            return
        path = self._playlist[self._idx]
        pos = f"[{self._idx + 1}/{len(self._playlist)}]"
        try:
            sprite = load_sprite(path)
        except Exception as exc:  # noqa: BLE001 — текст ошибки в статус-лейбл
            self._sprite = None
            self.done_btn.setEnabled(False)
            self.file_label.setText(f"{path.name}  {pos}")
            self.status_label.setText(f"{status_prefix}Ошибка чтения {path.name}: {type(exc).__name__}: {exc}")
            return
        if sprite is None:
            self._sprite = None
            self.done_btn.setEnabled(False)
            self.file_label.setText(f"{path.name}  {pos}")
            self.status_label.setText(f"{status_prefix}Не удалось прочитать {path.name} — «Пропустить ▶».")
            return
        self._sprite = sprite
        self.file_label.setText(f"{path.name}  {pos}")
        self.angle_slider.setValue(0)
        self.done_btn.setEnabled(True)
        self._refresh_preview()
        # detect_disk при провале логирует warning и ставит круг по центру —
        # подскажем пользователю, что результат стоит проверить.
        h, w = sprite.shape[:2]
        self.status_label.setText(
            f"{status_prefix}Открыто {pos} {path.name}: диск вырезан ({w}×{h}). Поймайте 0° и нажмите «Готово»."
        )

    def _update_nav_buttons(self) -> None:
        n = len(self._playlist)
        self.prev_btn.setEnabled(self._idx > 0)
        self.next_btn.setEnabled(0 <= self._idx < n - 1)

    def _on_angle_changed(self, value: int) -> None:
        self.angle_label.setText(f"{value}°")
        self._refresh_preview()

    def _nudge(self, delta: int) -> None:
        new = max(-180, min(180, self.angle_slider.value() + delta))
        self.angle_slider.setValue(new)

    def _refresh_preview(self) -> None:
        """Отрисовать превью в слот «Вырез эталона» верхней панели дисплеев."""
        if self._sprite is None or not self._top_attached or self._image_panel is None:
            return
        preview = render_preview(self._sprite, self._angle(), grid=self.grid_check.isChecked())
        # display_frame ждёт BGR (presenter переворачивает в RGB) → отдаём в обратном порядке.
        try:
            self._image_panel.display_frame(_TOP_SLOT_ID, np.ascontiguousarray(preview[..., ::-1]))
        except Exception:  # noqa: BLE001 — сбой панели не должен ронять тулзу
            pass

    def _on_browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка вывода", self.out_edit.text() or str(PROJECT_ROOT))
        if path:
            self.out_edit.setText(path)

    def _on_done(self) -> None:
        if self._sprite is None:
            self.status_label.setText("Сначала откройте фото.")
            return
        class_name = self.class_edit.text().strip()
        if not class_name:
            self.status_label.setText("Укажите имя класса.")
            return
        out_dir = Path(self.out_edit.text().strip() or str(_DEFAULT_OUT))
        try:
            target = save_sprite(self._sprite, out_dir, class_name, self.size_spin.value(), self._angle())
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"Ошибка сохранения: {type(exc).__name__}: {exc}")
            return
        saved = f"Сохранено: {target.name} → {target.parent}"
        # Авто-переход к следующему фото папки.
        if self._idx + 1 < len(self._playlist):
            self._idx += 1
            self._load_current(status_prefix=saved + " · ")
        else:
            self._sprite = None
            self.done_btn.setEnabled(False)
            self._update_nav_buttons()
            self.status_label.setText(f"{saved} · все изображения папки обработаны ✓")


# ---------------------------------------------------------------------------
# Секция (SectionProtocol) + фабрика
# ---------------------------------------------------------------------------


class _DiskCutterSection:
    """SectionProtocol: «Вырез эталона (диск)».

    Превью зеркалится в верхнюю панель дисплеев (где камера) через
    runtime.image_panel: слот заводится при показе вкладки и убирается при уходе.
    """

    def __init__(self, runtime: Any = None) -> None:
        self._runtime = runtime
        self._widget: DiskCutterWidget | None = None

    @property
    def key(self) -> str:
        return "__nn_disk_cutter__"

    @property
    def title(self) -> str:
        return "Вырез эталона (диск)"

    def widget(self) -> QWidget:
        if self._widget is None:
            image_panel = getattr(self._runtime, "image_panel", None)
            self._widget = DiskCutterWidget(image_panel=image_panel)
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        if self._widget is not None:
            self._widget.attach_top_display()

    def on_deactivated(self) -> None:
        if self._widget is not None:
            self._widget.detach_top_display()


def build_disk_cutter_section(_services: Any, runtime: Any, *, parent_key: str) -> SectionSpec:
    """SectionSpec секции «Вырез эталона (диск)» (lazy)."""
    section = _DiskCutterSection(runtime)
    return SectionSpec(
        key=section.key,
        title=section.title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
        lazy=True,
    )
