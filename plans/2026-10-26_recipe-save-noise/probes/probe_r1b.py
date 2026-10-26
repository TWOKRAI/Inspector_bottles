# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import sys
import glob
import yaml
import os
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.recipes.save import build_recipe_v3_raw
from multiprocess_prototype.frontend.widgets.tabs.pipeline.model import PipelineModel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.io import graph_to_blueprint


def canon(x):
    d = Topology.from_dict(x).to_dict()
    return {k: d[k] for k in ("processes", "wires", "displays")}


for fx in sorted(glob.glob(sys.argv[1] + "/*.yaml")):
    raw = yaml.safe_load(open(fx, encoding="utf-8"))
    name = os.path.basename(fx)
    if not isinstance(raw, dict) or not isinstance(raw.get("blueprint"), dict):
        print(name, "no blueprint")
        continue
    try:
        topo = Topology.from_dict(raw["blueprint"]).to_dict()
    except Exception as e:
        print(name, "Topology.from_dict FAILS ->", type(e).__name__, str(e)[:80].replace("\n", " "))
        continue
    before = build_recipe_v3_raw(raw, canon(raw["blueprint"]))
    after = build_recipe_v3_raw(raw, canon(topo))
    m = PipelineModel()
    m.from_topology_dict(topo)
    bp, bind, _ = graph_to_blueprint(m)
    t2 = {"processes": bp["processes"], "wires": bp["wires"], "displays": bind}
    after_p = build_recipe_v3_raw(raw, canon(t2))
    md = raw["blueprint"].get("metadata") or {}
    print(
        f"{name}: recipes-save cancels={before == after}; pipeline cancels(no layout)={before == after_p}; has gui_positions={'gui_positions' in md}; has locked_nodes={'locked_nodes' in md}"
    )
