"""Фикстуры тестов robot_comm — клиент поверх FakeRobotTransport (без сети)."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


# Тесты видов рисуют в QPixmap и читают пиксели: платформа Qt — «offscreen», не зависит от того,
# кто и как запустил pytest. Переменная читается при создании QApplication, импорты ей не мешают; setdefault — явная
# переменная окружения (например, для отладки на реальном экране) по-прежнему главнее.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _pin_offscreen_font_dir() -> None:
    """На Windows платформа offscreen не видит системных шрифтов («QFontDatabase: Cannot find
    font directory ... Qt no longer ships fonts») и рисует текст рамками-заглушками не на тех
    строках — тесты, ищущие пиксели подписей, читают не то. Кладём в каталог шрифтов Qt ровно
    один шрифт (DejaVuSans из matplotlib — он в зависимостях проекта): набор шрифтов не
    зависит от машины и порядка файлов в каталоге. Явный QT_QPA_FONTDIR главнее."""
    if sys.platform != "win32" or "QT_QPA_FONTDIR" in os.environ:
        return
    import matplotlib

    font_dir = Path(tempfile.mkdtemp(prefix="qt_fonts_"))
    atexit.register(shutil.rmtree, font_dir, ignore_errors=True)
    shutil.copy(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf", font_dir)
    os.environ["QT_QPA_FONTDIR"] = str(font_dir)


_pin_offscreen_font_dir()


class FakeClock:
    """Управляемые часы: каждый вызов sleep продвигает время — без реальных пауз."""

    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def transport(core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(core)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bot(transport: FakeRobotTransport, clock: FakeClock) -> RobotClient:
    """Подключённый клиент поверх фейк-робота, время — детерминированное."""
    client = RobotClient(RobotConfig(), transport=transport, clock=clock.clock, sleep=clock.sleep)
    client.connect()
    return client
