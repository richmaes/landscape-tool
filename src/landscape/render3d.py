"""The 3D view (M11): the plan seen in perspective from a camera placed in it.

Built on PyVista (VTK) — Rich asked to leverage an existing engine, and a
prototype showed it does everything needed in well under a second: each
object's resolved 2D shape is raised into a solid from its base to its top
(`solids.effective_solid`), holes and all; flat ground surfaces lie in
paint order, a hair apart so the upper one shows; a vinyl fence runs round
the page with sky above it (Rich: "a surrounding vinyl fence with sky
above it as the 3D background"); the camera stands at `x, y, z` looking at
its look-at point. Flat-shaded first, as decided — outlines on the solids'
edges, one sun and a soft fill light.

Lengths are feet in the plan's own frame (+x east, +y north, +z up).
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedScene
from .materials import MaterialLibrary
from .schema import Camera, SceneDocument
from .solids import effective_solid

SKY_TOP = "#8FB9E0"
SKY_HORIZON = "#EEF4F8"
GROUND_BEYOND = "#B9C8A4"
VINYL = "#F4F2EC"
UNASSIGNED = "#E9E6DF"  # items with no material yet: plain, not flat mode's magenta
OUTLINE = "#3A3833"
SURROUND_HEIGHT = 6.0
SURROUND_THICKNESS = 0.33
_GROUND_STEP = 0.004  # ft between stacked flat surfaces, so the upper one wins


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty]


def _prism(poly: Polygon, base: float, top: float):
    """A closed solid (or, if flat, just the top face) from `poly` — holes
    kept — between heights `base` and `top`, as (points, faces) arrays."""
    triangles = shapely.constrained_delaunay_triangles(poly)
    tris = [np.asarray(t.exterior.coords)[:3] for t in triangles.geoms]
    points, faces = [], []

    def add(face_pts):
        start = len(points)
        points.extend(face_pts)
        faces.append([len(face_pts), *range(start, start + len(face_pts))])

    for t in tris:
        add([(x, y, top) for x, y in t])
        if top - base > 1e-6:
            add([(x, y, base) for x, y in t[::-1]])
    if top - base > 1e-6:
        for ring in (poly.exterior, *poly.interiors):
            coords = np.asarray(ring.coords)
            for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
                add([(x0, y0, base), (x1, y1, base), (x1, y1, top), (x0, y0, top)])
    return np.asarray(points, float), np.hstack(faces) if faces else np.empty(0, int)


def _surround(doc: SceneDocument):
    """The vinyl fence around the page edge, as one mesh's pieces."""
    w, h, t = doc.page_width, doc.page_height, SURROUND_THICKNESS
    sides = [
        (0, -t, w, 0), (w, -t, w + t, h + t), (0, h, w, h + t), (-t, -t, 0, h + t),
    ]
    return [_prism(shapely.box(*s), 0.0, SURROUND_HEIGHT) for s in sides]


def _add_outline(plotter, mesh, color: str, width: float) -> None:
    """The solid's creases (edges where faces meet at more than 30°)."""
    edges = mesh.extract_feature_edges(feature_angle=30, boundary_edges=False,
                                       non_manifold_edges=False, manifold_edges=False)
    if edges.n_points:
        plotter.add_mesh(edges, color=color, line_width=width)


def render_3d_image(
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    camera: Camera,
    width: int = 1200,
    height: int = 800,
    surround: bool = True,
) -> Image.Image:
    """The scene from `camera`, flat-shaded, as a `width` x `height` image.
    `camera.fov` is the horizontal field of view."""
    import pyvista as pv

    plotter = pv.Plotter(off_screen=True, window_size=(width, height), lighting="none")
    try:
        plotter.set_background(SKY_HORIZON, top=SKY_TOP)
        plotter.add_light(pv.Light(
            position=(doc.page_width * 0.2 - 40, doc.page_height * 0.1 - 60, 80),
            focal_point=(doc.page_width / 2, doc.page_height / 2, 0),
            light_type="scene light", intensity=0.6,
        ))
        plotter.add_light(pv.Light(light_type="headlight", intensity=0.4))
        # Balanced so colours read true — a design tool must show the deck as
        # the deck colour: a surface facing the light lands near its material
        # colour, one facing away is gently shaded, never near-black or
        # blown out to white (both happened with stronger direct light).
        surface = dict(smooth_shading=False, ambient=0.55, diffuse=0.45, specular=0.0)

        reach = 20 * max(doc.page_width, doc.page_height, 50)
        ground = pv.Plane(center=(doc.page_width / 2, doc.page_height / 2, -0.02), direction=(0, 0, 1),
                          i_size=reach, j_size=reach)
        plotter.add_mesh(ground, color=GROUND_BEYOND, **surface)

        for rank, obj in enumerate(scene.paint_order()):
            if obj.annotation or obj.rule or obj.geometry.is_empty:
                continue
            polys = _polygons(obj.geometry)
            if not polys:
                continue  # lines (seams) have no surface to draw yet
            solid = effective_solid(obj, materials)
            material = materials.resolve(obj.material) if obj.material else None
            color = UNASSIGNED if material is None or material.id == "__fallback__" else material.color
            base = solid.base + rank * _GROUND_STEP
            top = base + solid.height
            for poly in polys:
                points, faces = _prism(poly, base, top)
                if not len(faces):
                    continue
                # clean() merges the corner points each face was built with,
                # so faces share edges and the creases can be found
                mesh = pv.PolyData(points, faces=faces).clean()
                plotter.add_mesh(mesh, color=color, **surface)
                if solid.height > 0.05:
                    _add_outline(plotter, mesh, OUTLINE, 1.2)

        if surround:
            for points, faces in _surround(doc):
                mesh = pv.PolyData(points, faces=faces).clean()
                plotter.add_mesh(mesh, color=VINYL, **surface)
                _add_outline(plotter, mesh, "#8A8780", 1.0)

        eye = (camera.x, camera.y, camera.z)
        look = (camera.look_x, camera.look_y, camera.look_z)
        direction = np.subtract(look, eye)
        direction = direction / np.linalg.norm(direction)
        up = (0, 0, 1) if abs(direction[2]) < 0.99 else (0, 1, 0)  # straight down: plan-north is up
        plotter.camera_position = [eye, look, up]
        # VTK's view angle is vertical; the camera's fov is horizontal
        aspect = width / height
        vertical = 2 * math.degrees(math.atan(math.tan(math.radians(camera.fov) / 2) / aspect))
        plotter.camera.view_angle = vertical
        plotter.camera.clipping_range = (0.05, reach * 2)

        pixels = plotter.screenshot(return_img=True)
    finally:
        plotter.close()
    return Image.fromarray(np.ascontiguousarray(pixels[:, :, :3]), "RGB")
