# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import sys
import yaml
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.recipes.save import build_recipe_v3_raw
from multiprocess_prototype.frontend.widgets.tabs.pipeline.model import PipelineModel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.io import graph_to_blueprint

fx = sys.argv[1]
raw = yaml.safe_load(open(fx, encoding="utf-8"))


def canon(x):
    d = Topology.from_dict(x).to_dict()
    return {k: d[k] for k in ("processes", "wires", "displays")}


def first_diff(a, b, path=""):
    if type(a) != type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((path + "/" + k, "<missing>", b[k]))
            elif k not in b:
                out.append((path + "/" + k, a[k], "<missing>"))
            else:
                out += first_diff(a[k], b[k], path + "/" + k)
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [(path, f"len {len(a)}", f"len {len(b)}")]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += first_diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [(path, a, b)]


# ---- Recipes-Save: topology = TopologyRepository.load().to_dict() ~ Topology.from_dict(raw.blueprint).to_dict()
topo_entity = Topology.from_dict(raw["blueprint"])
topo = topo_entity.to_dict()
before = build_recipe_v3_raw(raw, canon(raw["blueprint"]))
after = build_recipe_v3_raw(raw, canon(topo))
d = first_diff(before, after)
print("RECIPES-SAVE canon(before)==canon(after):", not d, d[:5])
# idempotence of canon
c1 = canon(raw["blueprint"])
c2 = canon(c1)
print("canon idempotent:", c1 == c2)

# ---- Pipeline-Save: model loaded as presenter.py:466-472 does (services.topology.load().to_dict())
model = PipelineModel()
model.from_topology_dict(topo)
bp_dict, bindings, _gui = graph_to_blueprint(model)
topology = {"processes": bp_dict.get("processes", []), "wires": bp_dict.get("wires", []), "displays": bindings}
before_p = build_recipe_v3_raw(raw, canon(raw["blueprint"]))
after_p = build_recipe_v3_raw(raw, canon(topology), gui_positions=None, locked_nodes=None)
d = first_diff(before_p, after_p)
print("PIPELINE-SAVE (no layout override) delta paths:", len(d))
for x in d[:10]:
    print("   ", x)
# with layout override like GUI: gui_positions only for scene nodes
gp = dict((raw["blueprint"].get("metadata") or {}).get("gui_positions") or {})
print(
    "file gui_positions keys:", list(gp)[:10], " locked:", (raw["blueprint"].get("metadata") or {}).get("locked_nodes")
)
