# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import glob
import os
import yaml
import sys
from multiprocess_prototype.domain.entities.recipe import Recipe

bad = []
files = sorted(glob.glob(sys.argv[1] + "/*.yaml"))
for f in files:
    try:
        Recipe.from_dict(yaml.safe_load(open(f, encoding="utf-8")))
    except Exception as e:
        bad.append((os.path.basename(f), type(e).__name__, str(e).splitlines()[0][:70]))
print(len(files), "recipes; Recipe.from_dict fails:", bad)
