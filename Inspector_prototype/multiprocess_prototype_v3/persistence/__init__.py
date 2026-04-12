# multiprocess_prototype_v3/persistence/__init__.py
"""Пути персистентности v3."""

from .paths import config_json_path, detections_db_url, ensure_data_dir

__all__ = ["config_json_path", "detections_db_url", "ensure_data_dir"]
