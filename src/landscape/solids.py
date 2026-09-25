"""Where an object's third dimension comes from, for the 3D view (M11).

In order: the object's own `solid: {base, height}`; else its material's
default `solid`; else — for a fence line — its own `height` (folded into
the object's solid when the scene is resolved); else flat on the ground.
"""

from __future__ import annotations

from .geometry import ResolvedObject
from .materials import MaterialLibrary
from .schema import Solid


def effective_solid(obj: ResolvedObject, materials: MaterialLibrary) -> Solid:
    if obj.solid is not None:
        return obj.solid
    default = materials.resolve(obj.material).solid if obj.material else None
    if default:
        return Solid(base=float(default.get("base", 0)), height=float(default.get("height", 0)))
    return Solid(0.0, 0.0)
