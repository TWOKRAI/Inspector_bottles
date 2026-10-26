# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
# Does a to_dict override on the nested model strip None when the PARENT is model_dump'ed? (design 1.1c DESIGN 1)
from pydantic import BaseModel, ConfigDict, model_serializer


class Topo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str | None = None
    description: str | None = None
    processes: tuple[int, ...] = ()

    def to_dict(self):
        d = self.model_dump(mode="json")
        for k in ("name", "description"):
            if d.get(k) is None:
                d.pop(k, None)
        return d


class Rec(BaseModel):
    blueprint: Topo = Topo()

    def to_dict(self):
        return self.model_dump(mode="json")


print("Topo.to_dict():      ", Topo().to_dict())
print("Rec.to_dict() nested:", Rec().to_dict())


class Topo2(Topo):
    @model_serializer(mode="wrap")
    def _ser(self, handler):
        d = handler(self)
        for k in ("name", "description"):
            if d.get(k) is None:
                d.pop(k, None)
        return d


class Rec2(BaseModel):
    blueprint: Topo2 = Topo2()


print(
    "wrap serializer, Rec2.model_dump():",
    Rec2().model_dump(mode="json"),
    "| Topo2().model_dump():",
    Topo2().model_dump(mode="json"),
)
