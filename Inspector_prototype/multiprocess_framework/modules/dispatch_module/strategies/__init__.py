"""Стратегии диспетчеризации сообщений."""

from .base_strategy import BaseStrategy
from .exact_match import ExactMatchStrategy
from .pattern_match import PatternMatchStrategy
from .fallback_match import FallbackMatchStrategy
from .chain_match import ChainMatchStrategy

__all__ = [
    'BaseStrategy',
    'ExactMatchStrategy',
    'PatternMatchStrategy',
    'FallbackMatchStrategy',
    'ChainMatchStrategy',
]

