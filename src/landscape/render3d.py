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
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedScene
from .materials import MaterialLibrary
from .schema import Camera, SceneDocument
from .fences import fence_centerline, fence_spec
from .solids import effective_solid

SKY_TOP = "#8FB9E0"
SKY_HORIZON = "#EEF4F8"
GROUND_BEYOND = "#B9C8A4"
VINYL = "#F4F2EC"
UNASSIGNED = "#E9E6DF"  # items with no material yet: plain, not flat mode's magenta
OUTLINE = "#3A3833"
PLACEHOLDER = "#D9D6CE"  # a model whose file isn't in the models folder
MODEL_DEFAULT = "#CFC9BD"  # a model file with no colours of its own (STL, PLY)
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


_PANEL_THICKNESS = 0.1  # ft: slats/boards
_POST_CAP = 0.25  # ft: how far posts stand above the panel


def _add_fence(plotter, line: LineString, spec, color: str, base: float, height: float) -> None:
    """A fence along `line`: a slatted (vinyl) or boarded (cedar) panel
    with its boards as a tiled texture, and square posts every
    `spec.post_spacing`, standing a little above the panel."""
    import pyvista as pv

    from .fences import board_texture, fence_posts

    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    length = line.length
    if length <= 0:
        return
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -dy * _PANEL_THICKNESS / 2, dx * _PANEL_THICKNESS / 2
    top = base + height
    repeat = length / (4 * (spec.slat_width + spec.gap))  # the texture holds 4 boards
    points, faces, uvs = [], [], []

    def quad(corners, uv):
        start = len(points)
        points.extend(corners)
        uvs.extend(uv)
        faces.append([4, start, start + 1, start + 2, start + 3])

    for side in (1, -1):  # both faces of the panel, boards on each
        ox, oy = nx * side, ny * side
        a, b = (x0 + ox, y0 + oy), (x1 + ox, y1 + oy)
        quad([(*a, base), (*b, base), (*b, top), (*a, top)], [(0, 0), (repeat, 0), (repeat, 1), (0, 1)])
    a0, a1 = (x0 + nx, y0 + ny), (x0 - nx, y0 - ny)
    b0, b1 = (x1 + nx, y1 + ny), (x1 - nx, y1 - ny)
    quad([(*a0, top), (*b0, top), (*b1, top), (*a1, top)], [(0, 1)] * 4)  # the top edge
    panel = pv.PolyData(np.asarray(points, float), faces=np.hstack(faces))
    panel.active_texture_coordinates = np.asarray(uvs, float)
    texture = pv.Texture(board_texture(spec, color))
    texture.repeat = True
    plotter.add_mesh(panel, texture=texture, ambient=0.55, diffuse=0.45, smooth_shading=False)

    post_color = "#" + "".join(f"{int(int(color[i:i + 2], 16) * (0.94 if spec.boards == 'vinyl' else 0.75)):02X}"
                               for i in (1, 3, 5))
    for post in fence_posts(line, spec.post_spacing, spec.post_size):
        pts, fcs = _prism(post, base, top + _POST_CAP)
        mesh = pv.PolyData(pts, faces=fcs).clean()
        plotter.add_mesh(mesh, color=post_color, ambient=0.55, diffuse=0.45, smooth_shading=False)
        _add_outline(plotter, mesh, "#8A8780" if spec.boards == "vinyl" else OUTLINE, 1.0)


def place_models(plotter, scene: ResolvedScene, materials: MaterialLibrary, models_dir=None) -> list[tuple]:
    """Every `model` object: its file from the models folder, stood upright,
    scaled to fit inside its declared width x depth x height *keeping its
    proportions*, turned and set on its footprint — or, if the file isn't
    there (or won't load), a plain placeholder box of that size. Returns
    (object id, "model" | "placeholder", final bounds) for each."""
    import pyvista as pv

    from .models import find_model

    placed = []
    for obj in scene.paint_order():
        placement = obj.model
        if placement is None or obj.geometry.is_empty:
            continue
        solid = effective_solid(obj, materials)
        path = find_model(placement.file, models_dir)
        actors = _import_model(plotter, path) if path is not None else []
        if actors:
            matrix = _fit_matrix(_combined_bounds(actors), placement, solid.base, solid.height)
            for actor in actors:
                existing = actor.GetUserMatrix()
                own = pv.array_from_vtkmatrix(existing) if existing is not None else np.eye(4)
                actor.SetUserMatrix(pv.vtkmatrix_from_array(matrix @ own))
            placed.append((obj.id, "model", _combined_bounds(actors)))
            continue
        box_mesh = None
        for poly in _polygons(obj.geometry):
            points, faces = _prism(poly, solid.base, solid.base + solid.height)
            box_mesh = pv.PolyData(points, faces=faces).clean()
            plotter.add_mesh(box_mesh, color=PLACEHOLDER, opacity=0.85, smooth_shading=False, ambient=0.55,
                             diffuse=0.45)
            _add_outline(plotter, box_mesh, "#8A8780", 1.0)
        if box_mesh is not None:
            placed.append((obj.id, "placeholder", tuple(box_mesh.bounds)))
    return placed


def _import_model(plotter, path) -> list:
    """Load a model file into the plotter; the new actors. Importers keep a
    file's materials and textures; if one yields nothing, fall back to
    reading the bare geometry."""
    import pyvista as pv

    before = set(plotter.renderer.actors)
    importers = {".glb": plotter.import_gltf, ".gltf": plotter.import_gltf, ".obj": plotter.import_obj,
                 ".3ds": plotter.import_3ds, ".wrl": plotter.import_vrml, ".vrml": plotter.import_vrml}
    importer = importers.get(path.suffix.lower())
    if importer is not None:
        try:
            importer(str(path))
        except Exception:  # a file the importer can't handle: fall back below
            pass
    actors = [a for key, a in plotter.renderer.actors.items() if key not in before]
    if actors:
        return actors
    try:
        mesh = pv.read(str(path))
    except Exception:
        return []  # unreadable: the caller draws a placeholder
    if isinstance(mesh, pv.MultiBlock):
        mesh = mesh.combine().extract_surface()
    if mesh.n_points == 0:
        return []
    return [plotter.add_mesh(mesh, color=MODEL_DEFAULT, ambient=0.55, diffuse=0.45)]


