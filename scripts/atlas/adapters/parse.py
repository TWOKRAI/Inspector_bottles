"""Адаптер `parse`: находка FILE_NOT_PARSED для нетестовых .py слоёв framework, services, plugins (Task B7).

Purpose: файл, который сканер не разобрал (`Scan.file` -> None), молча выпадает из карты; адаптер читает такие
    файлы ревизии пакетно (`read_blobs`, strict=False) и даёт по одной находке `warning` на файл. «Не разобран» —
    размер > `MAX_BLOB_BYTES` (`BlobTooLarge`), не utf-8 (`UnicodeDecodeError`) или `ast.parse` упал (`SyntaxError`);
    `detail` — имя класса исключения. Источник путей — `tree.oids()` (symlink и gitlink не читаются), путь с
    переводом строки пропускается (протокол cat-file построчный). Тесты и слои prototype/tools/scripts/docs вне охвата.
Public API: LAYERS, ParseAdapter.
Stability: lite
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.adapters.plans import adapter_version
from scripts.atlas.codemap import is_test
from scripts.atlas.modules import resolve as module_of
from scripts.atlas.scan import MAX_BLOB_BYTES
from scripts.atlas.schema import AdapterOutput, BuildContext, Finding
from scripts.atlas.tree import read_blobs

__all__ = ["LAYERS", "ParseAdapter"]

LAYERS = frozenset({"framework", "services", "plugins"})  # граница как у RulesAdapter.collect, плюс Services/Plugins


def _failure(blob: bytes) -> str | None:
    """Имя класса исключения, если блоб не разбирается, иначе None. Ловит Exception: один файл не роняет сборку."""
    if len(blob) > MAX_BLOB_BYTES:
        return "BlobTooLarge"
    try:
        ast.parse(blob.decode("utf-8").removeprefix("\ufeff"))
    except Exception as exc:  # noqa: BLE001 — имя класса уходит в detail, сборка не падает
        return type(exc).__name__
    return None


class ParseAdapter:
    name = "parse"
    _BASE = 1

    @property
    def version(self) -> int:
        return adapter_version(self._BASE, Path(__file__))

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        tree = ctx.tree
        rows = modules_for(tree)
        layer_of = {r["id"]: r["layer"] for r in rows}
        near = tuple(e for r in rows if r["layer"] in LAYERS for e in r["paths"])  # префильтр: resolve дорог
        paths = sorted(
            p
            for p in tree.oids()
            if p.endswith(".py")
            and "\n" not in p
            and p.startswith(near)
            and not is_test(p)
            and layer_of.get(module_of(p, rows)) in LAYERS
        )
        out = AdapterOutput()
        for path, blob in read_blobs(tree.root, tree.ref, paths, strict=False).items():
            if blob is None:
                continue
            detail = _failure(blob)
            if detail is not None:
                message = f"Файл не разобран ({detail}): в карту не попадёт"
                out.findings.append(Finding("FILE_NOT_PARSED", "warning", f"file:{path}", detail, message, path))
        return out
