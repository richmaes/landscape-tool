# 3D View — Requirements

**Status:** requirements only, nothing built yet (captured 2026-09-25). The
work items are milestone **M11** in `TODO.md`.
**Asked for by Rich:** "a new mode, a 3D view from a fixed position that we
can define in the design mode. It will need an X, Y and Z location and a view
direction. We will want to render the elements in the view. This may drive us
to add heights to the elements."

## What the mode is

A third way to see the scene, alongside **Design** and **Art preview**: the
backyard as someone standing at a chosen spot would see it — in perspective,
from a camera placed in the plan. Like Art preview, it is a *view*, read-only;
the plan is still edited in Design mode.

## 1. The camera (the viewpoint)

### 1.1 What a camera is

| Field | Meaning | Units / convention | Suggested default |
|---|---|---|---|
| `id` | a name for the viewpoint ("from the back door") | text | `view_1` |
| `x`, `y` | where the viewer stands | scene feet, the plan's own frame (+x east, +y north) | centre of the page |
| `z` | eye height above the ground | feet | 5.5 (standing adult) |
| `heading` | which way the camera faces, horizontally | degrees clockwise from plan-north (+y) — the same convention as the export north arrow's `north_deg` | 0 (looking north) |
| `pitch` | looking up or down | degrees, negative = down | −10 |
| `fov` | how wide the view is | horizontal field of view, degrees | 60 |

**Direction is stored as heading + pitch, not a look-at point:** the two are
interchangeable (the editor can offer "look at this point" and convert), but
heading/pitch stays meaningful when the camera is moved, and maps to simple
controls.

### 1.2 Stored in the scene

Cameras live in the scene YAML, like the legend and scale indicator — written
only once one exists, so an untouched file keeps round-tripping byte-identical:

```yaml
cameras:
  - id: from_back_door
    x: 18
    y: 2
    z: 5.5
    heading: 0
    pitch: -10
    fov: 60
```

Several named cameras are allowed (a view from the house, one from the gate,
one from the hot tub…); the 3D view shows one at a time.

### 1.3 Defining it in Design mode

- A **camera marker** on the canvas: the viewer's position plus a wedge
  showing the heading and field of view, so what the view will take in is
  visible on the plan.
- **Drag the marker** to move the viewer (X, Y); **drag a direction handle**
  on the wedge to turn it (heading). Same rules as every other canvas drag:
  undoable, marks the file unsaved, never also drags a selected object, and
  recomputes on release.
- **Properties panel** when the camera is selected: X, Y, Z, heading, pitch,
  field of view — typed values, like the Size row.
- Create / delete / rename cameras (a Create menu entry; a chooser for which
  camera the 3D view uses).
- Cameras are not design objects: not in the legend, the rule checker, or
  Tab's selection cycle; hidden in exports unless asked for.

## 2. Heights: giving the flat plan a third dimension

Today every object is a 2D shape. To draw it in perspective, each needs:

