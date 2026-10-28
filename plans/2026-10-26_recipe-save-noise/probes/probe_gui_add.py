# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import sys
import yaml
import io
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.frontend.widgets.tabs.pipeline.model import PipelineModel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.io import graph_to_blueprint

raw = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
topo = Topology.from_dict(raw["blueprint"]).to_dict()
m = PipelineModel()
m.from_topology_dict(topo)
m.add_process("cam2", plugin_name="CameraServicePlugin", category="source")
m.add_process("cam3")  # bare process, no plugin
m.add_wire("cam2.CameraServicePlugin.frame", "vision.color_convert.frame")
bp, bind, _ = graph_to_blueprint(m)
t = {"processes": bp["processes"], "wires": bp["wires"], "displays": bind}
try:
    c = Topology.from_dict(t).to_dict()
    print(
        "canon(GUI-added process) OK; new proc canon keys:",
        sorted(c["processes"][-2].keys())[:6],
        "... plugins:",
        c["processes"][-2]["plugins"],
    )
except Exception as e:
    print("canon(GUI-added process) FAILS:", type(e).__name__, str(e)[:300].replace("\n", " | "))
# CRLF: bytes-load trap
from multiprocess_framework.modules.recipe.yaml_io import _make_yaml

y = _make_yaml()
crlf = open(sys.argv[2], "rb").read()
doc = y.load(crlf)
b = io.StringIO()
y.dump(doc, b)
out = b.getvalue().replace("\n", "\r\n")
print("bytes-load + replace: '\r\r\n' count =", out.count("\r\r\n"))
doc = y.load(crlf.decode("utf-8").replace("\r\n", "\n"))
b = io.StringIO()
y.dump(doc, b)
print("text-load + replace == original CRLF bytes:", b.getvalue().replace("\n", "\r\n").encode() == crlf)
