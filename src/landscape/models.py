"""The local 3D models folder (M11): model files that are never committed.

Model licences such as TurboSquid's don't allow redistributing the files,
so they live in a git-ignored folder — `models/` at the repository root by
default, or wherever `LANDSCAPE_MODELS` points — and a scene refers to one
only by name. Everything here copes with the file not being there: a
scene still opens and renders, with a placeholder in the model's place.
"""

from __future__ import annotations

import os
from pathlib import Path

from .schema import Model, SceneDocument

# formats VTK can import: glTF keeps materials and textures best
MODEL_EXTENSIONS = (".glb", ".gltf", ".obj", ".3ds", ".stl", ".ply", ".wrl", ".vrml")


def default_models_dir() -> Path:
    override = os.environ.get("LANDSCAPE_MODELS")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "models"


def available_models(directory: Path | None = None) -> list[str]:
    """Every model file in the folder (subfolders included), as paths
    relative to it, sorted."""
    directory = Path(directory or default_models_dir())
    if not directory.is_dir():
        return []
    return sorted(
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in MODEL_EXTENSIONS
    )


def find_model(name: str, directory: Path | None = None) -> Path | None:
    """A model by its path inside the folder, or else by its file name
    anywhere in it (so files can be reorganised into subfolders). None if
    it isn't there — the caller shows a placeholder."""
    directory = Path(directory or default_models_dir())
    if not name or not directory.is_dir():
        return None
    direct = directory / name
    if direct.is_file():
        return direct
    matches = sorted(p for p in directory.rglob(Path(name).name) if p.is_file())
    return matches[0] if matches else None


def missing_models(doc: SceneDocument, directory: Path | None = None) -> list[str]:
    """The model files a scene uses that the folder doesn't have."""
    names = {o.primitive.file for o in doc.objects if isinstance(o.primitive, Model)}
    names |= {o.model for o in doc.objects if o.model}  # design elements drawn as a model (the firepit)
    return sorted(n for n in names if find_model(n, directory) is None)


def default_up_axis(file: str) -> str:
    """STL and PLY files are usually Z-up; glTF is Y-up by specification,
    and OBJ and the rest mostly Y-up."""
    return "z" if file.lower().endswith((".stl", ".ply")) else "y"


def model_proportions(path: Path, up: str = "", across: float = 4.0) -> tuple[float, float, float]:
    """(width, depth, height) in feet for a newly placed model: its own
    proportions, stood upright, scaled so its larger footprint side is
    `across` feet. Model files' units vary (centimetres, metres, inches),
    so the real size is the designer's to set afterwards."""
    import numpy as np
    import pyvista as pv

    mesh = pv.read(str(path))
    if isinstance(mesh, pv.MultiBlock):
        mesh = mesh.combine()
    x0, x1, y0, y1, z0, z1 = mesh.bounds
    ex, ey, ez = x1 - x0, y1 - y0, z1 - z0
    if (up or default_up_axis(path.name)) == "y":
        ex, ey, ez = ex, ez, ey  # standing it up: its y becomes the height
    s = across / max(ex, ey, 1e-9)
    return float(np.round(ex * s, 3)), float(np.round(ey * s, 3)), float(np.round(ez * s, 3))
