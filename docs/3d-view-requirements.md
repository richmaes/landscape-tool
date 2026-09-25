# 3D View — Requirements

**Status:** requirements captured 2026-09-25; Rich's answers recorded the same
day (see **Decisions** below); a feasibility prototype rendered — nothing built
into the project yet. The work items are milestone **M11** in `TODO.md`.
**Asked for by Rich:** "a new mode, a 3D view from a fixed position that we
can define in the design mode. It will need an X, Y and Z location and a view
direction. We will want to render the elements in the view. This may drive us
to add heights to the elements."

## Decisions (Rich, 2026-09-25)

- **Hot tub:** 3 ft tall (on its pad) — as proposed.
- **Deck heights — the deck is multi-level:** the **northward** deck 1.5 ft,
  the **middle** deck 1 ft, the **forward** deck 6 in (0.5 ft). Mapped to the
  scene as: north = `deck_nw_green`, `deck_ne_green`, `deck_nw_wood`,
  `deck_ne_wood`; middle = `deck_e`, `deck_w`; forward = `deck_s` (confirm).
- **Camera direction: a "look at" point on the plan.** The camera is where you
  stand plus a point you look at — both dragged on the canvas — rather than
  heading/pitch dials. (Supersedes 1.1's heading/pitch as the stored form.)
- **Style: flat-shaded first** (it's also the fastest preview).
- **Renderer: leverage an existing engine if there is one** — see 3.3; a
  prototype with **PyVista** (VTK) works.
- **Background: a vinyl fence all around the yard, with sky above it** — see
  2.4.

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
| `look_x`, `look_y`, `look_z` | the point the camera looks at (**decided**: a look-at point on the plan, dragged on the canvas) | scene feet; `look_z` is a height | the page centre, 1.5 ft up |
| `fov` | how wide the view is | horizontal field of view, degrees | 60 |

**Direction is a look-at point (decided).** Heading and tilt follow from it
(heading = the direction from the camera to the point, in degrees clockwise
from plan-north like the north arrow's `north_deg`); the panel can show them
read-only. Moving the camera keeps looking at the same point — e.g. circle the
hot tub while it stays in the middle of the view.

### 1.2 Stored in the scene

Cameras live in the scene YAML, like the legend and scale indicator — written
only once one exists, so an untouched file keeps round-tripping byte-identical:

```yaml
cameras:
  - id: from_back_door
    x: 18
    y: 2
    z: 5.5
    look_x: 18
    look_y: 23
    look_z: 1.5
    fov: 60
```

Several named cameras are allowed (a view from the house, one from the gate,
one from the hot tub…); the 3D view shows one at a time.

### 1.3 Defining it in Design mode

- A **camera marker** on the canvas: the viewer's position plus a wedge
  showing the heading and field of view, so what the view will take in is
  visible on the plan.
- **Drag the marker** to move the viewer (X, Y); **drag the look-at point**
  (a second marker, joined to the camera by a line) to aim it. Same rules as every other canvas drag:
  undoable, marks the file unsaved, never also drags a selected object, and
  recomputes on release.
- **Properties panel** when the camera is selected: X, Y, Z, look-at X, Y, Z,
  field of view — typed values, like the Size row (heading and tilt shown
  read-only).
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
| Hot tub | on the pad (0.33) | 3.0 | **confirmed** (Rich); water surface ~0.3 below the rim |
| Deck — north sections (`deck_nw_*`, `deck_ne_*`) | 0 | **1.5** | **decided** (Rich): the deck is multi-level |
| Deck — middle sections (`deck_e`, `deck_w`) | 0 | **1.0** | **decided** |
| Deck — forward section (`deck_s`) | 0 | **0.5** (6 in) | **decided** |
| Existing vinyl fence | 0 | 6.0 | open item: fence heights (objects.md) |
| Back (property-division) fence | 0 | 6.0 | open item: fence heights |
| Firepit | 0 | 1.25 | form still undecided |
| Water features | 0 | ? | placeholder hexagons; form undecided |
| Tree / shrub canopy | trunk 0 → crown base | crown top | needs a trunk + crown shape, not an extrusion |
| Keep-out zone, annotations | — | — | not physical; optionally drawn as a ground outline |

### 2.4 Background: the surrounding vinyl fence and sky (decided)

Rich: *"There is a vinyl fence around the back yard. You can make a surrounding
vinyl fence with sky above it as the 3D background."*

- A 6 ft white vinyl fence enclosing the yard, and a sky gradient above it
  (pale at the horizon, blue overhead); ground continues out to the fence.
- **Where it runs:** the real yard boundary isn't in the scene yet (the page is
  a crop; the full site extent is an open item). Until it is, the surround
  follows the **page boundary** — the prototype does this — and becomes real
  `fence_line` objects once the boundary is known, joining the existing vinyl
  fence already drawn as one side of it.
- It is part of the scene, not just a backdrop: it should show in Design mode
  too once it's real fence objects.

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

### 3.3 Technology — leverage an engine (Rich: "isn't there something we can leverage?")

Nothing for 3D is installed yet except Qt3D (bundled with PySide6).

| Option | For | Against |
|---|---|---|
| **Own small renderer** (numpy: project, clip, depth-sort or z-buffer, draw with cairo) | no new dependencies; pure Python, testable, same output everywhere; cairo gives crisp vector lines for PDF | more code to write; fine for this scene size (tens of objects), slow for thousands of faces |
| **trimesh + pyrender** (offscreen OpenGL) | real 3D engine, lighting, fast | new heavy dependencies; offscreen OpenGL setup varies by machine |
| **Qt3D** (already installed with PySide6) | interactive, in the editor, no new install | on-screen only, harder to export and to test headlessly; Qt3D is deprecated upstream in Qt 6 |
| **Export to glTF / OBJ** for Blender etc. | photoreal possible, no rendering to write | not in the tool; a side door, not the mode |

| **PyVista** (a Python layer over **VTK**, the long-established 3D toolkit) | extrusion, **look-at cameras** (`camera_position = [eye, look_at, up]`), flat shading, lighting, feature-edge outlines, **sky-gradient backgrounds**, offscreen rendering to an image, and a **depth image** for the later pencil-edge style — all built in | a large dependency (VTK ≈ **520 MB** installed); offscreen rendering on a headless Linux server needs VTK's OSMesa/EGL build |

**Prototype (2026-09-25, in a throwaway environment — not added to the
project):** PyVista 0.49 / VTK 9.7 installed and rendered the live backyard
offscreen on this Mac: every object extruded to the decided heights (hot tub
3 ft on its pad, decks at 1.5 / 1 / 0.5 ft, fences 6 ft), a surrounding vinyl
fence on the page boundary, sky gradient, flat shading with outlines, camera
by look-at point. **~0.75 s to build the scene, ~0.17 s to render**
1600 x 1000 — inside the < 1 s preview target. Image:
`out/3d-prototype/backyard-3d-first-look.png`. Rough edges to fix in the real
build: ground layers (the sand circle hidden under the patio) need proper
stacking, and the lighting is too dim.

**Recommendation:** **PyVista**, if the ~520 MB dependency is acceptable —
it replaces most of what an in-house renderer would have to write (camera,
hiding, lighting, outlines, sky) and its depth image serves the later
watercolor style. Fallback if not: the small in-house renderer.

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

Answered 2026-09-25 (see **Decisions**): hot tub height, deck tiers, look-at
point, flat-shaded first, leverage an engine, surrounding fence + sky.
Still open:

1. **Adding PyVista/VTK (~520 MB)** as a project dependency — OK?
2. **Deck tier mapping:** north = the four `deck_nw_*`/`deck_ne_*` sections,
   middle = `deck_e`/`deck_w`, forward = `deck_s` — right?
3. **Fence heights:** 6 ft for the existing vinyl fence, the back fence and
   the surround (still an open item in objects.md).
4. **The real yard boundary** for the surrounding fence (until then: the page
   boundary).
