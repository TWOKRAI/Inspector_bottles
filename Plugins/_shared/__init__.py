"""Plugins/_shared — переиспользуемые доменные утилиты, общие для нескольких плагинов.

Не плагины (нет @register_plugin, PluginRegistry.discover их не подхватывает) — чистые
классы/функции домена без lifecycle/процесса. Импортируют только framework + Services.
"""
