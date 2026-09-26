# Landscape Rendering Tool — Task List

**Status:** M0–M5, M1, M3b, and (bar one genuinely-blocked item) M8 all complete. The editor now covers its entire checklist: load, pan/zoom, select/move/resize/rotate (drag directly or via the panel), swatch-based material picking, relation editing, create-objects-from-a-palette, lossless save (toolbar Save button, unsaved-changes indicator, save/discard prompt on close), undo/redo, autosave, layer toggling, watch-and-reload, live rule-checker feedback, and export-to-PNG/SVG/PDF. Dashed annotation/keepout objects are selectable along their outline, and Tab on the canvas cycles through layered objects under the pointer. A run of real mouse-interaction bugs in move/resize/rotate was found and fixed 2026-09-22 to 09-24 (see the M8 notes); two follow-ups are parked in the new **Feature backlog** — see the M8 section for what's honestly partial (resize/rotate is uniform-scale/absolute-rotation only) versus fully done. Its non-GUI logic lives in `EditorSession` (`editor_session.py`, zero Qt dependency), with `EditorWindow` as a thin wrapper. `scenes/backyard.yaml` is the real design (converted from `extraction/objects.json`), not just the `scenes/example.yaml` schema fixture — see M1 for a real finding this surfaced (the documented `deck_intrudes_on_keepout` doesn't actually hold against the keepout as drawn). M7 export is done (2026-09-24) bar embedding art-mode raster fills, which needs M6: real DPI for PNG, SVG sized in points, scale bar and north arrow, an Export options dialog in the editor, and batch export recipes (`landscape export`), which also cover M8b. **M6 art mode is built (2026-09-24):** a watercolor-and-pencil renderer (`render_art.py`; diffuse or layered wash, per-material pencil textures, tree canopies, shadows, paper grain or a paper scan), in every export path (`--mode art`, recipes, the editor's Export dialog) and as a **Design / Art preview** switch in the editor — which also completes M8. The look itself stays open to iteration by eye. Since then (2026-09-25) the editor gained an editable **Size** row (type a width or height to reshape an object non-uniformly), a movable **legend box** and **scale indicator** (drawn in every mode), **paver** materials (5 colors x herringbone 45°/90°, running bond, basketweave, sailor border) and **deck wood colors**; the backyard gained its existing light grey herringbone patio and sand-circle border (page grown to 36 ft); and three real bugs were fixed — dragged objects snapping back on switching views, trackpad zoom lagging and backing up a step, and the canvas sliding sideways on selection. Remaining open work: M9 (broader validation, including the deferred golden-image tests), M10 (docs), **M11 (3D view — requirements captured, `docs/3d-view-requirements.md`)**, and the feature backlog.
**Last updated:** 2026-09-25

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

**Hot tub is now a 3D model (2026-09-25, Rich).** `hot_tub` changed from a plain rounded rect to a `model` object using the generated `Simple Hot Tub/simple_hot_tub.obj` (wood plank exterior, off-white interior; `tools/make_hot_tub_model.py`), sized 7 x 7 ft, 3 ft tall on the 0.33 ft pad. Same id (so the rules still refer to it), same material (water — the plan and legend still show it as the tub), layer, paint order and position (centre unchanged at (17.966, 23.615), Rich's move north kept). On the plan its footprint is a square; the rounded corners are in the 3D model. On a machine without the model file the 3D view shows a 7 x 7 x 3 ft placeholder box.

**Rich's layout edits in the editor (committed 2026-09-25).** Measured against the previous commit, in the 36 ft page's coordinates: the whole hot tub assembly (tub, all seven deck sections and their seams, the dashed ground-cover box) moved north by about 1.1–1.75 ft, and the pad's height went from 9 to 8.5 ft (81 → 76.5 sq ft); the back (property-division) fence moved about 0.7 ft north; and the firepit and its keep-out moved together from about (14.8, 11.7) to (12.0, 13.9). The rule checker afterwards reports only the two expected notes: the sand inside the keep-out (no non-burnable fill chosen yet), and the keep-out 0.066 ft off the firepit's centre (moved separately — a `center_of: firepit` relation would lock them together). The existing vinyl fence is unchanged.

**Existing brick patio and sand-circle border added; page grown to 36 x 36 ft (2026-09-25, Rich).** `brick_patio`: 36 x 36 ft of **light grey** pavers in a **45° herringbone**, centred on the sand circle, with the circle and its border cut out of it (`boolean: difference`). `sand_circle_border`: one **sailor course** (bricks laid lengthwise along the curve) — a 4 in ring, `center_of: site_circle` so it follows the circle. Pavers assumed standard 8 x 4 in (`brick:` in the material). The page grew from 24 to 36 ft to hold it, and every existing object moved +6 ft in x and y to stay centred (verified: all 20 shifted by exactly (6, 6), nothing else changed); at 1/2 in = 1 ft the plan now prints 18 in square. `rules/backyard.yaml` treats the paver colors as ground surfaces in the overlap rule, like the sand — otherwise every fence built across the patio or border was flagged. Worth a look: the existing vinyl fence (y = 30) is still tangent to the sand circle, so it now runs along the 4 in border ring; and the patio extends 6 ft beyond that fence, and the fence still spans only 6..30 ft of the new 36 ft width (its x extent was always a placeholder).

**Firepit keep-out: recentred on the firepit, radius ~4.73 ft (2026-09-24, Rich, in the editor).** Moved from its drawn centre (8.588, 4.965) to (8.785, 5.755) — 0.04 ft from the firepit's centre — and scaled 0.789x, from 6.0 ft to ~4.73 ft radius; the smaller radius is intentional. Stored as a `transform` on `firepit_keepout` in `scenes/backyard.yaml`, not by editing its `shape`. This resolves three documented findings at once (see `extraction/objects.md`): it's now concentric with the firepit, sits wholly inside the site circle (no overhang), and `deck_s` clears it by 1.151 ft. Still open: the keep-out isn't *locked* to the firepit — a `center_of: firepit` relation would keep it there if the firepit moves. **Tests:** the flaw-checking tests pin the *original* design, so they now load a frozen copy, `tests/fixtures/backyard_original.yaml`; the live `scenes/backyard.yaml` only gets design-independent checks (loads, resolves, rules run) and is free to change.

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
- [x] ~~**Elevation / 3D**~~ — resolved 2026-09-25: now in scope. Rich wants a 3D view from a camera placed in the plan, which brings heights for the elements. Requirements in `docs/3d-view-requirements.md` (with its own open questions: default heights, camera controls, style first, renderer technology, what's beyond the page); work items are **M11** below.
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
  **Decided 2026-09-24:** recentred *and* shrunk to ~4.73 ft, so the
  0.085 ft conflict never materialises — `deck_s` clears it by 1.151 ft
  (see the Decision record).
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

## M6 — Renderer: hand-drawn pastel art mode  *(built; the look stays open to iteration by eye)*

`src/landscape/render_art.py` — a raster watercolor-and-pencil pipeline (paper → shadows → per-object washes → pencil textures → pencil outlines → paper grain), composited with a *multiply* blend like transparent pigment. Lower washes are *lifted* under an upper object (as a painter leaves an area unpainted) — without that, overlapping washes stacked into mud (the first prototype's biggest flaw). Unassigned materials are left as paper with a pencil outline rather than flat mode's magenta fallback.

- [x] Research and prototype texture techniques before committing to an approach — two wash techniques prototyped on the real backyard and compared at 300 DPI (`out/m6-prototypes/comparison.png`): **A, diffuse** (wobbled masks, soft blur, pigment pooling at the rim, granulation — reads as watercolor) and **B, layered** (Tyler Hobbs-style recursive polygon deformation, many hard translucent glazes — crisper, more marker/gouache). Rich's call (2026-09-24): keep both, `ArtStyle.wash = "diffuse"` (default) or `"layered"`; lighter pencil work (`ArtStyle.pencil`, default 0.65).
  - [x] Edge wobble — noise-perturbed boundaries so lines read as hand-drawn (`_wobble`: densify, then push vertices along a smooth seeded sinusoid field; rings re-closed explicitly — vectorised maths gave a ring's identical endpoints last-bit differences, which GEOS rejects)
  - [x] Hatching and cross-hatching, direction varying by material — `texture: {style: hatch, direction, spacing, cross: true}`
  - [x] Stippling / dot density for gravel and mulch — `texture: {style: stipple, density}`
  - [x] Watercolor-style washes with soft, uneven edges and color pooling
  - [x] Canopy rendering — scalloped/blobby tree crowns rather than plain circles — `texture: {style: scallop}` (`tree_canopy`): overlapping circles just inside the outline unioned with the core, bump size scaled to the crown, plus a few pencil leaf-clump arcs; bump spacing picked by eye from three candidates
  - [x] Water — ripple lines, edge darkening — `texture: {style: ripple}` plus the wash's rim pooling
  - [x] Paper grain and slight color bleed as a global overlay — procedural (two noise scales); bleed comes from the washes' soft edges
- [x] Per-material texture recipe — composable generators rather than one hardcoded look — `texture:` in `assets/materials.yaml` is now consumed (`hatch | stipple | ripple | none`)
- [x] Clip every texture to its region while letting edges overshoot slightly (that overshoot is what sells the hand-drawn look) — hatching clipped to the region grown by 0.06 ft
- [x] Seeded randomness so a given scene reproduces exactly — `ArtStyle.seed`; byte-identical re-renders tested
- [x] Resolution independence — textures scale with target DPI without turning to mush — every size in feet or inches; a 2x-DPI render downsampled matches the 1x one (tested)
- [x] Drop shadows / soft elevation cues for structures — objects on `ArtStyle.shadow_layers` (default `structures`) cast a soft offset shadow
- [x] Performance pass — texture generation is the likely bottleneck; profile and cache — profiled: 94% of a 300 DPI render was Gaussian blurs, half of it building the large soft noise fields at full resolution. Wide blurs and smooth noise now run on a coarse grid and are scaled up (`_blur`, `_cloud`; tested to match a true Gaussian within 0.03): backyard at 300 DPI **34 s → 4.5 s** (diffuse) / 2.9 s (layered); 150 DPI ~1 s; 60 DPI 0.2 s. Bonus: the coarse noise grid is sized in real units, so the same seed now gives the same wash pattern at every DPI. Caching is for the editor preview (next item).
- [x] Background: PNG texture images (real paper/canvas photos or scans), not just a procedural "paper grain overlay" — raised alongside the M8 editing-view redesign (2026-09-22); this is squarely a high-fidelity-render concern, deliberately *not* done to the plain editing canvas, which stays flat fills + lines on purpose. Rich (2026-09-24): procedural for now, with a style setting that accepts a paper image whenever he has scans. **Support done:** `ArtStyle(paper_image=path, paper_image_width_in=6.0)` tiles the scan at its true physical size at any DPI, replaces the procedural grain, and lifted areas restore the scan's own texture. Tested with a generated stand-in; no real scan in the repo yet.
- [~] "Simulate watercolor pastel drawings" for the full render, explicitly — the north star; the diffuse wash is the closest so far. Expect iteration by eye.
- [x] Art mode in exports — `landscape render --mode art [--wash diffuse|layered] [--paper-image scan.png]`, recipes (`mode: art`, `wash:`, `paper_image:`), and the editor's Export dialog (a Style choice plus wash). All three now dispatch through one module, `render.py` (`render_to_file`, `check_output`, `takes_dpi`), replacing three separate extension→renderer tables. For art, `dpi` is the painting's resolution in every format (default 200); `exports/backyard.yaml` now also writes `out/backyard-art.pdf`.
- [x] Editor **Design / Art preview** toggle (Rich, 2026-09-24) — toolbar buttons **Design | Art preview**, also View menu (Ctrl+1 / Ctrl+2). The preview hides every design item and lays the painting over the page: read-only (selection cleared, nothing clickable; the status bar says so). Rendered at about screen resolution for the current zoom (30–200 DPI), re-rendered sharper ~250 ms after a zoom-in settles, and cached by `EditorSession.revision` + hidden layers + annotations — toggling back and forth, or undoing to an already-painted state, costs nothing. Undo/redo/layer toggles while previewing re-paint and stay in preview; hidden layers are left out of the painting.

## M7 — Export  *(complete)*

- [x] PNG export at configurable DPI with correct physical sizing — `render_scene_to_png(..., dpi=)` / `landscape render --dpi N` (replacing the old `dpi_scale` multiplier; default 72 = the old output, one pixel per point). The print size is the scene's own scale — 36 pt/ft at 72 pt/in, so the 24 ft backyard is a 12 in square, the source PDF's 1/2 in = 1 ft — and the DPI is written into the PNG's pHYs metadata (via Pillow; cairo can't) so it actually prints at that size instead of whatever DPI an app assumes. Also in the editor's File > Export options dialog.
- [x] SVG export for flat mode — existed since M5 (`render_scene_to_svg`), but checking it for M7 found a real sizing bug: cairo wrote a unitless `width="864"`, which SVG reads as CSS pixels (96/in), so the 12 in drawing printed/imported at 9 in. Now sized in points (`SVGSurface.set_document_unit(PT)` → `width="864pt"`), matching the PDF and the PNG's recorded DPI. Verified vector-only: no embedded raster data (cairo's zero-size `<image>` mask placeholders carry no pixels).
- [x] PDF export at print scale, with a scale bar and north arrow — the PDF was already at print scale (1 ft = 36 pt, 12 in square). `scale_bar=`/`north_arrow=`/`north_deg=` on all three exporters (`landscape render --scale-bar --north-arrow --north-angle DEG`), off by default. They go in a 1 in strip *below* the drawing, since the drawing fills its page edge to edge and no corner is reliably free; the drawing stays at exact scale and is now clipped to its own area (it had relied on the page edge — with a strip below, the site circle's outline and the original design's overhanging keep-out spilled into it). Scale bar: a round length about a quarter of the page width (5 ft for the backyard), alternating segments, plus the stated print scale (`1/2 in = 1 ft (1:24)`). North arrow assumes page-up is north unless `north_deg` says otherwise — still an open question for the real site. Pixel-verified that the bar is physically the length it claims. Also in the editor's File > Export options dialog.
- [x] Embed raster fills in vector output for art mode (document the hybrid honestly) — art-mode PDF/SVG embed the painting as one image at the drawing's true size (`render_art._art_page`); the scale bar, north arrow and legend stay vector (real text in the PDF). Documented in `render_art.py`'s export section: the washes, granulation and paper grain have no vector equivalent, so an art PDF is a raster painting in a vector page, and its sharpness is set by `dpi`.
- [x] Batch export — multiple modes/variants from one scene in a single run — **export recipes**: a YAML file listing outputs (each with its own `dpi`, `legend`, `annotations`, `scale_bar`, `north_arrow`, `north_angle`, `mode`), optional shared `defaults`, run with `landscape export <recipe>` (`export_recipe.py`). Paths are relative to the recipe file, so it runs from anywhere; the whole recipe is validated (with file/line errors) before anything is written. `mode: art` is accepted by the schema but errors until M6 exists. Example: `exports/backyard.yaml` (PDF plan with scale bar and north arrow, 150 DPI PNG, technical SVG with annotations → `out/`).

## M8 — Graphical editor  *(promoted: this is the primary interface; complete)*

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
- [x] Pan/zoom; toggle layers and render modes — pan/zoom (`SceneGraphicsView`, space-drag + wheel) and layer toggling (a "Layers" menu checkbox per `doc.layers` entry, `build_graphics_scene(..., hidden_layers=...)`); render-mode toggling done with M6's **Design / Art preview** switch (2026-09-24)
- [x] Select, move, resize and rotate objects directly — `EditableItem` for select/move; `SelectionHandle` adds two on-canvas drag handles (resize: uniform scale about the object's centroid — `Transform.scale` is a single factor, not independent width/height; rotate: absolute angle) shown whenever exactly one object is selected. Deliberately never rebuilds the scene during or right after the drag — `_rebuild_scene()` replacing the whole `QGraphicsScene` would destroy the handle mid-event, the same class of hazard as the earlier segfault — so the drag previews with a live Qt-level item transform and commits straight to `EditorSession.set_scale`/`set_rotation` (the same calls the panel's own spinboxes make) on release; the next rebuild triggered by *anything else* regenerates the authoritative path from the committed value. Verified safe against a real rebuild (a layer toggle) happening while handles are active, and against dragging the same handle twice without an intervening rebuild (the second gesture correctly re-reads the first gesture's committed result as its baseline, not the value the handle was constructed with — this needed a real fix, not just a passing test, the first time through).

**Real usability bug, reported by Rich after actually using it, fixed 2026-09-22:** resizing a thin, wide object (a deck panel) and dragging sideways could blow its scale up hugely, and felt far more sensitive when the view was zoomed out — to the point that a deck could grow wide enough that its (unchanged, proportional) height became imperceptible at the zoom level needed to see the whole thing. Root cause was using a *ratio* of raw scene-space distances (`new_distance / starting_distance`) for resize sensitivity: Qt hands `itemChange` mouse positions already converted to scene coordinates, so the same physical drag corresponds to a larger scene-space distance the further zoomed out; and dividing by `starting_distance` amplifies the same absolute drag into a huge factor for small/thin objects. Fixed by switching to an additive, zoom-normalized delta (`SelectionHandle.RESIZE_SENSITIVITY`, `_zoom()`) with a hard per-gesture clamp (`MAX_GESTURE_FACTOR = 4.0`) — the same physical drag now produces the same scale change regardless of the object's size or the current zoom, and no single gesture can blow the scale past 4x/¼x no matter how far or fast the mouse moves. Rotation didn't need the same fix — an angle from the centroid is scale-invariant under uniform zoom.

**A second real bug found the same way, fixed 2026-09-22:** rotating (or resizing) an object right after moving it, without deselecting/reselecting in between, rotated it about its *pre-move* center — the object visibly swung to a new position instead of turning in place, exactly matching Rich's report that rotation seemed to also translate the object. Root cause: `SelectionHandle._center` was cached once at handle-construction time, but a plain move-drag deliberately never rebuilds the scene (`EditableItem`'s whole design, to avoid destroying an item mid-drag), so it never recreated the handles either — leaving them pointed at a stale center. Fixed by re-reading `_center` fresh from the target's current path at the start of every gesture, the same pattern already used to fix `_start_scale`/`_start_rotation` staleness for the "drag the same handle twice" case. Reproduced with a diagnostic script before touching any code, confirmed fixed the same way, then locked in with 3 regression tests.

**Zoom feel changed on request, 2026-09-22.** Two things: the per-scroll-tick rate dropped from 15% (`1.15`) to 5% (`SceneGraphicsView.ZOOM_PER_TICK = 1.05`) — the old rate felt too aggressive; and zoom now anchors on the selected object's center (falling back to the viewport center when nothing's selected) instead of `AnchorUnderMouse`, matching "the same origin as the rotation axis" rather than incidental mouse position. `QGraphicsView.setTransformationAnchor` only offers "under the mouse" or "view center," neither of which is "the selected object," so the anchor correction is manual: note the anchor point's viewport pixel position, scale, then adjust the scrollbars so that scene point lands back at the same pixel (`_scale_anchored_at()`). One real gotcha found while testing this, not a bug in the fix itself: right after `fitInView`, the whole scene already fits the viewport with room to spare, so the scrollbar range is genuinely `(0, 0)` — there's nowhere to scroll to, and no anchor technique (this one or the `centerOn()` alternative tried first) can possibly keep a point fixed in that state. Confirmed the fix works correctly (exact pixel match, not just "close") once the view is zoomed in enough that scrolling is actually meaningful — the practical case this was built for.

**Zoom simplified again, on request, 2026-09-23 — Rich: "zoom out seems to scale wildly and then recenter... keep it simple for now.":** the anchor-on-selected-object behavior from the note above, only a day old, turned out to be part of the problem rather than a refinement — the anchor point would silently jump between "the viewport center" and "some object's center" the instant something got selected or deselected mid-session, with no visual continuity between the two, which reads exactly like "scaled wildly and then recentered" even though each individual zoom tick was, on its own, anchored correctly. Separately, the manual scrollbar correction (`_scale_anchored_at()`) turned out to mostly be a no-op in practice: `QGraphicsView`'s *implicit* scene rect (this app never calls `setSceneRect()`) auto-expands to always include the current viewport, so the scrollbar range was `(0, 0)` almost all the time — before or after zooming, selected or not — leaving nothing for that correction to actually adjust. Simplified to always anchor on the viewport center ("the center of the image"), for both zoom in and out, via Qt's own built-in `AnchorViewCenter` — Qt's well-tested handling of exactly this case, including the "scrollbar range is (0, 0)" edge case the hand-rolled version admitted it couldn't handle, so it replaces that code outright rather than patching it. Per-object zoom-following (matching the rotation axis the resize/rotate handles use) is explicitly deferred as "fancier zoom" for later, per Rich's own framing. Verified with a real 40-tick zoom-out sequence crossing the "already fits the viewport" threshold from a fresh load: the viewport-center scene point drifts by sub-unit amounts per tick (worst observed: ~0.5 scene units, pixel-quantization noise, not a jump) rather than anything resembling "wild." Also verified the new `test_zoom_anchor_stays_the_viewport_center_even_with_an_object_selected` regression test actually catches the old behavior: reverting `editor.py` alone reproduces an 88px jump the instant `shed` is selected before zooming, versus ≤1px with the fix.

**Visual redesign, phase 1 (editing view only), started 2026-09-22, on request.** Rich wants a hand-drawn/pencil-and-pastel feel for the finished product, but is changing the *editing* canvas's look first, deliberately keeping it simple ("during editing, everything can just be basic fills and lines") before doing any visual regression test work — the real textured/watercolor look is out of scope here and belongs to M6 below. Landed in `editor.py`:
  - Every shape's outline is now a single uniform width and a dark charcoal color (`LINE_COLOR = "#2B2A28"`, "coal, like a pencil," not flat black), replacing each material's own `edge` weight/color for this view only — `render_flat` (the real renderer, and what `EditorSession.export()` calls) is untouched and still draws each material's actual edge styling.
  - Canvas background is a warm off-white (`BACKGROUND_COLOR = "#F6F1E4"`), set on both the `QGraphicsScene` (the drawing itself) and the `QGraphicsView` (so panning/zooming past the drawing's edge doesn't reveal a stark-white gap) — chosen so the existing pastel material fills read clearly against it rather than the previous plain white.
  - Tooltip and status-bar text (the only "popup message" text that exists today — `SelectionHandle`'s drag/rotate tooltips, and export/reload/violation-count status bar messages) forced dark via a small stylesheet on `EditorWindow`, so it can't flip light-on-dark under an OS dark theme.
  - Line *thickness*: asked for "a thinner 3 pixel line," but also that it "should change depending on magnification" — i.e. **not** a Qt cosmetic pen (which would hold a fixed device-pixel width forever, regardless of zoom); a plain scene-space pen width instead, which under `QGraphicsView`'s zoom transform naturally gets thicker/thinner right along with everything else as you wheel-zoom. `_line_width_for_zoom()` converts the "3 screen pixels" target into that scene-space width from the view's *current* zoom, recalculated on every scene rebuild (select, edit, undo, layer toggle, a fresh load, ...) — so thickness self-corrects back to a true ~3px baseline at each of those points, and drifts smoothly between them as the view is wheel-zoomed. `load_scene()` now rebuilds the scene a second time right after its initial `fitInView()` for exactly this reason — the first rebuild (needed to get a bounding rect to fit to) necessarily happens before the real zoom is known. Verified visually via an offscreen-rendered screenshot (background/line colors read correctly, pastel fills sit well on the new background) and by comparing screenshots before/after a rebuild at an artificially zoomed-in view (line width visibly grows with a plain zoom, then visibly snaps back down to the ~3px baseline once something rebuilds the scene) — the number itself (`LINE_WIDTH_PX = 3.0`) is a first guess, expected to get tuned.
  - **Deferred, explicitly out of scope for this pass:** a pencil-style font. Rich wants one, as long as it can ship *with* the application rather than depending on whatever's installed on the machine it runs on — that means bundling a font file (e.g. under `assets/`) and loading it via `QFontDatabase.addApplicationFont()` rather than naming a system font family. Not done yet; needs an actual font file chosen/licensed first.

**A third real bug, same family, found while checking Rich's report of lingering "weird rotational behavior" after the two fixes above — not stale YAML, there's no origin stored in the scene format at all, both the preview and the real geometry compute their pivot fresh every time, but they were computing two *different* fresh values, fixed 2026-09-22:** `SelectionHandle` pivoted its live rotate/resize preview on `path().boundingRect().center()`, but the real, committed transform in `geometry._apply_transform` pivots on `origin="centroid"` (Shapely's actual area/line centroid). For a symmetric shape (a rect, a circle) the two points coincide, which is exactly why the two earlier fixes' tests didn't catch it — but for anything asymmetric (a bent `fence_line`/`wavy_path`/`walkway`, an irregular `polygon`) they're genuinely different points. Confirmed on `garden_walkway` in `example.yaml` (a 3-point bent line): bbox center `(9.86, 12.69)` vs. true centroid `(9.43, 12.91)`. Pivoting on the wrong one meant the object visibly jumped the instant a rotate/resize gesture committed and `recompute()` re-resolved it about the real centroid instead of wherever the preview had been spinning it around. Fixed by computing the true centroid once per object from `obj.geometry.centroid` at scene-build time (`_add_material_item`, the same value `_add_annotation_item` already used for label placement), storing it on `EditableItem.centroid`, translating it alongside the path on every move-drag (so it can't go stale the same way `_center` did in the second fix above), and having `SelectionHandle` read `target.centroid` instead of the bounding box. Verified the regression tests actually catch the old bug (not just pass against the new code) by reverting `editor.py` alone and confirming they fail with the exact old/new numbers, then restored the fix.

**A fourth real bug, the most serious of the four, found by building the "legitimate GUI click and rotate/scale test" Rich asked for on 2026-09-22 — every resize/rotate test up to this point drove `SelectionHandle` via `handle.setPos(...)` + `handle.end_drag()`, which never exercises Qt's own mouse-event dispatch at all, so this class of bug had no way to get caught until an actual `QTest.mousePress`/`mouseMove`/`mouseRelease` gesture was tried:** dragging a resize/rotate handle with a *real* mouse gesture silently translated the selected object underneath it, corrupting its position at the same time the rotate/scale preview ran — the exact "the origin of a part should not change" failure Rich was worried about, confirmed for real rather than hypothetical. Root cause: `SelectionHandle` never overrode `mousePressEvent`/`mouseMoveEvent`, so dragging it ran `QGraphicsItem`'s own *default* mouse handling — which, when the scene has a selection, moves that whole selection together with whatever movable item is actually being dragged, even one (a handle) that isn't itself part of that selection. Since the target object stays selected for as long as its handles are shown, dragging a handle always dragged the selected object along with it. Reproduced with exact numbers on `shed`: a rotate-handle drag meant to spin it ~90° around its own centroid (5.5, 4.0) instead left its rotation *and* moved its centroid to roughly (8.44, 2.0); a resize-handle drag showed the identical pattern. Fixed by having `SelectionHandle` own its press/move/release handling directly (compute the drag delta from `event.scenePos()` itself and call `setPos()` explicitly, still routed through `itemChange` via `ItemSendsGeometryChanges`) rather than relying on the `QGraphicsItem` default at all. Four new tests drive the handles with genuine `QTest` mouse events end-to-end (not `setPos()`) and assert the "origin doesn't move" invariant directly; verified each one fails against the pre-fix code with the exact numbers above, and passes against the fix — and along the way, caught and fixed a mistake in the tests' own first draft (asserting `shed.pos() == (0, 0)`, which is *always* true regardless of this bug, since `EditableItem.itemChange` deliberately vetoes its own Qt-level `pos()` and tracks movement through `scene_object.transform` instead — fixed to check `transform.tx`/`ty` directly).

**A fifth real bug, same family, reported by Rich as "when I move an object, it seems to accelerate beyond the cursor off the page," fixed 2026-09-23:** the bug above (the fourth) was about handles moving the *wrong* item; this one is about the *right* item (a plain object drag, no handle involved) moving by the *wrong amount* — accelerating well past the actual mouse distance. Same underlying cause as the other three, and same reason it went uncaught until now: every existing drag test (including the four "legitimate" ones just added for the fourth bug) drives a drag with a single `setPos()`/single `mouseMove` jump, but this bug only shows up across a *second* move event, since it's a compounding bug, not a one-shot one — a real human drag naturally produces many small move events, which none of the tests up to this point ever simulated. Root cause: `EditableItem.itemChange` deliberately vetoes Qt's own `pos()` back to its frozen original value every time (see the class docstring — it tracks position via `scene_object.transform`/the path instead). Qt's *default* `mouseMoveEvent` recomputes, on every move event, `press-time pos() + (current mouse scenePos - press-time mouse scenePos)` — the *cumulative* offset since press, referenced against its own cached `pos()`. Since that `pos()` never actually advances, Qt keeps recomputing that same growing cumulative offset on every subsequent event too, and `itemChange`'s `delta = value - self.pos()` reads the *entire* cumulative amount as if it were just this event's incremental step, applying it on top of everything already applied — every single event compounds the last. Reproduced with exact numbers: a 3-unit drag over 10 small steps left `shed.transform.tx` at 16.6 instead of ~3.5, with each step's increment visibly growing (0.26, 0.61, 0.87, 1.12, ...). Fixed the same way as the third bug: `EditableItem` now owns its own `mousePressEvent`/`mouseMoveEvent` (tracking the mouse's last scene position itself and feeding `itemChange` a true incremental per-event delta) instead of relying on `QGraphicsItem`'s default — confirmed real click-to-select still works without it (that's handled at the `QGraphicsScene` level, not inside `QGraphicsItem`'s own press handler). Also explicitly verified — since Rich asked for it by name — that the fix is *consistent regardless of an object's distance from the scene origin*: the buggy cumulative-offset mechanism happened to be independent of an object's actual position (the frozen reference is always Qt's `pos() == (0, 0)`, for every object, near the origin or far from it), but that's exactly the kind of assumption worth locking in with a real test rather than trusting it by accident — `test_real_multi_step_mouse_drag_is_consistent_regardless_of_distance_from_the_origin` drags both `shed` (near the origin) and `hot_tub_pad` (far from it) by the same real mouse distance and confirms both land within the same small pixel-rounding tolerance of each other and of the intended distance. Verified both new tests fail against the pre-fix code (16.8 instead of 3.0) and pass against the fix.

**Handles drifting off the object after a resize/rotate, plus a mirrored-rotation bug found alongside it, fixed 2026-09-23 — Rich: "scaling or rotating an object causes their handles to move off to a location away from the object.":** a handle commit deliberately never rebuilds the scene (see the fourth bug above), so nothing ever put the handles back: the dragged handle stayed wherever the mouse let go, and the other stayed on the pre-gesture bounding box. Fixed by `EditorWindow._settle_handle_gesture()`, run right after each handle commit: it updates just the one selected item in place (path regenerated from the freshly recomputed geometry, centroid refreshed, the Qt-level preview rotation/scale cleared back to identity) and re-places both handles on its new bounding box via `SelectionHandle.place_at()`, which moves a handle without `itemChange` mistaking it for the start of a new gesture. Clearing the preview transform also fixes a related snap: a second gesture used to *overwrite* the first gesture's leftover preview rotation instead of building on it. Doing this surfaced a real rotation bug that a rebuild would otherwise have hidden until later: the preview's angle is measured in Qt's y-down coordinates (positive = clockwise on screen), but `transform.rotation` feeds Shapely in y-up coordinates (positive = counter-clockwise), and the commit added the delta unchanged — so it stored the *mirror image* of the preview (a 45° drag on `shed` previewed at ~-40° but committed 50°). Now `start - delta`. None of the earlier rotate tests could catch it, because a 90° drag on a rectangle looks nearly the same either way; one old test (`test_rotate_handle_updates_rotation_and_syncs_panel`) had actually encoded the wrong sign and was corrected. 4 new tests (preview matches the rebuilt geometry at 45°; handles sit on the object's edge after a real rotate drag and after a real resize drag; a second rotate gesture doesn't snap), each confirmed failing before the fix. Handles are placed on the object's axis-aligned bounding box, so on a rotated object the resize handle sits at the box's corner, not on the shape's own outline.

**Dashed objects selectable, and Tab cycles through layered objects, 2026-09-24 — Rich: "I am unable to select the firepit keepout," nor the dashed ground-cover box around the deck and hot tub (`fence_enclosure`):** annotations and keepouts were drawn by `_add_annotation_item` as plain, deliberately non-selectable `QGraphicsPathItem`s, so a click on their outline fell straight through to `site_circle` underneath. They're now `EditableItem`s (select, move, resize, rotate, undo — all the same machinery), but clickable **only along the dashed outline** (`EditableItem.shape()`, a band 3x the drawn line width, with `boundingRect()` widened to cover it) — never the empty interior, so clicking the hot tub inside the ground-cover box, or the firepit inside its keepout, still selects the hot tub/firepit. The text label is now a child of its outline and moves with it; it never takes clicks. The panel's material picker is disabled for these (they have no material); a keepout's `rule` still shows only in its canvas label, not the panel. The old `test_annotations_are_never_editable_even_with_doc` asserted the old rule and was rewritten to assert the new one.

  Alongside it, at Rich's request, **Tab on the canvas cycles the selection through every object under the mouse pointer** (top to bottom, wrapping; Shift+Tab reverses) — the way to reach an object buried under others. Implemented in `SceneGraphicsView.focusNextPrevChild` (what Qt calls for Tab), with mouse tracking so "under the pointer" means where the pointer is *now*, not the last click. Only while the canvas has focus and something is selected: with nothing selected Tab moves focus as usual, and in the right-hand properties panel Tab still steps between controls. With a selection, Tab stays on the canvas even when nothing is under the pointer, rather than unexpectedly jumping focus. 11 new tests (real `QTest` clicks/drags/key presses on `backyard.yaml`), each confirmed failing before the change except the two guards (hot tub still selectable inside the box; panel Tab unchanged) that must keep passing.
- [x] Create objects from a palette of the M2 primitives — a Create menu (one action per creatable kind); `EditorSession.create_object()` adds a centered, sensibly-defaulted object to `doc`, `resolution_order`, and appends a proper raw YAML node via the new `schema.primitive_to_raw_dict()` (the inverse of `parse_primitive`, round-trip verified for every primitive kind). Deliberately excludes `keepout` — it needs a `rule` string and a nested `shape`, no control for either yet. Undoable; newly created object is auto-selected so the properties panel is immediately usable on it.
- [x] Material assignment by visual swatch — `_swatch_icon()` converts M4's `render_swatch()` (a flat PIL image) into a `QIcon` per combo entry; sorted by display name, id kept as `itemData` so the picker shows "Water" with a blue swatch while the document still stores `water`
- [x] Edit relations as simple controls (a "keep centred on firepit" checkbox, a mirror link) — one generic control cluster (relation type, target, up to two params relabeled per type) rather than four separate forms, wired to `EditorSession.set_relation()`. A relation isn't a per-object property like material/transform — it changes the dependency graph — so this required making `scene_io`'s cycle/reference validation (`validate_and_order`, renamed from a private `_validate_references`) reusable after an edit, not just at parse time. On an invalid edit (unknown target, or a real cycle — verified against `deck_east`'s actual `mirror_of: deck_west` in `example.yaml`, not a synthetic case), automatically rolls back to the pre-edit snapshot before re-raising, so a rejected relation can never leave the session in a broken state. Found one real trap while smoke-testing by hand (not a production bug): `QMessageBox.warning()` blocks forever with no running event loop and no display to click "OK" on — harmless in real usage (the event loop is always running there), but manual headless smoke-testing and automated tests both need it mocked, which the actual pytest suite already does correctly.
- [x] Live rule-checker feedback attached to the offending object — `add_violation_overlays()`; try `landscape edit scenes/backyard.yaml --rules rules/backyard.yaml --show-annotations`
- [x] **Undo/redo**, and autosave that never silently discards hand edits — `EditorSession.push_undo/undo/redo`, deep-copying `doc` and the raw `ruamel` tree (verified independently mutable, not just assumed); one snapshot per drag *gesture*, not per mouse-move pixel, via `EditableItem`'s `on_drag_start`/`on_drag_end` hooks. `autosave()` writes a `.autosave` sidecar after every edit (removed once an explicit save supersedes it) — satisfies "never silently discards hand edits" without needing a restore-on-load prompt, which stays open as a UX nicety, not the safety property itself. Found a real repo-hygiene bug while wiring this up: several existing tests loaded the real `scenes/example.yaml`/`scenes/backyard.yaml` directly and then edited them, so every test run littered the repo with `.autosave` sidecars next to the committed fixtures — fixed by having those tests load a private temp copy, plus `*.autosave` added to `.gitignore` as a second line of defense for real usage too.
- [x] Lossless round-trip: load YAML, edit, save, and a file the editor has not
      changed comes back byte-identical — `save_scene()`; verified both ways: an unchanged load-then-save reproduces the source file byte-for-byte, and an edited save touches only the edited object's `material`/`transform` (a cosmetic caveat: a rewritten `transform` switches from whatever flow/block style it had to block style, since it's written as a plain dict — acceptable since the guarantee is about *untouched* content, not about preserving formatting on a value just overwritten)
  **Formatting fix, 2026-09-24** (found in Rich's own saved `backyard.yaml`): ruamel keeps the blank line between objects as a comment on the object's *last* key, so a newly added `transform:` landed *after* that blank line, and re-writing an existing trailing transform would have dropped the gap entirely. `sync_object` now writes through `_set_keeping_trailing_gap()`, which detaches that trailing comment and re-attaches it after the new last key. The one misplaced gap already in `backyard.yaml` was moved by hand (whitespace only, parsed data verified identical).
- [x] Watch-and-reload for files edited outside the editor — a `QFileSystemWatcher` on the loaded path; auto-reloads if nothing's unsaved (`EditorSession.dirty` — as of 2026-09-24 computed from per-edit state ids, so it's also clear after undoing back to the last save; see the Save button item below), otherwise asks first via a Yes/No dialog rather than silently discarding hand edits. Distinguishes our own `save()`/`autosave()` writes from a genuine external change by comparing the file's mtime against the one recorded right after our own last write — a naive implementation would otherwise treat every save as if some other tool had just edited the file. Found a real, subtle bug while testing this, not a hypothetical: the real OS-level file-change signal is delivered asynchronously and can arrive *after* a test function returns, once `monkeypatch` has already restored the real (blocking, undismissable-in-headless-mode) `QMessageBox.question` — aborting the process. Fixed by draining pending Qt events and explicitly stopping the watch before each such test ends, confirmed stable across 5 repeated runs, not just one passing attempt.
- [x] Export straight from the editor (with an **Export options** dialog since 2026-09-24: DPI for PNG, default 300; legend; annotations; scale bar; north arrow and its angle — asked for after the file picker, bad extensions rejected before it, choices remembered for the next export in the session) — `EditorSession.export()` dispatches to M5's `render_scene_to_svg/pdf/png` by extension, so the editor and `landscape render` produce identical output for the same scene; File > Export… in the GUI, with a warning dialog on an unsupported extension instead of a silent failure
- [x] **Wood colour options for decking** (2026-09-25, Rich: "specifically a darker wood") — `deck_dark` (dark wood, `#6F4A35`), `deck_cedar` and `deck_weathered` (grey) alongside the original `deck`, now labelled "Deck (natural)"; all in a `deck` family with the same hatch texture, colours checked to stay distinguishable from every non-deck material (the dark wood's nearest neighbour is mulch, well clear). Chosen per object from the Material dropdown.
- [x] **Fix: design-mode zoom slow, and backing up one step at the end** (2026-09-25, Rich: "zoom is very smooth in the art mode. In design mode it is really slow to zoom and then seems to back up one step at the end"). Two bugs in `SceneGraphicsView.wheelEvent`: every scroll event zoomed a full 5% step whatever its size — a trackpad sends dozens of small deltas per gesture, each forcing a full redraw of the design scene (~7–9 ms offscreen, several times that on a Retina screen, half of it the patio's ~6,000 brick outlines), so zoom lagged behind the fingers, while the art preview is one pixmap and kept up; and a zero-length scroll event — how a trackpad gesture ends — counted as "zoom out". Now each event zooms `ZOOM_PER_TICK ** (delta / 120)` (a mouse notch is still one 5% step; ten tenth-notches equal one notch), zero-length events are ignored, and mid-gesture redraws skip edge smoothing and paver joints, restoring full quality 200 ms after the last scroll. 3 new tests, each failing before the fix.
- [x] **Fix: a dragged object snapped back when switching to Art preview (or back to Design)** (2026-09-25, Rich: moving the firepit and its keep-out "did not save … the fireplace returns to original location even after I save"). Diagnosed with a real drag: the save *was* correct (the file had the new position), but a plain move-drag only updated the document, the raw YAML and the item's own outline — it never recomputed `session.resolved`, which the art preview paints from and every scene rebuild redraws from. So switching views showed the pre-drag position, and the rule check was stale too, until some other edit happened to recompute. Fixed in `EditorWindow._on_object_drag_end`: recompute (geometry + rules), autosave, then a redraw queued until the mouse event has returned (replacing the scene inside it would destroy the item handling the event). New `tests/test_movement.py` (25 tests, real mouse drags on `tests/fixtures/movement.yaml` — one object of every draggable kind, plus a ring that depends on another object): each drag must move the object in the resolved geometry and on the canvas, save to the YAML, survive view switches and the art preview, accumulate across drags, undo, move its dependents, and re-run the rules. Without the fix 13 of them fail — and the 12 save-to-YAML ones pass, exactly the pattern Rich saw.
- [x] **Type a size to reshape, in one dimension or both** (2026-09-25, on request) — the properties panel's Size row is now editable: width x height boxes (one ⌀ box for circles and regular polygons; a dimension that's zero, like a straight fence's height, is greyed out). Typing a value reshapes the object *non-uniformly* — only that dimension, keeping its centre and its `transform.scale` — by rewriting the primitive's own fields in the YAML (a rect's `width`/`height` and `x`/`y`, an ellipse's `rx`/`ry`, a circle's `r`, points stretched about their centre, a keepout's nested `shape`), only the fields that changed, whole numbers kept whole and point lists kept compact (`dimensions.py`, `EditorSession.set_dimensions`, undoable). Sizes are shown and entered *after* scale, matching what's drawn. Commits on Enter, leaving the box, or an arrow click — not per keystroke. Instances of a shared `definitions` entry keep a read-only readout (their shape belongs to the definition). Found and fixed along the way: the wider boxes made selecting an object widen the panel, squeeze the canvas and slide the drawing sideways (zoom anchors on the view centre) — the panel's minimum width is now fixed at its widest content.
- [x] **Pavers: patterns and colors** (2026-09-25, on request) — `pavers.py` generates every brick of a paved area as a polygon for **herringbone 45° / 90°, running bond, basketweave**, and a **sailor** border course around a ring (tested to tile with no gaps or overlaps; whole bricks are the real 8 x 4 in). Five colors as materials in a `pavers` family — **light grey, classic red, red blend, tan, charcoal** (`texture: {style: pavers, pattern, brick, variation}`); the palette check compares family members only to other materials, and the colors were picked to stand apart from sand and concrete. The pattern is a per-object `pattern:` choice overriding the material's default, with a **Pattern** dropdown in the properties panel for paver objects. Drawn everywhere from the same bricks: joint lines on the design canvas (re-laid after a resize/rotate) and in flat renders, and in art mode each brick a slightly different tone (the blend most) with light pencil joints. Layouts are cached by geometry (a 36 ft herringbone is ~6,000 bricks; the backyard's canvas rebuild stays ~0.09 s).
- [x] **Size readout, legend box and scale indicator** (2026-09-25, on request) — the properties panel's **Size** row shows the selected object's real size after scaling (its tightest rotated rectangle, so a turned 6 x 4 shed reads 6.00 x 4.00 ft; a diameter for circles; a length for lines), updating live on every step of a resize-handle drag. The drawing gains a **legend box** (uniform square swatches for materials in use, circles for unassigned items like the firepit and water features grouped by name — detail linework like seams left out — each with a text note) and a **scale indicator** (a horizontal line with its length written above). Both are laid out once in Qt-free `overlays.py` (sized in paper inches so they look the same at any plan scale) and drawn from that by the design canvas (`OverlayItem`, dragged by an origin marker — own mouse handling, so it never also drags a selected object), the flat renderer, and the art renderer (painted: paper lifted clean in the box, watercolor swatches, pencil frame and graphite text). Positions are saved as optional top-level `legend: {x, y}` / `scale_indicator: {x, y}` in the scene, only once moved (`EditorSession.set_overlay_position`, undoable), so untouched files stay byte-identical. Art preview always paints both; exports draw them via `show_legend` / `scale_indicator` (CLI `--legend --scale-indicator`, recipe keys, Export dialog checkboxes — on by default there); the old fixed bottom-left flat legend is gone. Text is a plain sans in graphite — a bundled pencil/handwriting font is still the open item noted under the visual redesign.
- [x] **Save button and unsaved-changes indicator** (2026-09-24, on request) — a toolbar under the menu bar with **Save** (the same `QAction` as File > Save and Ctrl+S, so all three enable/disable together — greyed out when there's nothing to save) and a red "● Unsaved changes" label; the window title also carries Qt's `[*]` modified marker. Driven by a new Qt-free `EditorSession.on_state_change` callback, fired by load/every edit's `push_undo()`/undo/redo/save — needed because a plain move-drag never rebuilds the scene, so the indicator can't just hang off `_rebuild_scene`. `dirty` is now a property comparing state ids rather than a sticky flag: every edit gets a fresh, never-reused id carried through undo/redo, so **undoing back to the last save clears the indicator** (Rich's call — this used to stay dirty until an explicit save), redoing past it sets it again, and a new edit made after undoing is never mistaken for the saved state. A rejected relation edit rolls its state id back too. **Save As** now switches the file being edited to the new path (standard desktop behaviour; previously it wrote the copy but kept editing, watching and plain-saving the original). **Closing with unsaved changes asks Save / Discard / Cancel**; Discard leaves the `.autosave` sidecar as a backup, and a failed save (here or from the button) shows a warning and keeps the window open rather than raising. Test harness note: pytest-qt closes every window at teardown, so any test leaving edits unsaved hung forever on the new modal prompt the first time this ran — an autouse fixture now answers it with Discard. Two older tests encoded the replaced behaviour and were updated (`test_still_dirty_after_undo_to_original_state` → the new rule; `test_save_action_writes_the_file` now edits first, since Save is disabled on an unchanged scene). 15 new tests.

## M8b — CLI  *(complete)*

- [x] Batch/headless rendering for developer use and regression tests — `landscape export <recipe>` (see M7's batch export) renders any number of outputs headlessly in one run; `landscape render` covers the single-output case. Using it to *drive* golden-image regression tests is M9's still-deferred item, not a missing capability here.

## M9 — Validation and testing

**Test coverage audit (2026-09-21).** 139 tests existed across the project at the time (310 as of 2026-09-24, 504 as of 2026-09-25 — most of the growth in editor tests, plus `test_movement.py`'s real-drag suite)
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
  zoom. 5 new tests, stable across repeated runs. The judgment at the time
  — that the rest of the editor could keep driving interaction via
  `setPos()`/`setSelected()`, since nothing needed the real dispatch path —
  turned out wrong: from 2026-09-22 on, real `QTest` mouse
  press/move/release gestures caught three genuine bugs that `setPos()`
  tests structurally couldn't (handles dragging the selected object,
  move-drags compounding past the cursor, click-to-select broken), so new
  interaction tests use real events — clicks, multi-step drags, Tab/
  Shift+Tab — and some older `setPos()` tests remain alongside them.
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



## M11 — 3D view  *(built 2026-09-25: heights, cameras, the 3D view mode and exports, and the backyard's heights and first camera; later: posts-and-rails fences, tree crowns, `sits_on`, the watercolor 3D style)*

A third view — **Design | Art preview | 3D view** — showing the backyard in perspective from a camera placed in the plan. Full requirements, proposed default heights and open questions: `docs/3d-view-requirements.md`. Decide its open questions (heights, camera controls, style, renderer technology) before building.

**Camera**
- [x] Camera model: `id`, `x`, `y`, `z` (eye height), a **look-at point** `look_x`/`look_y`/`look_z` (decided — Rich), `fov`; several named cameras per scene
- [x] Schema + round-trip: optional top-level `cameras:` list, written only once one exists (untouched files stay byte-identical); validation with line numbers
- [x] Design-mode camera marker plus a draggable **look-at marker** joined by a line, with the field-of-view wedge; drag either — undoable, saved, never drags the selected object, recomputes on release
- [x] Properties panel for a selected camera (as a **3D camera** section under the object panel, always available): X, Y, Z, look-at X, Y, Z, field of view as typed values (heading/tilt shown read-only)
- [x] Create / delete cameras; a chooser for the camera the 3D view uses (rename: not yet)
- [x] Cameras excluded from the legend, rule checker, Tab cycling, and plan exports

**Heights**
- [x] Object-level base and height — as a nested `solid: {base, height}` (a rect's `height` is already its 2D height) — optional, round-trips losslessly
- [x] Material-level default heights (e.g. deck 1.5 ft, pad 0.33 ft, ground surfaces 0) so most objects need nothing written
- [~] Use `fence_line`'s existing `height` (done) / `post_spacing` / `post_size` / `rail_count` (posts and rails not modelled yet — fences are slabs)
- [x] Properties panel **Height** row (and base), editable like Size
- [ ] Backyard heights: hot tub 3 ft on its pad (**confirmed**); deck multi-level — north 1.5 ft, middle 1 ft, forward 6 in (**decided**; tier-to-object mapping to confirm); fences, firepit, water features still to confirm
- [ ] `sits_on:` relation so stacked things (tub on pad, planters on deck) follow what they rest on
- [ ] Flat ground at z = 0 for now; real grade stays an open question

**Rendering**
- [x] Renderer: **PyVista/VTK** — approved by Rich, added (Rich asked to leverage an existing engine; prototype renders the backyard in < 1 s with look-at camera, flat shading, outlines, sky) — pending OK on the ~520 MB dependency; fallback: small in-house renderer
- [x] Extrude each resolved 2D shape from base to base + height (holes carried through); flat objects as ground polygons in paint order
- [ ] Fences as posts and rails; tree crowns as trunk + crown (not extrusions)
- [x] Perspective projection with correct hiding (nearer objects in front), clipping behind the camera
- [x] First style: flat-shaded material colors with simple sun lighting and silhouette/crease outlines (**decided**: flat-shaded first)
- [x] **Background: a surrounding 6 ft vinyl fence with sky above** (decided — Rich); on the page boundary until the real yard boundary is known, then real `fence_line` objects
- [x] Ground layers stacked properly (the prototype hid the sand circle under the patio)
- [ ] Pavers as a surface texture (joints), not ~6,000 bricks of geometry
- [ ] Later style: watercolor-and-pencil perspective (washes from color regions, pencil from depth/normal edges), reusing the art renderer

**Editor and exports**
- [x] **3D view** toolbar button and View menu entry (shortcut), read-only like Art preview, camera chooser in the toolbar; cached by document revision + camera
- [x] `3d` render mode in `render.py`; `landscape render --mode 3d --camera NAME`; `mode: 3d` + `camera:` in export recipes; Export dialog Style entry

**Validation**
- [x] Camera math against hand-computed points (centre, off-axis angle, behind-camera culling, occlusion)
- [x] Heights and cameras round-trip; untouched scenes byte-identical
- [x] Real-drag tests for moving/turning the camera (like `test_movement.py`)
- [x] Determinism; preview speed target (backyard < ~1 s at screen resolution)
- [x] **Fence colours and textures** (2026-09-25, Rich: "vertical vinyl slats with posts every 8 feet" and "a cedar colored fence") — `fence_vinyl` (white `#F2F1EC`, 6 in slats, ½ in gaps) and `fence_cedar` (`#A5603A`, 5½ in boards) join the plain fence (now "Fence (natural)") in a `fence` family; recipe `texture: {style: fence, boards, slat_width_in, gap_in, post_spacing, post_size_in}` (`fences.py`). Posts every 8 ft from the fence's start plus one at its end (a shorter last bay, as built), found along the centre line of the fence's shape so they follow moves and turns. Plan: posts as darker squares (Design, flat, art). 3D: a panel with the boards as a tiled generated texture (crisp vinyl slats with shadow lines, or cedar boards with grain and dark seams) between posts standing 3 in proud; the **surrounding background fence is now vinyl with posts** too. The backyard's `existing_vinyl_fence` now uses the vinyl material; the back fence is still the plain one (cedar is ready for it). 11 tests.
- [x] **3D models from a local folder** (2026-09-25, Rich: models, e.g. from TurboSquid, are never committed; place one if it's available, a placeholder if not). `models/` at the repo root (or `LANDSCAPE_MODELS`) is git-ignored except its README — model licences don't allow redistributing the files. New `model` object type (`file`, `x`, `y`, `width`, `depth`, `height`, `rotation`, optional `up`): on the plan its footprint (neutral grey, labelled with the file, dashed and marked "model missing" when absent; the status bar lists missing ones); in the 3D view the file is found by name anywhere in the folder, imported with its materials (glTF/GLB, OBJ+MTL, 3DS, VRML; STL/PLY as bare geometry), stood upright (Y-up by default, Z-up for STL/PLY), fitted inside its declared size *keeping its proportions*, turned and placed — following the object's own moves/turns/resizes — or drawn as a placeholder box of that size if missing or unreadable. **Create › Model…** lists the folder's models and places one at 4 ft across by its proportions (file units vary, so the designer sets the real size in Size and Height); **File › Open models folder / Rescan models folder**. The 3D view's cache notices models being added, replaced or removed. 17 tests (generated test models, never real ones).
- [x] **A 3D model for any design element** (2026-09-25, Rich: "Add this model as a selectable option the firepit design element") — an optional `model: <file>` on any object (not a `type: model`, which uses `file:`). The element keeps its own shape and material on the plan (labelled with the file, dashed when missing); in the 3D view the model fills the element's footprint, measured in the element's own frame so it turns with it, keeping proportions — to the element's height if it has one (`solid:` or its material's), else its own proportions. When the file is missing it's drawn as a placeholder of the footprint's shape, half as tall as it is wide when no height is given. **Right-hand column › 3D model** lists *(plain shape)* plus the models folder (rescanned on each selection; a model object switches its file); undoable and saved. Missing element models show in the status bar like model objects. 6 tests. Models to use with it are generated by `tools/make_fire_bowl_model.py` and `tools/make_hot_tub_model.py`.
- [x] **River rock and turf grass ground covers** (2026-09-25, Rich: "For the big circle, add a river rock texture option and a turf grass option") — two new materials in the Material dropdown, `river_rock` (4 in rounded stones, `#A8977C`) and `turf` (`#5E9A3C`, 3 ft mowing stripes), with texture styles `river_rock` / `turf` (`src/landscape/ground_covers.py`, one shared source of stones and stripes). Design canvas: stones in three tones with thin outlines, or turf's alternate stripes (hidden while zooming, like paver joints, and re-laid after a resize/turn). Flat: each stone its own tone. Art: per-stone tone over the wash with light pencil ovals; turf's stripes a touch deeper, plus pencil tufts. 3D: a seamless tiled texture at real size (rounded, lit stones; streaked grass with stripes). Rules: both are ground covers things stand on (no overlap warnings); turf is flagged inside the firepit keep-out (grass scorches), river rock isn't — the fire-safe option. The backyard circle stays gravel until Rich picks one. 9 tests.
- [x] ~~Known intermittent issue~~ — **found and fixed (2026-09-25):** importing PyVista at a test file's top level (at collection time, before Qt starts) let VTK set up macOS's windowing first; Qt and VTK then contended for it — the suite ran twice as slowly and the process hung for minutes at exit. Proven by `--ignore` (fine) vs `--deselect` (hung: imported but not run). PyVista is now only imported inside functions everywhere, with a guard test; the close-prompt test fixture also moved to `tests/conftest.py` so no test file can forget it (a forgotten one caused a separate hang the same day). Suite: 577 tests, ~37 s, exits immediately.
- [x] Backyard scene: the decided heights (hot tub 3 ft on its 0.33 ft pad; deck north 1.5 ft, middle 1 ft, forward 0.5 ft) and a first camera, `view_1` (standing at (10, 4), eye height 5.5 ft, looking at the hot tub) — added after committing Rich's edits (gravel circle, dark wood decks, legend placed). Firepit and water features left flat until their heights are confirmed.

## Feature backlog

Deferred on purpose, not forgotten: things Rich has asked to park until later. Not scheduled into any milestone yet.

- [ ] **Zoom on the selected object** — zoom anchored on the selected object's centroid (the same point the resize/rotate handles pivot on) rather than the viewport center. Parked 2026-09-24; plain viewport-center zoom (the 2026-09-23 simplification, see M8) is working well enough for now — Rich: "Zoom bug seems better now." If picked up, avoid the earlier version's flaw: the anchor jumped between the viewport center and an object's center whenever the selection changed, which read as "scales wildly and then recenters."
- [ ] **Handle placement on rotated objects** — the resize/rotate handles sit on the object's axis-aligned bounding box, so on a rotated object the resize handle lands on the box's corner, which can be off the shape itself. Adjust them to sit on the object's own (rotated) outline/corner instead. Parked 2026-09-24; the handles-drifting-away bug itself is fixed (see M8, `_settle_handle_gesture`).

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
