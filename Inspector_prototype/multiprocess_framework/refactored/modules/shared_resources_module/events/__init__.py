"""Модуль событий для межпроцессного взаимодействия."""

from .core import EventManager
from ..types import EventType

__all__ = ["EventManager", "EventType"]
