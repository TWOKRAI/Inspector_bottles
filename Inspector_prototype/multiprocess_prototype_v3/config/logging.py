"""Logging configuration for AppConfig."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.data_schema_module import SchemaBase

_PROTO_ROOT = Path(__file__).resolve().parent.parent


class LoggingConfig(SchemaBase):
    """Logging configuration."""

    log_dir: str = ""
    preset: str = "standard"

    def model_post_init(self, __context: Any) -> None:
        if not self.log_dir:
            default = _PROTO_ROOT / "logs"
            self.log_dir = os.environ.get("INSPECTOR_LOG_DIR") or str(default)
