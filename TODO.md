# Landscape Rendering Tool — Task List

**Status:** M0–M5, M1, M3b, and (bar one genuinely-blocked item) M8 all complete. The editor now covers its entire checklist: load, pan/zoom, select/move/resize/rotate (drag directly or via the panel), swatch-based material picking, relation editing, create-objects-from-a-palette, lossless save, undo/redo, autosave, layer toggling, watch-and-reload, live rule-checker feedback, and export-to-PNG/SVG/PDF — see the M8 section for what's honestly partial (resize/rotate is uniform-scale/absolute-rotation only) versus fully done. Its non-GUI logic lives in `EditorSession` (`editor_session.py`, zero Qt dependency), with `EditorWindow` as a thin wrapper. `scenes/backyard.yaml` is the real design (converted from `extraction/objects.json`), not just the `scenes/example.yaml` schema fixture — see M1 for a real finding this surfaced (the documented `deck_intrudes_on_keepout` doesn't actually hold against the keepout as drawn). Remaining open work: M6 (art mode, not started), M7 (export polish — DPI/scale bar/north arrow/batch — separate from the editor's own export, which just calls M5), M8b (headless/batch CLI), M9 (broader validation), M10 (docs).
**Last updated:** 2026-09-22

## Decisions locked in

| Area | Decision |
|---|---|
| Language | Python |
| Geometry source | Extracted from `backyard concept.pdf` (done). Scene lives as hand- and tool-editable YAML. |
| Scene format | **YAML** — data only, round-trippable. No Python DSL, no expression language. |
| Primary user | Design is driven by a non-technical user; the graphical editor is the main interface, the CLI is the developer back door |
| Render modes | (1) flat pastel color-coding, (2) hand-drawn pastel art |
| Outputs | Screen preview, raster PNG, vector SVG/PDF |
| Constraints | Warn, never block. Rule checker flags violations; the designer is never prevented from moving something. |

## Decision record

**Scene format: YAML, single layer.** A graphical editor is planned and the
designer is non-technical, so the editor must be able to read, modify and
write the scene file losslessly. Hand-written Python cannot be round-tripped
by a tool, which rules out a Python DSL however convenient its expressions
would be. Derived geometry is handled by declarative relations, reusable
definitions, and a rule checker instead — see M2 and M3b.

## Working practices

- Commit as work progresses — small, logical commits per milestone item
  rather than one large commit at the end of a milestone.
- Develop tests alongside each milestone's implementation, not deferred
  entirely to M9. M9 is for the comprehensive/regression pass, but each
  primitive, relation, or rule should get a quick check as it's built so
  regressions surface immediately rather than at the end.
- Update this file and the relevant decision/markdown docs (e.g.
  `extraction/objects.md`) periodically as work happens, not only at the
  end of a session — checkboxes, decision records, and open
  questions/items should stay current with what has actually been
  decided or built.
- **10-minute rule:** no AI-driven operation may run longer than 10
  minutes without pausing to notify the user that it is taking longer
  than expected, and asking for approval or assistance before continuing.

## Open questions

- [x] ~~Scene script format~~ — resolved: YAML. See above.
- [x] ~~Is the PDF vector or scanned?~~ — vector, Illustrator 30.6, extracted.
- [x] ~~Units and coordinate origin~~ — feet, +x east / +y north, origin bottom-left, 36 pt = 1 ft.
- [x] ~~UI stack for the editor~~ — resolved 2026-09-21: desktop, using **PySide6** (Qt for Python; LGPL, free for commercial use, unlike PyQt6's GPL/commercial dual license). `QGraphicsView`/`QGraphicsScene` gives interactive selection/move/resize/rotate largely for free, which Tkinter's plain `Canvas` doesn't.
- [ ] **Target print size / DPI** for the art mode (drives texture resolution budget).
- [ ] **Elevation / 3D** — assumed out of scope; 2D plan view only. Confirm.
- [ ] **Full site extent** — the source PDF is a 24 x 24 ft crop; the real yard is significantly larger.
- [ ] **Mechanical bay side** — east or west; both currently modelled as removable deck panels.

Design-content unknowns (paver spec, burnable material, fence heights, north
orientation, water feature form) are tracked in `extraction/objects.md` under
**Open items**, not duplicated here.

---

## M0 — Project setup

- [x] Create repo structure (`src/landscape/`, `scenes/`, `assets/`, `tests/`, `out/`)
- [x] `git init`, `.gitignore` (ignore `out/`, `__pycache__/`, venv)
- [x] Set up virtualenv + `pyproject.toml` / `requirements.txt`
- [x] Evaluate and pin core libraries:
  - [x] `shapely` — polygon ops, buffering, boolean union/difference, offsetting
  - [x] `numpy` / `scipy` — splines, interpolation, sampling
  - [x] `pycairo` — vector rendering backend (chosen over `cairosvg`: native PNG/SVG/PDF surfaces from one drawing API, matches the M5/M7 rendering-abstraction plan; system `cairo` confirmed present via Homebrew)
  - [x] `Pillow` — raster compositing, paper grain, blur
  - [x] `svgwrite` — vector export
  - [x] `opensimplex` — wavy paths and texture variation
  - [x] `pdfplumber` — PDF path extraction; proven on the real file in `tools/extract_pdf.py`
  - [x] `pytest` — tests
  - [x] `PyYAML` — not in the original list but required for the M2 scene format; added
- [x] CLI entry point skeleton (`landscape render scene.yaml --mode flat --out out/plan.png`) — stub `render` command wired up via `pyproject.toml` `[project.scripts]`, exits 1 with "not yet implemented" until M2/M3 land; covered by `tests/test_cli.py`

## M1 — PDF to scene script  *(complete)*

- [x] Ingest the source site-plan PDF; determine vector vs. raster — pure vector
- [x] Extract vector paths with coordinates, colours and true paint order
- [x] Establish scale — 36 pt = 1 ft, confirmed by the 2 ft scale badge and round dimensions
- [x] Classify extracted geometry into named objects with roles
- [x] Emit `extraction/objects.json` + `extraction/objects.md` (20 objects)
- [x] Capture the existing vinyl fence, which is absent from the PDF
- [x] Convert `objects.json` into the first real scene YAML once M2 lands — `scenes/backyard.yaml`, all 20 objects, faithfully reproducing the actual extracted geometry rather than a corrected version (see below)
- [x] Extraction kept as a one-time bootstrap (`tools/extract_pdf.py`), not a runtime dependency

**`scenes/backyard.yaml`** is the real design, not a fixture — unlike
`scenes/example.yaml` (a hand-authored schema-coverage demo with arbitrary
placement, never meant to resemble the PDF). `rules/backyard.yaml` mirrors
the findings in `extraction/objects.md` "Geometric findings" as executable
checks. Running it surfaced a genuinely new, more precise result, not
just a re-confirmation:

- The `firepit_keepout_concentric` (0.792 ft off-center) and
  `firepit_keepout_contained_by_site` (overhangs by 7.819 ft
  center-to-center) rules reproduce the documented findings exactly.
- **`deck_intrudes_on_keepout` does not actually hold against the drawing
  as-is.** `extraction/objects.json`'s "deck_s is 0.085 ft inside the
  keep-out" measures distance from the *firepit's own center* — that's
  what the clearance would be if the keepout gets recentered on the
  firepit first (fixing the concentricity flaw). Measured against the
  keepout circle's own drawn position, `deck_s` is actually a clear 0.675
  ft away. Confirmed precisely with `shapely` (`tests/test_backyard_scene.py`),
  not just re-asserted. Worth a decision: recenter the keepout (M2's
  `center_of` relation would then keep it locked to the firepit going
  forward) and re-check whether the 0.085 ft conflict is real once that's
  done, or leave it as a known, intentionally-off-center placeholder.
- A palette gap, found only by actually rendering it: the new
  `sand_tbd` placeholder material (`#E8DCC0`, matching the PDF's sand
  fill) and the existing `fence` material (`#E4DCC8`) sit at color
  distance 0.124 — just over the 0.12 "too similar" threshold, so M4's
  own palette checker doesn't catch it, but `back_fence` all but
  disappears into `site_circle` in the actual render. The threshold is
  probably too lenient; not fixed yet, just measured and locked into a
  test so it doesn't drift unnoticed.

## M2 — Scene script schema  *(complete)*

Implemented in `src/landscape/schema.py` (dataclasses for the document,
primitives, relations, booleans) and `src/landscape/scene_io.py`
(`ruamel.yaml`-backed load/dump, validation, resolution ordering). Covered
by `tests/test_schema.py` and `tests/test_scene_io.py` (33 tests), exercised
against `scenes/example.yaml`, a hand-authored fixture hitting every
primitive and relation.

- [x] Define the top-level document: units, canvas/page size, scale, layer order, palette reference — `SceneDocument`
- [x] Define the object model — every object has: `id`, `type`, `material`, `layer`/z-order, transform — `SceneObject` (+ `Transform` for the object-level translate/rotate/scale; a primitive's own fields, e.g. a rect's `rotation`, are its intrinsic shape, not this)
- [x] Implement parametric primitives:
Driven by what the real scene actually contains — see `extraction/objects.md`.

  - [x] `circle` — center, radius (site circle, firepit keep-out)
  - [x] `ellipse` — center, rx, ry (the firepit is 1.013 x 0.956, not a circle)
  - [x] `rect` — origin, width, height, rotation, optional `corner_r` (hot tub 7x7 r=1, pad, deck sections)
  - [x] `polygon` — explicit vertex list
  - [x] `regular_polygon` — center, sides, size, rotation (the hexagon water-feature placeholders)
  - [x] `line` — deck and fence seam details
  - [x] `fence_line` — polyline + post spacing, post size, rail count, height
  - [x] `wavy_path` — control points + `waviness` (amplitude), `wavelength`, `seed`; closed or open. Not used by the current scene; needed for the organic bed edges to come.
  - [x] `path` / `walkway` — centerline + width (offset to a polygon happens in M3)
  - [x] `keepout` — a zone that carries a rule rather than a material (see M3b); wraps its own shape primitive + a `rule` string
- [x] **Declarative relations** — a small closed vocabulary, NOT an expression language. Flat sibling keys, e.g. `mirror_of: deck_west` + a sibling `about_x: 30`, so each one maps to one GUI control:
  - [x] `center_of: <id>` — keep-out circle centred on the firepit
  - [x] `mirror_of: <id>` + `about_x` — the left/right deck pairs
  - [x] `relative_to: <id>` + offset — deck sections positioned off the pad
  - [x] `chord_of: <id>` — the new fence's span across the sand circle
  - [x] Resolution order, and cycle detection with a readable error — `scene_io.resolution_order()`, a topological sort over relation + boolean-op dependencies; stashed on `SceneDocument.resolution_order` for M3
  - [x] Every relation maps to a simple GUI control (an id-picker plus at most two numeric siblings) — achieved by the flat-sibling-key design, not a nested payload
- [x] Reusable `definitions` + `instances` (define once, place many) — `definition: <id>` on an object pulls its primitive/material from `definitions:`
- [x] `annotation: true` objects (e.g. the 14 x 10 clearance marker) — excluded from material rendering, shown only in technical views
- [x] Boolean relationships — a bed carved out of lawn, a patio cut from decking. Declared via `boolean: {op: union|difference|intersection, targets: [...]}` on an object; validated (unknown targets, cycles) same as relations. Executing the actual geometry op is M3's job, not M2's.
- [x] Schema validation with clear, line-numbered error messages — `SchemaError` carries a `path` and 1-based `line` (via `ruamel.yaml`'s line/col tracking); verified against a real malformed YAML file, not just dict fixtures
- [x] Hand-authored example scene exercising every primitive (doubles as a test fixture) — `scenes/example.yaml`; also proves byte-identical round-trip through `load_raw`/`dump_raw`

## M3 — Geometry engine  *(complete)*

Implemented in `src/landscape/geometry.py` (`resolve_scene`, `ResolvedScene`,
`ResolvedObject`). Walks `SceneDocument.resolution_order` (from M2) so every
relation/boolean target is already resolved by the time it's needed. Covered
by `tests/test_geometry.py` (33 tests) against both small fixtures and the
full `scenes/example.yaml`.

- [x] Scene script to in-memory object graph — `SceneDocument` (M2) + `resolve_scene`'s dependency-ordered walk over it
- [x] Resolve each primitive to a shapely geometry (the "resolved scene") — `primitive_to_geometry`; circles/ellipses are polygon-approximated at 32 segments/quadrant (bumped up from shapely's default 8, needed for M3b clearance rules to reproduce real-plan distances like `deck_s`'s 5.915 ft to within a hundredth of a foot)
- [x] `wavy_path` generator: spline through control points, noise-modulated normal offset, `waviness` 0 to 1 mapped to amplitude; deterministic per `seed` — `_wavy_path_geometry`: `scipy.interpolate.splprep`/`splev` for the spline, per-sample local normal, `opensimplex.OpenSimplex(seed=...)` (an instance, not the mutating global `opensimplex.seed()`) for the offset
- [x] Offsetting/buffering for paths and fence lines — `walkway`/`fence_line` resolve via `LineString(...).buffer(width/2, cap_style="flat")`
- [x] Boolean ops, overlap resolution, and z-order compositing rules — `_apply_boolean` executes the `union`/`difference`/`intersection` declared in M2's schema; `ResolvedScene.paint_order()` gives the z-then-id painter's-algorithm order M5 will draw in. Overlap *detection* (as opposed to compositing order) is M3b's job, not this one.
- [x] Transform stack (translate/rotate/scale on objects and groups) — `_apply_transform`: scale then rotate (both about centroid) then translate, applied after any relation. No `group` object type exists yet, so "on groups" doesn't apply — nothing in M2's schema defines a group.
- [x] Bounding-box computation, auto-fit and explicit crop windows — `ResolvedScene.bounds()` and `.crop(x, y, width, height)` (clips every object to the window via `shapely` intersection, drops objects that fall entirely outside)
- [x] Determinism check — same scene + seed renders identically every time — `test_resolve_scene_is_deterministic` and `test_wavy_path_is_deterministic_per_seed` compare geometry with `equals_exact(..., tolerance=0)`

## M3b — Rule checker (DRC)  *(complete)*

Constraints warn; they never block. The designer must be free to drag
anything anywhere and be told afterwards what is wrong.

Implemented in `src/landscape/rules.py`: a fixed set of generic check
*types* (`keepout_material_exclusion`, `concentricity`, `containment`,
`no_overlap_unless_stacked`, `directional_clearance`), each driven by data
in `rules/default.yaml`. 19 tests in `tests/test_rules.py`, including an
integration run against `scenes/example.yaml` that checks exactly which
rules fire and which stay silent.

- [x] Rule engine over the resolved scene, emitting located, human-readable violations — `run_rules(scene, rules) -> list[Violation]`; `Violation.location` is a representative (x, y) point (the offending overlap's centroid where there is one) for the editor to anchor a warning to later
- [x] Starter rules — implemented as the 5 check types above, plus real instances in `rules/default.yaml` (against `scenes/example.yaml`, the schema demo fixture) **and** `rules/backyard.yaml` (against the real design, `scenes/backyard.yaml` — see M1 above for what actually fired, including one documented finding that turned out not to hold against the as-drawn geometry):
  - [x] No burnable material inside a keep-out zone — `keepout_material_exclusion`; against the real backyard scene this catches `site_circle` not being carved out around the keepout, but *not* `deck_s` — see M1's note on why the "0.085 ft inside" finding doesn't hold against the keepout as actually drawn
  - [x] Keep-out zone must be concentric with its firepit — `concentricity`; checks the geometric invariant directly (centroid distance), not just that a `center_of` relation exists, so it still catches drift in a hand-edited scene
  - [x] Keep-out zone must be contained by its parent region — `containment`
  - [x] Objects must not overlap unless explicitly stacked — `no_overlap_unless_stacked`; needed an `ignore_materials`/`exceptions` design to keep ground-cover layers (lawn, mulch) and intentionally-abutting pairs (deck-on-pad) from drowning real findings in noise
  - [x] Access clearance in front of a mechanical bay — `directional_clearance`; the check type is generic and tested, but not wired to a real mechanical-bay object since which side it's on is still an open question (see Open Questions) — exercised against the example scene's `shed` as a stand-in
- [x] Violations surface in the editor next to the offending object, not in a log — `add_violation_overlays()` in `src/landscape/editor.py`: a dashed red highlight on every object a violation names, plus a marker at its location, both carrying the violation's message as a hover tooltip; recomputed on every edit. `landscape edit scene.yaml --rules rules/backyard.yaml`. See M8 below.
- [x] Rules are data, so new ones do not need code changes — true for new *instances* of the 5 existing check types (a new entry in `rules/default.yaml`); a genuinely new *kind* of check still needs a new Python function, the same trade-off M2 made for its relation vocabulary

## M4 — Material system  *(complete)*

Implemented in `src/landscape/materials.py`, library data in
`assets/materials.yaml`. 10 tests in `tests/test_materials.py` (95 total
across the project).

- [x] Material definition schema: name, flat color, texture recipe, edge treatment — `Material` (`texture`/`edge` are free-form recipe placeholders; M6 hasn't picked its techniques yet, so nothing consumes them beyond `render_swatch` using `color`)
- [x] Material library file, separate from scenes, so palettes swap independently — `assets/materials.yaml`, loaded by `load_materials()`
- [x] Starter materials: lawn, planting bed, mulch, gravel, flagstone, concrete, deck/wood, water, stone wall, fence, mature tree/shrub canopy — all 11 present
- [x] Pastel palette definition with a rule for keeping adjacent materials distinguishable — `find_indistinguishable_pairs()`, a hue-weighted HSL distance check (same warn-don't-block spirit as M3b, just at palette-authoring time rather than scene time); caught `planting_bed`/`deck` as too close on the first pass and the palette was re-tuned until clean, so the check is proven to actually catch something, not just present
- [x] Material resolution: object to material to render parameters, with sensible fallback — `MaterialLibrary.resolve()`; unknown or `None` material ids fall back to an unmistakable magenta (`#FF00FF`) rather than crashing or rendering blank
- [x] Visual swatch picking — the designer chooses materials by appearance and name, never by hex code — `render_swatch()` gives a flat-color `PIL.Image` swatch for M8's material picker to display; the picker UI itself is M8's job

## M5 — Renderer: flat pastel mode  *(complete — the real end-to-end path now works)*

Implemented in `src/landscape/render_flat.py`. `landscape render
scenes/example.yaml --mode flat --out out/plan.png` — the exact command
this file's own example — now actually works, wired up in
`src/landscape/cli.py`. 15 new tests (10 in `tests/test_render_flat.py`,
5 updated/added in `tests/test_cli.py`); 108 tests total.

- [x] Rendering abstraction so both modes share scene traversal (backend-agnostic draw calls) — `render_flat(ctx, scene, materials, ...)` draws onto whatever `cairo.Context` it's given; `iter_paint_order_with_material()` is the shared paint-order walk M6 is expected to reuse
- [x] Fill each region with its flat pastel color — via `MaterialLibrary.resolve()` (M4)
- [x] Outline style — weight, color, whether outlines are per-material — each material's own `edge: {weight, color}` (M4); `color: null` falls back to a darkened shade of the fill, not one global stroke color
- [x] Labels/callouts and an optional legend keyed to materials — annotations (`annotation: true`) and keepout zones (a `Keepout` primitive's `.rule`) get a dashed outline + text label instead of a fill (a real bug caught by actually looking at a render: keepout zones were being flat-filled with the "missing material" fallback color before this fix, since M2's own schema says a keepout "carries a rule rather than a material"); `--legend` draws a swatch+name list of materials actually used, via the independently-tested `used_materials_in_scene()`
- [x] Vector-native output (clean SVG/PDF, no rasterization) — `render_scene_to_svg`/`render_scene_to_pdf` use `cairo.SVGSurface`/`PDFSurface` directly; `render_scene_to_png` (needed for on-screen preview and now wired into the CLI) is the one raster path, using the same `render_flat()` call over an `ImageSurface`

**Real usability bug, found by Rich actually running the CLI himself, not
by testing it in isolation:** `landscape render` printed nothing on
success — same terminal output as doing nothing at all, so a real
successful render looked indistinguishable from the command silently
failing. Fixed by printing `landscape render: wrote <path>` on success;
`tests/test_cli.py` now asserts that line appears.

## M6 — Renderer: hand-drawn pastel art mode

- [ ] Research and prototype texture techniques before committing to an approach:
  - [ ] Edge wobble — noise-perturbed boundaries so lines read as hand-drawn
  - [ ] Hatching and cross-hatching, direction varying by material
  - [ ] Stippling / dot density for gravel and mulch
  - [ ] Watercolor-style washes with soft, uneven edges and color pooling
  - [ ] Canopy rendering — scalloped/blobby tree crowns rather than plain circles
  - [ ] Water — ripple lines, edge darkening
  - [ ] Paper grain and slight color bleed as a global overlay
- [ ] Per-material texture recipe — composable generators rather than one hardcoded look
- [ ] Clip every texture to its region while letting edges overshoot slightly (that overshoot is what sells the hand-drawn look)
- [ ] Seeded randomness so a given scene reproduces exactly
- [ ] Resolution independence — textures scale with target DPI without turning to mush
- [ ] Drop shadows / soft elevation cues for structures
- [ ] Performance pass — texture generation is the likely bottleneck; profile and cache
- [ ] Background: PNG texture images (real paper/canvas photos or scans), not just a procedural "paper grain overlay" — raised alongside the M8 editing-view redesign (2026-09-22); this is squarely a high-fidelity-render concern, deliberately *not* done to the plain editing canvas, which stays flat fills + lines on purpose
- [ ] "Simulate watercolor pastel drawings" for the full render, explicitly — the "Watercolor-style washes" bullet above already covers the technique; noting Rich's own framing here since it's the north star for how this whole milestone should look and feel, not just one texture among several

## M7 — Export

- [ ] PNG export at configurable DPI with correct physical sizing
- [ ] SVG export for flat mode
- [ ] PDF export at print scale, with a scale bar and north arrow
- [ ] Embed raster fills in vector output for art mode (document the hybrid honestly)
- [ ] Batch export — multiple modes/variants from one scene in a single run

## M8 — Graphical editor  *(promoted: this is the primary interface; every item done except render-*mode* toggling, genuinely blocked on M6 not existing yet — there's only flat mode to toggle to)*

M8 is a large milestone; the items below are genuinely still a checklist,
not close to done as a whole. Landed so far in `src/landscape/editor.py`
(`landscape edit scene.yaml`): load a scene into a `QGraphicsScene` built
object-by-object (each tagged with its scene id via `setData`, since
selection/dragging need to hit-test individual objects, not a flattened
image), pan/zoom, select an object, drag it to move it, a properties panel
to change rotation/scale/material, and **Ctrl+S / File > Save saves back
to disk losslessly** — edits mutate the in-memory `SceneDocument`'s
`Transform`/`material` and are mirrored into the corresponding node of the
raw `ruamel.yaml` document, so `save_scene()` (via M2's `dump_raw`) only
changes what was actually touched, and — when `--rules` is given — live
DRC feedback: a dashed highlight + marker on every object a rule
violation names, tooltip carrying the message, recomputed on every edit
(`add_violation_overlays()`; this also closes M3b's last open item); and
File > Export…, which renders the current (edited) scene straight to
PNG/SVG/PDF via M5's `render_flat` pipeline. 32 tests in
`tests/test_editor.py`, run headless via `QT_QPA_PLATFORM=offscreen`
and checked visually with rendered screenshots before writing them.

**GUI/core separation.** The rest of the project already had zero Qt
dependency (`schema`/`scene_io`/`geometry`/`materials`/`render_flat`/`rules`
never imported PySide6, and `landscape render` never touches it either).
The one remaining seam was inside the editor itself: `EditorWindow` mixed
actual widget code with orchestration logic — load/edit/sync/save/rule-
check — that didn't need Qt at all. That's now `src/landscape/editor_session.py`
(`EditorSession`, zero PySide6 import, verified both by a source-text
check and by importing it in a fresh interpreter and checking
`sys.modules`), with `EditorWindow` reduced to a thin wrapper that reads
`session.doc`/`.resolved`/`.violations` and calls `session.set_*()`/
`.save()`. Directly reusable for M8b's planned headless/batch CLI without
pulling in Qt, and its own 11 tests in `tests/test_editor_session.py` run
without `qtbot`/`QApplication` at all. Found one real latent bug while
writing its tests: `sync_object` called `doc.get(object_id)` (which raises
for an unknown id) before checking whether a raw node even existed for
it — harmless in practice since it was only ever called with ids that had
just been selected in the UI, but a real defensive-coding gap, fixed by
checking the raw lookup first.

Real bugs found only by actually exercising the interaction, not by
reading the code:
- `QGraphicsView.ScrollHandDrag` as the default drag mode swallows every
  left-drag for panning, so plain click-drag could never reach an item to
  select or move it — fixed by making pan a space-held modifier instead.
- A classic PySide6 pitfall: a rebuilt `QGraphicsScene` with no persistent
  Python reference gets its underlying C++ object garbage-collected out
  from under the view, so every signal on it after the enclosing method
  returns silently misbehaves — fixed by holding `self._scene`.
- `setScene()` itself fires `selectionChanged` for the outgoing scene's
  deselection, which raced with and clobbered the reselect-after-rebuild
  step — fixed by capturing the selected id in a local variable before the
  rebuild rather than trusting the instance attribute mid-rebuild.
- A **segfault**, reproducible on the 18th test in the file: creating many
  `EditorWindow`/`QGraphicsScene` instances across a test run without an
  explicit teardown path left their C++ objects to Python's non-deterministic
  GC, which corrupted memory badly enough to crash unrelated code (`ruamel`,
  mid-parse, in a later test). Fixed by adding `pytest-qt` as a dev
  dependency and routing every `EditorWindow` in the test suite through
  `qtbot.addWidget()`, which owns proper Qt teardown between tests — not a
  workaround, the actual standard tool for this exact class of problem.

- [x] Decide the UI stack (see open questions) — PySide6, see the Open Questions entry above
- [x] Fast low-resolution preview render for interactive iteration — `build_graphics_scene()`; not yet "low-resolution" in any deliberate sense, just whatever Qt draws directly, which has been fast enough so far
- [~] Pan/zoom; toggle layers and render modes — pan/zoom (`SceneGraphicsView`, space-drag + wheel) and layer toggling (a "Layers" menu checkbox per `doc.layers` entry, `build_graphics_scene(..., hidden_layers=...)`) both done; render-*mode* toggling genuinely can't be finished until M6 exists — there's only flat mode to toggle to
- [x] Select, move, resize and rotate objects directly — `EditableItem` for select/move; `SelectionHandle` adds two on-canvas drag handles (resize: uniform scale about the object's centroid — `Transform.scale` is a single factor, not independent width/height; rotate: absolute angle) shown whenever exactly one object is selected. Deliberately never rebuilds the scene during or right after the drag — `_rebuild_scene()` replacing the whole `QGraphicsScene` would destroy the handle mid-event, the same class of hazard as the earlier segfault — so the drag previews with a live Qt-level item transform and commits straight to `EditorSession.set_scale`/`set_rotation` (the same calls the panel's own spinboxes make) on release; the next rebuild triggered by *anything else* regenerates the authoritative path from the committed value. Verified safe against a real rebuild (a layer toggle) happening while handles are active, and against dragging the same handle twice without an intervening rebuild (the second gesture correctly re-reads the first gesture's committed result as its baseline, not the value the handle was constructed with — this needed a real fix, not just a passing test, the first time through).

**Real usability bug, reported by Rich after actually using it, fixed 2026-09-22:** resizing a thin, wide object (a deck panel) and dragging sideways could blow its scale up hugely, and felt far more sensitive when the view was zoomed out — to the point that a deck could grow wide enough that its (unchanged, proportional) height became imperceptible at the zoom level needed to see the whole thing. Root cause was using a *ratio* of raw scene-space distances (`new_distance / starting_distance`) for resize sensitivity: Qt hands `itemChange` mouse positions already converted to scene coordinates, so the same physical drag corresponds to a larger scene-space distance the further zoomed out; and dividing by `starting_distance` amplifies the same absolute drag into a huge factor for small/thin objects. Fixed by switching to an additive, zoom-normalized delta (`SelectionHandle.RESIZE_SENSITIVITY`, `_zoom()`) with a hard per-gesture clamp (`MAX_GESTURE_FACTOR = 4.0`) — the same physical drag now produces the same scale change regardless of the object's size or the current zoom, and no single gesture can blow the scale past 4x/¼x no matter how far or fast the mouse moves. Rotation didn't need the same fix — an angle from the centroid is scale-invariant under uniform zoom.

**A second real bug found the same way, fixed 2026-09-22:** rotating (or resizing) an object right after moving it, without deselecting/reselecting in between, rotated it about its *pre-move* center — the object visibly swung to a new position instead of turning in place, exactly matching Rich's report that rotation seemed to also translate the object. Root cause: `SelectionHandle._center` was cached once at handle-construction time, but a plain move-drag deliberately never rebuilds the scene (`EditableItem`'s whole design, to avoid destroying an item mid-drag), so it never recreated the handles either — leaving them pointed at a stale center. Fixed by re-reading `_center` fresh from the target's current path at the start of every gesture, the same pattern already used to fix `_start_scale`/`_start_rotation` staleness for the "drag the same handle twice" case. Reproduced with a diagnostic script before touching any code, confirmed fixed the same way, then locked in with 3 regression tests.

**Zoom feel changed on request, 2026-09-22.** Two things: the per-scroll-tick rate dropped from 15% (`1.15`) to 5% (`SceneGraphicsView.ZOOM_PER_TICK = 1.05`) — the old rate felt too aggressive; and zoom now anchors on the selected object's center (falling back to the viewport center when nothing's selected) instead of `AnchorUnderMouse`, matching "the same origin as the rotation axis" rather than incidental mouse position. `QGraphicsView.setTransformationAnchor` only offers "under the mouse" or "view center," neither of which is "the selected object," so the anchor correction is manual: note the anchor point's viewport pixel position, scale, then adjust the scrollbars so that scene point lands back at the same pixel (`_scale_anchored_at()`). One real gotcha found while testing this, not a bug in the fix itself: right after `fitInView`, the whole scene already fits the viewport with room to spare, so the scrollbar range is genuinely `(0, 0)` — there's nowhere to scroll to, and no anchor technique (this one or the `centerOn()` alternative tried first) can possibly keep a point fixed in that state. Confirmed the fix works correctly (exact pixel match, not just "close") once the view is zoomed in enough that scrolling is actually meaningful — the practical case this was built for.

**Visual redesign, phase 1 (editing view only), started 2026-09-22, on request.** Rich wants a hand-drawn/pencil-and-pastel feel for the finished product, but is changing the *editing* canvas's look first, deliberately keeping it simple ("during editing, everything can just be basic fills and lines") before doing any visual regression test work — the real textured/watercolor look is out of scope here and belongs to M6 below. Landed in `editor.py`:
  - Every shape's outline is now a single uniform width and a dark charcoal color (`LINE_COLOR = "#2B2A28"`, "coal, like a pencil," not flat black), replacing each material's own `edge` weight/color for this view only — `render_flat` (the real renderer, and what `EditorSession.export()` calls) is untouched and still draws each material's actual edge styling.
  - Canvas background is a warm off-white (`BACKGROUND_COLOR = "#F6F1E4"`), set on both the `QGraphicsScene` (the drawing itself) and the `QGraphicsView` (so panning/zooming past the drawing's edge doesn't reveal a stark-white gap) — chosen so the existing pastel material fills read clearly against it rather than the previous plain white.
  - Tooltip and status-bar text (the only "popup message" text that exists today — `SelectionHandle`'s drag/rotate tooltips, and export/reload/violation-count status bar messages) forced dark via a small stylesheet on `EditorWindow`, so it can't flip light-on-dark under an OS dark theme.
  - Line *thickness*: asked for "a thinner 3 pixel line," but also that it "should change depending on magnification" — i.e. **not** a Qt cosmetic pen (which would hold a fixed device-pixel width forever, regardless of zoom); a plain scene-space pen width instead, which under `QGraphicsView`'s zoom transform naturally gets thicker/thinner right along with everything else as you wheel-zoom. `_line_width_for_zoom()` converts the "3 screen pixels" target into that scene-space width from the view's *current* zoom, recalculated on every scene rebuild (select, edit, undo, layer toggle, a fresh load, ...) — so thickness self-corrects back to a true ~3px baseline at each of those points, and drifts smoothly between them as the view is wheel-zoomed. `load_scene()` now rebuilds the scene a second time right after its initial `fitInView()` for exactly this reason — the first rebuild (needed to get a bounding rect to fit to) necessarily happens before the real zoom is known. Verified visually via an offscreen-rendered screenshot (background/line colors read correctly, pastel fills sit well on the new background) and by comparing screenshots before/after a rebuild at an artificially zoomed-in view (line width visibly grows with a plain zoom, then visibly snaps back down to the ~3px baseline once something rebuilds the scene) — the number itself (`LINE_WIDTH_PX = 3.0`) is a first guess, expected to get tuned.
  - **Deferred, explicitly out of scope for this pass:** a pencil-style font. Rich wants one, as long as it can ship *with* the application rather than depending on whatever's installed on the machine it runs on — that means bundling a font file (e.g. under `assets/`) and loading it via `QFontDatabase.addApplicationFont()` rather than naming a system font family. Not done yet; needs an actual font file chosen/licensed first.

**A third real bug, same family, found while checking Rich's report of lingering "weird rotational behavior" after the two fixes above — not stale YAML, there's no origin stored in the scene format at all, both the preview and the real geometry compute their pivot fresh every time, but they were computing two *different* fresh values, fixed 2026-09-22:** `SelectionHandle` pivoted its live rotate/resize preview on `path().boundingRect().center()`, but the real, committed transform in `geometry._apply_transform` pivots on `origin="centroid"` (Shapely's actual area/line centroid). For a symmetric shape (a rect, a circle) the two points coincide, which is exactly why the two earlier fixes' tests didn't catch it — but for anything asymmetric (a bent `fence_line`/`wavy_path`/`walkway`, an irregular `polygon`) they're genuinely different points. Confirmed on `garden_walkway` in `example.yaml` (a 3-point bent line): bbox center `(9.86, 12.69)` vs. true centroid `(9.43, 12.91)`. Pivoting on the wrong one meant the object visibly jumped the instant a rotate/resize gesture committed and `recompute()` re-resolved it about the real centroid instead of wherever the preview had been spinning it around. Fixed by computing the true centroid once per object from `obj.geometry.centroid` at scene-build time (`_add_material_item`, the same value `_add_annotation_item` already used for label placement), storing it on `EditableItem.centroid`, translating it alongside the path on every move-drag (so it can't go stale the same way `_center` did in the second fix above), and having `SelectionHandle` read `target.centroid` instead of the bounding box. Verified the regression tests actually catch the old bug (not just pass against the new code) by reverting `editor.py` alone and confirming they fail with the exact old/new numbers, then restored the fix.

**A fourth real bug, the most serious of the four, found by building the "legitimate GUI click and rotate/scale test" Rich asked for on 2026-09-22 — every resize/rotate test up to this point drove `SelectionHandle` via `handle.setPos(...)` + `handle.end_drag()`, which never exercises Qt's own mouse-event dispatch at all, so this class of bug had no way to get caught until an actual `QTest.mousePress`/`mouseMove`/`mouseRelease` gesture was tried:** dragging a resize/rotate handle with a *real* mouse gesture silently translated the selected object underneath it, corrupting its position at the same time the rotate/scale preview ran — the exact "the origin of a part should not change" failure Rich was worried about, confirmed for real rather than hypothetical. Root cause: `SelectionHandle` never overrode `mousePressEvent`/`mouseMoveEvent`, so dragging it ran `QGraphicsItem`'s own *default* mouse handling — which, when the scene has a selection, moves that whole selection together with whatever movable item is actually being dragged, even one (a handle) that isn't itself part of that selection. Since the target object stays selected for as long as its handles are shown, dragging a handle always dragged the selected object along with it. Reproduced with exact numbers on `shed`: a rotate-handle drag meant to spin it ~90° around its own centroid (5.5, 4.0) instead left its rotation *and* moved its centroid to roughly (8.44, 2.0); a resize-handle drag showed the identical pattern. Fixed by having `SelectionHandle` own its press/move/release handling directly (compute the drag delta from `event.scenePos()` itself and call `setPos()` explicitly, still routed through `itemChange` via `ItemSendsGeometryChanges`) rather than relying on the `QGraphicsItem` default at all. Four new tests drive the handles with genuine `QTest` mouse events end-to-end (not `setPos()`) and assert the "origin doesn't move" invariant directly; verified each one fails against the pre-fix code with the exact numbers above, and passes against the fix — and along the way, caught and fixed a mistake in the tests' own first draft (asserting `shed.pos() == (0, 0)`, which is *always* true regardless of this bug, since `EditableItem.itemChange` deliberately vetoes its own Qt-level `pos()` and tracks movement through `scene_object.transform` instead — fixed to check `transform.tx`/`ty` directly).

**A fifth real bug, same family, reported by Rich as "when I move an object, it seems to accelerate beyond the cursor off the page," fixed 2026-09-23:** the bug above (the fourth) was about handles moving the *wrong* item; this one is about the *right* item (a plain object drag, no handle involved) moving by the *wrong amount* — accelerating well past the actual mouse distance. Same underlying cause as the other three, and same reason it went uncaught until now: every existing drag test (including the four "legitimate" ones just added for the fourth bug) drives a drag with a single `setPos()`/single `mouseMove` jump, but this bug only shows up across a *second* move event, since it's a compounding bug, not a one-shot one — a real human drag naturally produces many small move events, which none of the tests up to this point ever simulated. Root cause: `EditableItem.itemChange` deliberately vetoes Qt's own `pos()` back to its frozen original value every time (see the class docstring — it tracks position via `scene_object.transform`/the path instead). Qt's *default* `mouseMoveEvent` recomputes, on every move event, `press-time pos() + (current mouse scenePos - press-time mouse scenePos)` — the *cumulative* offset since press, referenced against its own cached `pos()`. Since that `pos()` never actually advances, Qt keeps recomputing that same growing cumulative offset on every subsequent event too, and `itemChange`'s `delta = value - self.pos()` reads the *entire* cumulative amount as if it were just this event's incremental step, applying it on top of everything already applied — every single event compounds the last. Reproduced with exact numbers: a 3-unit drag over 10 small steps left `shed.transform.tx` at 16.6 instead of ~3.5, with each step's increment visibly growing (0.26, 0.61, 0.87, 1.12, ...). Fixed the same way as the third bug: `EditableItem` now owns its own `mousePressEvent`/`mouseMoveEvent` (tracking the mouse's last scene position itself and feeding `itemChange` a true incremental per-event delta) instead of relying on `QGraphicsItem`'s default — confirmed real click-to-select still works without it (that's handled at the `QGraphicsScene` level, not inside `QGraphicsItem`'s own press handler). Also explicitly verified — since Rich asked for it by name — that the fix is *consistent regardless of an object's distance from the scene origin*: the buggy cumulative-offset mechanism happened to be independent of an object's actual position (the frozen reference is always Qt's `pos() == (0, 0)`, for every object, near the origin or far from it), but that's exactly the kind of assumption worth locking in with a real test rather than trusting it by accident — `test_real_multi_step_mouse_drag_is_consistent_regardless_of_distance_from_the_origin` drags both `shed` (near the origin) and `hot_tub_pad` (far from it) by the same real mouse distance and confirms both land within the same small pixel-rounding tolerance of each other and of the intended distance. Verified both new tests fail against the pre-fix code (16.8 instead of 3.0) and pass against the fix.
- [x] Create objects from a palette of the M2 primitives — a Create menu (one action per creatable kind); `EditorSession.create_object()` adds a centered, sensibly-defaulted object to `doc`, `resolution_order`, and appends a proper raw YAML node via the new `schema.primitive_to_raw_dict()` (the inverse of `parse_primitive`, round-trip verified for every primitive kind). Deliberately excludes `keepout` — it needs a `rule` string and a nested `shape`, no control for either yet. Undoable; newly created object is auto-selected so the properties panel is immediately usable on it.
- [x] Material assignment by visual swatch — `_swatch_icon()` converts M4's `render_swatch()` (a flat PIL image) into a `QIcon` per combo entry; sorted by display name, id kept as `itemData` so the picker shows "Water" with a blue swatch while the document still stores `water`
- [x] Edit relations as simple controls (a "keep centred on firepit" checkbox, a mirror link) — one generic control cluster (relation type, target, up to two params relabeled per type) rather than four separate forms, wired to `EditorSession.set_relation()`. A relation isn't a per-object property like material/transform — it changes the dependency graph — so this required making `scene_io`'s cycle/reference validation (`validate_and_order`, renamed from a private `_validate_references`) reusable after an edit, not just at parse time. On an invalid edit (unknown target, or a real cycle — verified against `deck_east`'s actual `mirror_of: deck_west` in `example.yaml`, not a synthetic case), automatically rolls back to the pre-edit snapshot before re-raising, so a rejected relation can never leave the session in a broken state. Found one real trap while smoke-testing by hand (not a production bug): `QMessageBox.warning()` blocks forever with no running event loop and no display to click "OK" on — harmless in real usage (the event loop is always running there), but manual headless smoke-testing and automated tests both need it mocked, which the actual pytest suite already does correctly.
- [x] Live rule-checker feedback attached to the offending object — `add_violation_overlays()`; try `landscape edit scenes/backyard.yaml --rules rules/backyard.yaml --show-annotations`
- [x] **Undo/redo**, and autosave that never silently discards hand edits — `EditorSession.push_undo/undo/redo`, deep-copying `doc` and the raw `ruamel` tree (verified independently mutable, not just assumed); one snapshot per drag *gesture*, not per mouse-move pixel, via `EditableItem`'s `on_drag_start`/`on_drag_end` hooks. `autosave()` writes a `.autosave` sidecar after every edit (removed once an explicit save supersedes it) — satisfies "never silently discards hand edits" without needing a restore-on-load prompt, which stays open as a UX nicety, not the safety property itself. Found a real repo-hygiene bug while wiring this up: several existing tests loaded the real `scenes/example.yaml`/`scenes/backyard.yaml` directly and then edited them, so every test run littered the repo with `.autosave` sidecars next to the committed fixtures — fixed by having those tests load a private temp copy, plus `*.autosave` added to `.gitignore` as a second line of defense for real usage too.
- [x] Lossless round-trip: load YAML, edit, save, and a file the editor has not
      changed comes back byte-identical — `save_scene()`; verified both ways: an unchanged load-then-save reproduces the source file byte-for-byte, and an edited save touches only the edited object's `material`/`transform` (a cosmetic caveat: a rewritten `transform` switches from whatever flow/block style it had to block style, since it's written as a plain dict — acceptable since the guarantee is about *untouched* content, not about preserving formatting on a value just overwritten)
- [x] Watch-and-reload for files edited outside the editor — a `QFileSystemWatcher` on the loaded path; auto-reloads if nothing's unsaved (`EditorSession.dirty`, set by every mutating call, cleared by `load()`/`save()`), otherwise asks first via a Yes/No dialog rather than silently discarding hand edits. Distinguishes our own `save()`/`autosave()` writes from a genuine external change by comparing the file's mtime against the one recorded right after our own last write — a naive implementation would otherwise treat every save as if some other tool had just edited the file. Found a real, subtle bug while testing this, not a hypothetical: the real OS-level file-change signal is delivered asynchronously and can arrive *after* a test function returns, once `monkeypatch` has already restored the real (blocking, undismissable-in-headless-mode) `QMessageBox.question` — aborting the process. Fixed by draining pending Qt events and explicitly stopping the watch before each such test ends, confirmed stable across 5 repeated runs, not just one passing attempt.
- [x] Export straight from the editor — `EditorSession.export()` dispatches to M5's `render_scene_to_svg/pdf/png` by extension, so the editor and `landscape render` produce identical output for the same scene; File > Export… in the GUI, with a warning dialog on an unsupported extension instead of a silent failure

## M8b — CLI

- [ ] Batch/headless rendering for developer use and regression tests

## M9 — Validation and testing

**Test coverage audit (2026-09-21).** 139 tests exist across the project
(schema, scene_io, geometry, materials, render_flat, rules, cli, editor,
backyard scene). Categorized by what they actually benchmark against:
hand-derived closed-form math (geometry/rules — real ground truth, the
strongest coverage in the suite), hand-picked pixel/hex values
(render_flat/materials — real ground truth), and self-consistency checks
(scene_io round-trip, editor property get/set — these prove an invariant
holds, not that a value is externally correct, which is the right kind of
test for what they're checking but shouldn't be mistaken for more than
that).

Gaps found, most important first:
- `scenes/backyard.yaml` was hand-typed from `extraction/objects.json`;
  nothing programmatically diffs the two. Only 3 derived numbers (the
  concentricity offset, the containment overhang, the keepout clearance)
  are cross-checked against independently-documented values in
  `extraction/objects.md` — the other ~17 objects' raw coordinates have
  no automated check against their source.
- No golden-image regression test exists anywhere yet (see the M9 item
  below) — every image assertion today is a single-pixel sample or a
  format-validity check (`<svg` present, `%PDF` magic bytes), not "does
  the whole picture look right."
- No cross-platform determinism test (see the M9 item below) — the
  existing determinism tests only re-run in the same process/machine.
- ~~Editor tests never simulate a real Qt mouse/key event~~ — resolved
  2026-09-22: `QTest.keyPress`/`keyRelease` (real focus/dispatch) for the
  space-bar pan toggle, and a manually-built `QWheelEvent` sent via
  `QApplication.sendEvent()` to the view's *viewport* (where Qt actually
  delivers wheel events for a `QGraphicsView`, not the view itself) for
  zoom. 5 new tests, stable across repeated runs. Everything else in the
  editor still drives interaction the old way (`setPos()`/`setSelected()`
  through `itemChange`) — deliberately: it's reliable and fast, and nothing
  found so far needed the real dispatch path to catch a bug, unlike these
  two, which had zero coverage of any kind before.
- `relative_to`/`chord_of` aren't verified end-to-end with a numeric
  expected position the way `center_of`/`mirror_of` are; `directional_clearance`
  only exercises its "south" branch; `landscape edit`'s actual CLI
  execution path (not just its argparse wiring) never runs in a test.

- [ ] Unit tests: primitive generation, `waviness` behavior at parameter extremes, boolean ops
- [ ] Schema validation tests, including malformed scenes producing useful errors
- [ ] Golden-image regression tests for both render modes — deliberately deferred as of 2026-09-22: Rich wants to change what elements fundamentally look like in the editor view first, so baselining screenshots now would just mean re-baselining them right after. Pick this back up once that visual pass lands.
- [ ] Round-trip check: scene to render, visually verified against the source PDF plan
- [ ] Determinism test across runs and platforms
- [ ] Revisit test coverage gaps (see audit note above)

## M10 — Documentation

- [ ] `REQUIREMENTS.md` — the requirements doc the project brief calls for
- [ ] Scene script reference with every primitive and parameter
- [ ] Material authoring guide
- [ ] `README.md` — install, quickstart, CLI usage
- [ ] Worked example: the real site plan, from PDF through both render modes

---

## Suggested order of attack

Revised now that the editor is the primary interface rather than an afterthought.

1. ~~**M1** extraction~~ — done; the real geometry is in hand, 20 objects with
   roles, phases and confidence levels. **M0 setup is still outstanding** and is
   the immediate next task: there is no repo, no venv and no pinned dependencies yet.
2. **M2 + M3** schema and geometry engine, with the flat renderer (**M5**) as the
   thinnest end-to-end path. Get the real backyard on screen.
3. **M4** materials, then **M8** the editor — earlier than originally planned.
   Until the editor exists, the designer cannot participate at all, and every
   design change has to route through a developer.
4. **M3b** rule checker and **M7** export.
5. **M6** art mode last. Still the highest-risk, highest-variance work, and it
   benefits from a stable pipeline underneath it. It is also the mode the
   designer will judge the tool by, so it deserves unhurried iteration rather
   than being rushed early.

## Round-trip is a hard requirement

Every design decision from here is measured against one test: **can the editor
open a scene, change one thing, save it, and leave everything else untouched?**
Anything that breaks that — code in scene files, generated comments, reordered
keys, lost formatting — is a defect, not a trade-off.
