"""Заставка загрузки отдельным процессом (задача 2.6). Пакет без Qt и фреймворка на импорте."""

from multiprocess_prototype.splash.interface import LeafSender, SplashControllerProtocol, SplashLinkProtocol

__all__ = ["LeafSender", "SplashControllerProtocol", "SplashLinkProtocol"]
