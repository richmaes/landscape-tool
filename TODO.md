# Landscape Rendering Tool — Task List

**Status:** M0–M5, M1, and M3b complete; M8 underway (PySide6 editor: load, pan/zoom, select, drag-move, panel-based rotate/scale/material edits, lossless save-to-disk, and live rule-checker feedback all work — the last one also closes out M3b's final open item). The editor's non-GUI logic is now factored out into `EditorSession` (`editor_session.py`, zero Qt dependency), so `EditorWindow` is a thin wrapper over it. `scenes/backyard.yaml` is now the real design (converted from `extraction/objects.json`), not just the `scenes/example.yaml` schema fixture — see M1 for a real finding this surfaced (the documented `deck_intrudes_on_keepout` doesn't actually hold against the keepout as drawn). Still open in M8: create-objects, swatch-based material picking, relation editing, undo/redo, watch-reload, export-from-editor. M7 export is untouched.
**Last updated:** 2026-09-21

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

## M7 — Export

- [ ] PNG export at configurable DPI with correct physical sizing
- [ ] SVG export for flat mode
- [ ] PDF export at print scale, with a scale bar and north arrow
- [ ] Embed raster fills in vector output for art mode (document the hybrid honestly)
- [ ] Batch export — multiple modes/variants from one scene in a single run

## M8 — Graphical editor  *(promoted: this is the primary interface; first slice landed, most of the milestone still ahead)*

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
(`add_violation_overlays()`; this also closes M3b's last open item). 29
tests in `tests/test_editor.py`, run headless via `QT_QPA_PLATFORM=offscreen`
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
- [ ] Pan/zoom; toggle layers and render modes — pan/zoom done (`SceneGraphicsView`, space-drag + wheel); layer/mode toggling not started (there's only one render mode, flat, to toggle to yet)
- [~] Select, move, resize and rotate objects directly — select and drag-move done (`EditableItem`); resize/rotate work but only via the properties panel's numeric fields, not a drag handle on the item itself
- [ ] Create objects from a palette of the M2 primitives
- [ ] Material assignment by visual swatch — the properties panel's material field is a name-only combo box; M4's `render_swatch()` exists but isn't wired in here yet
- [ ] Edit relations as simple controls (a "keep centred on firepit" checkbox, a mirror link)
- [x] Live rule-checker feedback attached to the offending object — `add_violation_overlays()`; try `landscape edit scenes/backyard.yaml --rules rules/backyard.yaml --show-annotations`
- [ ] **Undo/redo**, and autosave that never silently discards hand edits — save is manual (Ctrl+S) only; no undo stack yet
- [x] Lossless round-trip: load YAML, edit, save, and a file the editor has not
      changed comes back byte-identical — `save_scene()`; verified both ways: an unchanged load-then-save reproduces the source file byte-for-byte, and an edited save touches only the edited object's `material`/`transform` (a cosmetic caveat: a rewritten `transform` switches from whatever flow/block style it had to block style, since it's written as a plain dict — acceptable since the guarantee is about *untouched* content, not about preserving formatting on a value just overwritten)
- [ ] Watch-and-reload for files edited outside the editor
- [ ] Export straight from the editor

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
- Editor tests never simulate a real Qt mouse/key event (`wheelEvent`
  zoom, space-bar pan) — every interaction test calls the underlying API
  directly (`setPos()`, `setSelected()`).
- `relative_to`/`chord_of` aren't verified end-to-end with a numeric
  expected position the way `center_of`/`mirror_of` are; `directional_clearance`
  only exercises its "south" branch; `landscape edit`'s actual CLI
  execution path (not just its argparse wiring) never runs in a test.

- [ ] Unit tests: primitive generation, `waviness` behavior at parameter extremes, boolean ops
- [ ] Schema validation tests, including malformed scenes producing useful errors
- [ ] Golden-image regression tests for both render modes
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
