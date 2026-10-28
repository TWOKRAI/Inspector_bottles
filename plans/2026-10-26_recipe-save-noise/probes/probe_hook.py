# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import glob
import os
import sys
import yaml
from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

h = InspectorRecipeFormatHook()
files = sorted(glob.glob(sys.argv[1] + "/*.yaml")) + [sys.argv[2]]
nonidem, notidentity = [], []
for f in files:
    raw = yaml.safe_load(open(f, encoding="utf-8"))
    n1 = h.normalize(raw)
    n2 = h.normalize(n1)
    if n1 != n2:
        nonidem.append(os.path.basename(f))
    if n1 != raw:
        notidentity.append((os.path.basename(f), sorted(set(raw) ^ set(n1))))
print(len(files), "files; normalize NOT idempotent:", nonidem)
print("normalize(file) != file (file-space != normalized-space):", notidentity)