| Concept | Meaning |
|---|---|
| **base** (elevation) | how high above the ground its bottom sits (a deck surface on joists, a tub on its pad) |
| **height** | how tall it is from its base (a fence, a tub wall, a pad's thickness) |

### 2.1 Where heights come from

1. **The object** — `base:` / `height:` on the object in YAML, and editable in
   the properties panel (a new **Height** row next to Size).
2. **Else its material** — a default per material (all "deck" is 1.5 ft
   high, all pavers are flat), so most objects need nothing written.
3. **Else its type** — `fence_line` already carries `height` (default 6 ft)
   plus `post_spacing`, `post_size` and `rail_count`, so fences can be built
   post-and-rail without new fields.
4. **Else flat** (height 0): drawn as a surface on the ground.

As with every other field: optional, written only when set, round-trips
losslessly.

### 2.2 Proposed defaults for the backyard (assumptions — to confirm)

| Object / material | Base | Height | Notes |
|---|---|---|---|
| Brick patio, border ring, sand circle, lawn, beds, gravel, mulch | 0 | 0 | ground surfaces |
| Concrete pad | 0 | 0.33 | a 4 in slab |
| Hot tub | on the pad (0.33) | 3.0 | typical shell; water surface ~0.3 below the rim |
| Deck sections | 0 | 1.5 | a low deck; the green "planter" sections the same, with planters on top later |
| Existing vinyl fence | 0 | 6.0 | open item: fence heights (objects.md) |
| Back (property-division) fence | 0 | 6.0 | open item: fence heights |
| Firepit | 0 | 1.25 | form still undecided |
| Water features | 0 | ? | placeholder hexagons; form undecided |
| Tree / shrub canopy | trunk 0 → crown base | crown top | needs a trunk + crown shape, not an extrusion |
| Keep-out zone, annotations | — | — | not physical; optionally drawn as a ground outline |

### 2.3 Things heights raise that the plan never had to answer

- **Ground level.** Assume a flat site at z = 0 for the first version; real
  grade (slopes, steps, the patio's fall) is an open question.
- **What's beyond the page.** The page is a crop of the yard; a 3D view looking
  outward sees an empty horizon. The house position and full site extent are
  already open items — the view will make that gap visible.
- **Stacking.** Things resting on other things (tub on pad, planters on deck
  sections) need `base` to follow what they sit on; a `sits_on: hot_tub_pad`
  relation, in the spirit of `center_of`, would keep that true when heights
  change.
- **Shapes that aren't extrusions.** Tree crowns, a round firepit bowl, the
  hot tub's rounded corners and inset water — first version can extrude
  everything straight up; specific shapes come later.

## 3. Rendering the view

### 3.1 Geometry

- Each object's 2D shape (already resolved by `geometry.py`) **extruded** from
  its base to base + height into a closed solid: top face, bottom face, walls.
  Holes carry through (the patio's cut-out circle).
- Flat objects (height 0) become ground polygons, drawn in paint order so they
  layer correctly on the ground plane.
- Fences built from their posts and rails (`post_spacing`, `post_size`,
  `rail_count`, `height`) rather than as a slab.
- Pavers: joints drawn as a texture on the surface, **not** as geometry — the
  patio is ~6,000 bricks.

### 3.2 Style

- **First version: flat-shaded perspective** — each material's color with
  simple sun lighting (a light direction, darker walls away from it) and
  outlines on silhouette and crease edges, matching Design mode's look.
- **Later: watercolor-and-pencil perspective**, reusing the art renderer's
  look: render color, depth and surface-direction images, then paint washes
  from the color regions and pencil lines from the depth/direction edges.
  Rich's north star for the finished product applies here too.

### 3.3 Technology — decision needed

Nothing for 3D is installed yet except Qt3D (bundled with PySide6).

| Option | For | Against |
|---|---|---|
| **Own small renderer** (numpy: project, clip, depth-sort or z-buffer, draw with cairo) | no new dependencies; pure Python, testable, same output everywhere; cairo gives crisp vector lines for PDF | more code to write; fine for this scene size (tens of objects), slow for thousands of faces |
| **trimesh + pyrender** (offscreen OpenGL) | real 3D engine, lighting, fast | new heavy dependencies; offscreen OpenGL setup varies by machine |
| **Qt3D** (already installed with PySide6) | interactive, in the editor, no new install | on-screen only, harder to export and to test headlessly; Qt3D is deprecated upstream in Qt 6 |
| **Export to glTF / OBJ** for Blender etc. | photoreal possible, no rendering to write | not in the tool; a side door, not the mode |

**Recommendation to confirm:** start with the **own small renderer** — the
backyard is a few dozen extruded shapes, the output must be deterministic and
testable like the rest of the project, and a raster/vector hybrid fits the
existing export pipeline. Add glTF export later as an extra.

### 3.4 In the editor and in exports

- A third view button: **Design | Art preview | 3D view** (and a View menu
  entry with a shortcut), read-only like Art preview, rendering from the
  selected camera; cached by document revision + camera, like Art preview.
- The camera chooser in the toolbar while in 3D view.
- Exports: a `3d` render mode through the same dispatcher (`render.py`) —
  `landscape render --mode 3d --camera from_back_door`, `mode: 3d` +
  `camera:` in export recipes, and the Export dialog's Style list. Output at
  the page's size and DPI, like art mode.

## 4. Acceptance: how we'll know it works

- Camera math against hand-computed cases: a point straight ahead lands at the
  image centre; a point 30° right of heading at the expected x; things behind
  the camera aren't drawn; objects in front hide objects behind.
- Heights round-trip losslessly; an untouched scene saves byte-identical.
- Moving or turning the camera on the canvas is undoable, saved, and the 3D
  view follows (the same real-drag tests as `test_movement.py`).
- Deterministic: the same scene and camera render identically every time.
- Fast enough to preview: the backyard in under ~1 s at screen resolution.

## 5. Open questions for Rich

1. **Heights:** are the proposed defaults in 2.2 right? Specifically fence
   heights (already an open item), deck height, hot tub height.
2. **Camera direction control:** heading + pitch dials, or drag a "look at"
   point on the plan — or both?
3. **Style first:** flat-shaded first, then the watercolor look — or go
   straight for the watercolor look?
4. **Technology:** OK to build the small renderer in-house (no new
   dependencies), per 3.3?
5. **Beyond the page:** should the first version show anything past the page
   edge (a plain ground plane to the horizon, the house as a block once its
   position is known)?