def _combined_bounds(actors) -> tuple:
    b = np.array([a.GetBounds() for a in actors])
    return (b[:, 0].min(), b[:, 1].max(), b[:, 2].min(), b[:, 3].max(), b[:, 4].min(), b[:, 5].max())


def _fit_matrix(bounds, placement, base: float, height: float) -> np.ndarray:
    """Model space -> scene: turn the file's up axis to +z, move its
    footprint centre to the origin and its bottom to 0, scale uniformly to
    fit width x depth x height, turn by the placement's rotation, and set
    it on its footprint at `base`."""
    up = np.eye(4)
    if placement.up_axis == "y":  # +90 degrees about x: y -> z, z -> -y
        up = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)
    x0, x1, y0, y1, z0, z1 = bounds
    corners = np.array([[x, y, z, 1] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]) @ up.T
    lo, hi = corners[:, :3].min(axis=0), corners[:, :3].max(axis=0)
    extent = hi - lo
    targets = (placement.width, placement.depth, height)
    ratios = [t / e for t, e in zip(targets, extent) if e > 1e-9 and t > 0]
    s = min(ratios) if ratios else 1.0
    centre = np.eye(4)
    centre[:3, 3] = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
    scale = np.diag([s, s, s, 1.0])
    a = math.radians(placement.rotation)
    turn = np.array([[math.cos(a), -math.sin(a), 0, 0], [math.sin(a), math.cos(a), 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    place = np.eye(4)
    place[:3, 3] = [placement.x, placement.y, base]
    return place @ turn @ scale @ centre @ up


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
    models_dir=None,
) -> Image.Image:
    """The scene from `camera`, flat-shaded, as a `width` x `height` image.
    `camera.fov` is the horizontal field of view. Model files are looked up
    in `models_dir` (default: `models.default_models_dir()`)."""
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
            if obj.annotation or obj.rule or obj.geometry.is_empty or obj.model is not None:
                continue  # models are placed below, from their files
            polys = _polygons(obj.geometry)
            if not polys:
                continue  # lines (seams) have no surface to draw yet
            solid = effective_solid(obj, materials)
            material = materials.resolve(obj.material) if obj.material else None
            color = UNASSIGNED if material is None or material.id == "__fallback__" else material.color
            spec = fence_spec(material, doc.units) if material is not None else None
            if spec is not None and solid.height > 0:
                _add_fence(plotter, fence_centerline(obj.geometry), spec, color, solid.base, solid.height)
                continue
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

        place_models(plotter, scene, materials, models_dir)

        if surround:
            vinyl = materials.materials.get("fence_vinyl")
            spec = fence_spec(vinyl, doc.units) if vinyl is not None else None
            if spec is not None:  # Rich's vinyl fence all round: slats and posts
                w, h = doc.page_width, doc.page_height
                corners = [(0, 0), (w, 0), (w, h), (0, h)]
                for a, b in zip(corners, corners[1:] + corners[:1]):
                    _add_fence(plotter, LineString([a, b]), spec, vinyl.color, 0.0, SURROUND_HEIGHT)
            else:
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


# ---------------------------------------------------------------------------
# Export (M11): the 3D view as PNG, or embedded in PDF/SVG
# ---------------------------------------------------------------------------

PRINT_DPI = 150.0  # a 3D picture has no plan scale; this sets its print size


def resolve_camera(doc: SceneDocument, camera: "Camera | str | None") -> Camera:
    """A camera object, a camera id from the scene, or None for the scene's
    first camera."""
    if isinstance(camera, Camera):
        return camera
    if not doc.cameras:
        raise ValueError("the scene has no camera — add one in the editor's 3D camera section")
    if camera is None:
        return doc.cameras[0]
    for candidate in doc.cameras:
        if candidate.id == camera:
            return candidate
    raise ValueError(f"no camera '{camera}' in the scene (it has: {', '.join(c.id for c in doc.cameras)})")


def render_3d_to_file(doc, scene, materials, path, camera=None, width: int = 1600, height: int = 1000,
                      surround: bool = True, models_dir=None) -> None:
    """The 3D view from `camera` as a `width` x `height` picture: a PNG
    (DPI recorded as `PRINT_DPI`), or embedded at that size in a PDF/SVG."""
    import io
    from pathlib import Path

    import cairo

    image = render_3d_image(doc, scene, materials, resolve_camera(doc, camera), width=width, height=height,
                            surround=surround, models_dir=models_dir)
    path = Path(path)
    if path.suffix.lower() == ".png":
        image.save(str(path), format="PNG", dpi=(PRINT_DPI, PRINT_DPI))
        return
    w_pt, h_pt = width / PRINT_DPI * 72, height / PRINT_DPI * 72
    if path.suffix.lower() == ".pdf":
        surface = cairo.PDFSurface(str(path), w_pt, h_pt)
    else:
        surface = cairo.SVGSurface(str(path), w_pt, h_pt)
        surface.set_document_unit(cairo.SVGUnit.PT)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    source = cairo.ImageSurface.create_from_png(buffer)
    ctx = cairo.Context(surface)
    ctx.scale(w_pt / width, h_pt / height)
    ctx.set_source_surface(source, 0, 0)
    ctx.paint()
    surface.finish()
