"""
Unit-тесты для config_module.tools.watcher — ConfigFileWatcher.

Пропускаются если watchdog не установлен.
"""

import json
import time
import pytest

try:
    from multiprocess_framework.modules.config_module.tools.watcher import ConfigFileWatcher

    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from multiprocess_framework.modules.config_module.core.config import Config

pytestmark = pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog not installed")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_stop(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"a": 1}))

    cfg = Config(initial_data={"a": 1})
    watcher = ConfigFileWatcher(path=config_file, config=cfg)

    assert not watcher.is_running
    watcher.start()
    assert watcher.is_running
    watcher.stop()
    assert not watcher.is_running


def test_double_start_is_safe(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"a": 1}))

    cfg = Config(initial_data={"a": 1})
    watcher = ConfigFileWatcher(path=config_file, config=cfg)

    watcher.start()
    watcher.start()  # не должно бросить исключение
    assert watcher.is_running
    watcher.stop()


def test_stop_without_start():
    cfg = Config()
    watcher = ConfigFileWatcher(path="nonexistent.json", config=cfg)
    watcher.stop()  # не должно бросить исключение


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------


def test_reload_on_file_change(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reload_called = []

    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reload_called.append(True),
        debounce_seconds=0.1,
    )
    watcher.start()

    try:
        # Даём watcher время запуститься
        time.sleep(0.3)

        # Изменяем файл
        config_file.write_text(json.dumps({"value": "updated"}))

        # Ждём обработки
        deadline = time.monotonic() + 5.0
        while cfg.get("value") != "updated" and time.monotonic() < deadline:
            time.sleep(0.2)

        assert cfg.get("value") == "updated"
        assert len(reload_called) >= 1
    finally:
        watcher.stop()


# ---------------------------------------------------------------------------
# Атомарная запись (temp + os.replace) — как пишет сама система
# ---------------------------------------------------------------------------


def _atomic_write(path, payload: dict) -> None:
    """Запись «как в проде»: временный файл рядом + ``os.replace``.

    Именно так пишет ``write_companion`` (и так же сохраняют многие редакторы):
    читатель никогда не видит полуфайла. Для watchdog это НЕ модификация целевого
    пути — для него это created/moved, а modified приходит только на временный
    файл.
    """
    import os

    tmp = path.with_name(path.name + ".tmp_test")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def test_reload_on_atomic_replace(tmp_path):
    """Живой дефект 2026-07-29: правки НЕ подхватывались вообще.

    Обработчик реализовывал только ``on_modified``, а система пишет конфиги
    атомарно. В логе было видно единственное событие — по временному файлу
    (``…json.tmp_test``), которое отбрасывалось по несовпадению имени. То есть
    «hot-reload работает» держалось на тестах, писавших файл НА МЕСТЕ, — а
    собственный способ записи система не слышала.

    Пара: до фикса три атомарные записи подряд давали 0 срабатываний.
    """
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reloads = []
    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reloads.append(c.get("value")),
        debounce_seconds=0.05,
    )
    watcher.start()
    try:
        time.sleep(0.4)
        for expected in ("first", "second", "third"):
            before = len(reloads)
            # Пауза больше дебаунса: без неё запись приходит через ~0.05с после
            # предыдущей перезагрузки и отбрасывается КАК ДУБЛЬ — тест падал бы
            # на работающем механизме (поймано при первом прогоне).
            time.sleep(0.3)
            _atomic_write(config_file, {"value": expected})
            deadline = time.monotonic() + 5.0
            while len(reloads) == before and time.monotonic() < deadline:
                time.sleep(0.05)
            assert len(reloads) > before, f"атомарная запись '{expected}' не разбудила watcher"
        assert cfg.get("value") == "third"
    finally:
        watcher.stop()


def test_recreate_without_rename_also_reloads(tmp_path):
    """Удалить и создать заново — тоже способ записи, и он не через rename.

    Так пишут часть редакторов (truncate/recreate вместо атомарной подмены), и
    события здесь другие: ``deleted`` + ``created``, БЕЗ ``moved``. Обработчик,
    знающий только про переименование, этот путь пропустил бы.
    """
    import os

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reloads = []
    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reloads.append(c.get("value")),
        debounce_seconds=0.05,
    )
    watcher.start()
    try:
        time.sleep(0.4)
        os.remove(config_file)
        time.sleep(0.3)
        config_file.write_text(json.dumps({"value": "recreated"}), encoding="utf-8")
        deadline = time.monotonic() + 5.0
        while cfg.get("value") != "recreated" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert cfg.get("value") == "recreated", "пересоздание файла не разбудило watcher"
    finally:
        watcher.stop()


def test_rapid_edits_collapse_into_one_reload(tmp_path):
    """Дебаунс: серия быстрых правок = ОДНА перезагрузка.

    **Уточнение после слом-инъекции W3.** Первая редакция этого теста утверждала,
    что атомарная подмена даёт три события на целевой файл и без дебаунса
    перечитывала бы конфиг трижды. Это неверно: для целевого пути приходит РОВНО
    одно событие (``moved``), а ``created``/``modified`` относятся к временному
    файлу. Инъекция «дебаунса нет» не убила тест — то есть он сторожил
    несуществующее свойство. Дебаунс защищает от другого: от СЕРИИ правок,
    которую даёт ползунок пульта или редактор, сохраняющий по каждому нажатию.
    """
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reloads = []
    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reloads.append(c.get("value")),
        debounce_seconds=2.0,
    )
    watcher.start()
    try:
        time.sleep(0.4)
        for i in range(5):
            _atomic_write(config_file, {"value": f"v{i}"})
            time.sleep(0.1)
        time.sleep(1.5)
        assert len(reloads) == 1, f"серия из 5 правок дала {len(reloads)} перезагрузок вместо одной"
    finally:
        watcher.stop()


def test_foreign_file_in_the_same_directory_is_ignored(tmp_path):
    """Watcher слушает КАТАЛОГ — сосед не имеет права его будить.

    Обработчиков стало три, и фильтр по имени теперь общий: ошибись он, каждая
    запись любого файла рядом (включая временные) дёргала бы перезагрузку.
    """
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"value": "original"}))

    cfg = Config(initial_data={"value": "original"})
    reloads = []
    watcher = ConfigFileWatcher(
        path=config_file,
        config=cfg,
        on_reload=lambda c: reloads.append(True),
        debounce_seconds=0.05,
    )
    watcher.start()
    try:
        time.sleep(0.4)
        _atomic_write(tmp_path / "neighbour.json", {"value": "not ours"})
        (tmp_path / "plain.txt").write_text("hello", encoding="utf-8")
        time.sleep(1.0)
        assert reloads == [], f"чужой файл разбудил watcher: {len(reloads)}"
    finally:
        watcher.stop()
