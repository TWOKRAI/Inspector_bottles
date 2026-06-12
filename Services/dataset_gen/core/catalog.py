"""Каталог классов и фонов: загрузка RGBA-эталонов и выдача фоновых кропов.

Класс = ЛИСТОВАЯ папка со спрайтами. Каталог обходится рекурсивно, поэтому
классы можно группировать в подклассы (`letters/vowels/А`); путь от корня до
листа = иерархия класса. Внутри листовой папки — один или несколько эталонов
на прозрачном фоне. Индекс класса стабилен между запусками (сортировка по пути).

В каждой папке (любого уровня) может лежать `meta.yaml` — разметка, которая
наследуется вниз (см. core/metadata.py).

Внутреннее цветовое соглашение сервиса — RGB/RGBA; конвертация из BGR(A)
происходит здесь, на загрузке.

Windows-грабли: имена классов бывают кириллицей («А/», «Б/»), а cv2.imread
не умеет non-ASCII пути на Windows — поэтому весь I/O через
np.fromfile + cv2.imdecode (и imencode + tofile на записи).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from Services.dataset_gen.core.backgrounds import procedural_background
from Services.dataset_gen.core.config import CatalogConfig
from Services.dataset_gen.core.metadata import ClassMeta, load_meta

SPRITE_SUFFIXES = {".png", ".webp", ".tif", ".tiff"}
BACKGROUND_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def imread_unicode(path: str | Path, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray:
    """Чтение изображения с поддержкой non-ASCII путей (Windows-safe).

    Pre:
      - файл существует и является изображением
    Post:
      - возвращён ndarray; исключение ValueError при нечитаемом файле
    """
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, flags)
    if img is None:
        raise ValueError(f"Не удалось прочитать изображение: {path}")
    return img


def imwrite_unicode(path: str | Path, image_bgr: np.ndarray) -> None:
    """Запись изображения с поддержкой non-ASCII путей (формат — по суффиксу)."""
    suffix = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(suffix, image_bgr)
    if not ok:
        raise ValueError(f"Не удалось закодировать изображение в {suffix}: {path}")
    buf.tofile(str(path))


@dataclass(frozen=True)
class ClassEntry:
    """Описание класса.

    name — имя листовой папки (для совместимости и overrides по имени);
    path — иерархия от корня каталога классов (`["letters", "А"]`);
    meta — слитая разметка (родительские meta.* + собственный), см. metadata.py.
    """

    name: str
    index: int
    sprite_paths: tuple[Path, ...]
    path: tuple[str, ...] = ()
    meta: ClassMeta = field(default_factory=ClassMeta)

    @property
    def qualified_name(self) -> str:
        """Полное имя через иерархию: `letters/vowels/А` (POSIX-разделитель)."""
        return "/".join(self.path) if self.path else self.name

    @property
    def display_name(self) -> str:
        """Человекочитаемое имя из meta или имя папки."""
        return self.meta.display_name or self.name


class SpriteCatalog:
    """Каталог: эталоны классов (в памяти) + фоны (ленивый кэш по пути).

    Эталоны грузятся жадно в load() — их немного и они маленькие.
    Фоновые фото могут быть большими и многочисленными — грузятся по запросу
    и кэшируются по пути (кэш не ограничен: при огромных наборах фонов
    следите за памятью).
    """

    def __init__(self, config: CatalogConfig) -> None:
        self._config = config
        self._classes: list[ClassEntry] = []
        self._sprites: dict[int, list[np.ndarray]] = {}
        self._background_paths: list[Path] = []
        self._background_cache: dict[Path, np.ndarray] = {}
        self._loaded = False

    # -- загрузка -----------------------------------------------------------

    def load(self) -> None:
        """Просканировать каталоги и загрузить эталоны.

        Pre:
          - config.classes_dir существует и содержит ≥1 подкаталог с эталонами
        Post:
          - num_classes ≥ 1; каждый эталон — RGBA (HxWx4, uint8)
        """
        root = self._config.classes_dir
        if not root.is_dir():
            raise FileNotFoundError(f"Каталог классов не найден: {root}")

        # Рекурсивный обход: класс = листовая папка со спрайтами; промежуточные
        # папки — группы (подклассы). meta.* наследуется от корня к листу.
        leaves: list[tuple[tuple[str, ...], Path, tuple[Path, ...], ClassMeta]] = []
        self._collect_classes(root, (), load_meta(root), leaves)
        if not leaves:
            raise ValueError(f"В каталоге классов нет листовых папок со спрайтами: {root}")

        leaves.sort(key=lambda item: item[0])  # стабильный порядок по иерархии

        names_seen: dict[str, tuple[str, ...]] = {}
        self._classes = []
        self._sprites = {}
        for index, (path, _dir, paths, meta) in enumerate(leaves):
            if not path:
                raise ValueError(
                    f"Спрайты лежат прямо в корне {root} — нужны подпапки-классы "
                    f"(например {root.name}/<класс>/sprite.png)"
                )
            name = path[-1]
            if name in names_seen:
                raise ValueError(
                    f"Конфликт имён классов «{name}»: {'/'.join(names_seen[name])} и "
                    f"{'/'.join(path)}. Имена листовых папок должны быть уникальны "
                    f"(переименуйте или задайте display_name в meta.yaml)."
                )
            names_seen[name] = path
            self._classes.append(ClassEntry(name=name, index=index, sprite_paths=paths, path=path, meta=meta))
            self._sprites[index] = [self._load_sprite(p) for p in paths]

        bg_dir = self._config.backgrounds_dir
        if bg_dir is not None:
            if not bg_dir.is_dir():
                raise FileNotFoundError(f"Каталог фонов не найден: {bg_dir}")
            # Рекурсивно: фоны допустимо раскладывать по подпапкам-категориям
            # (например belt/, tray/, table/) — берём все изображения из дерева.
            self._background_paths = sorted(
                p for p in bg_dir.rglob("*") if p.is_file() and p.suffix.lower() in BACKGROUND_SUFFIXES
            )
            if not self._background_paths:
                raise ValueError(f"В каталоге фонов нет изображений: {bg_dir}")
        self._loaded = True

    def _collect_classes(
        self,
        directory: Path,
        rel_path: tuple[str, ...],
        inherited_meta: ClassMeta,
        out: list[tuple[tuple[str, ...], Path, tuple[Path, ...], ClassMeta]],
    ) -> None:
        """Рекурсивно собрать листовые классы со спрайтами и накопить метаданные.

        Листовая папка (есть спрайты) → класс; иначе спускаемся в подпапки.
        Если в папке есть и спрайты, и подпапки — спрайты выигрывают (это класс),
        подпапки не считаются подклассами (избегаем неоднозначности).
        Служебные папки (имя с «.» или «_») пропускаются.
        """
        meta = inherited_meta if rel_path == () else inherited_meta.merged_with_child(load_meta(directory))
        sprite_paths = tuple(sorted(p for p in directory.iterdir() if p.suffix.lower() in SPRITE_SUFFIXES))
        if sprite_paths:
            out.append((rel_path, directory, sprite_paths, meta))
            return
        subdirs = sorted(
            (d for d in directory.iterdir() if d.is_dir() and d.name[0] not in "._"),
            key=lambda d: d.name,
        )
        for sub in subdirs:
            self._collect_classes(sub, rel_path + (sub.name,), meta, out)

    @staticmethod
    def _load_sprite(path: Path) -> np.ndarray:
        """Загрузить эталон, гарантировать RGBA."""
        img = imread_unicode(path, cv2.IMREAD_UNCHANGED)
        if img.ndim != 3 or img.shape[2] != 4:
            raise ValueError(
                f"Эталон {path}: нужен альфа-канал (RGBA, объект на прозрачном фоне), получено shape={img.shape}"
            )
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)

    # -- доступ --------------------------------------------------------------

    @property
    def classes(self) -> list[ClassEntry]:
        self._ensure_loaded()
        return list(self._classes)

    @property
    def class_names(self) -> list[str]:
        self._ensure_loaded()
        return [c.name for c in self._classes]

    @property
    def num_classes(self) -> int:
        self._ensure_loaded()
        return len(self._classes)

    def entry(self, class_index: int) -> ClassEntry:
        """Запись класса по индексу (без копирования списка — для hot path)."""
        self._ensure_loaded()
        return self._classes[class_index]

    def sprites(self, class_index: int) -> list[np.ndarray]:
        """Все эталоны класса (RGBA uint8)."""
        self._ensure_loaded()
        return self._sprites[class_index]

    def get_sprite(self, class_index: int, rng: np.random.Generator) -> np.ndarray:
        """Случайный эталон класса."""
        sprites = self.sprites(class_index)
        return sprites[int(rng.integers(len(sprites)))]

    def get_background(self, rng: np.random.Generator, size_hw: tuple[int, int]) -> np.ndarray:
        """Случайный фон, кропнутый/отресайзенный под size_hw (RGB uint8).

        Post:
          - shape == (*size_hw, 3), dtype uint8
        """
        self._ensure_loaded()
        if not self._background_paths:
            return procedural_background(rng, size_hw)
        path = self._background_paths[int(rng.integers(len(self._background_paths)))]
        bg = self._background_cache.get(path)
        if bg is None:
            raw = imread_unicode(path, cv2.IMREAD_COLOR)
            bg = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
            self._background_cache[path] = bg
        return _cover_crop(bg, size_hw, rng)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()


def _cover_crop(image: np.ndarray, size_hw: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    """Масштабировать так, чтобы изображение покрывало целевой размер, и кропнуть случайно."""
    th, tw = size_hw
    h, w = image.shape[:2]
    scale = max(th / h, tw / w)
    if scale != 1.0:
        nh, nw = max(th, int(round(h * scale))), max(tw, int(round(w * scale)))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        image = cv2.resize(image, (nw, nh), interpolation=interp)
        h, w = image.shape[:2]
    y0 = int(rng.integers(h - th + 1))
    x0 = int(rng.integers(w - tw + 1))
    return image[y0 : y0 + th, x0 : x0 + tw].copy()
