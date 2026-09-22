# Landscape Rendering Tool — Task List

**Status:** M0–M3 complete — M3b rule checker (or M1's leftover objects.json-to-YAML conversion) is the next work
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
- [ ] **UI stack for the editor** — Tk/Qt desktop vs. a browser front end over the Python core. A browser UI is usually far more approachable for a non-technical daily user. Decide before M8.
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

## M1 — PDF to scene script  *(largely complete)*

- [x] Ingest the source site-plan PDF; determine vector vs. raster — pure vector
- [x] Extract vector paths with coordinates, colours and true paint order
- [x] Establish scale — 36 pt = 1 ft, confirmed by the 2 ft scale badge and round dimensions
- [x] Classify extracted geometry into named objects with roles
- [x] Emit `extraction/objects.json` + `extraction/objects.md` (20 objects)
- [x] Capture the existing vinyl fence, which is absent from the PDF
- [ ] Convert `objects.json` into the first real scene YAML once M2 lands
- [x] Extraction kept as a one-time bootstrap (`tools/extract_pdf.py`), not a runtime dependency

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

## M3b — Rule checker (DRC)

Constraints warn; they never block. The designer must be free to drag
anything anywhere and be told afterwards what is wrong.

- [ ] Rule engine over the resolved scene, emitting located, human-readable violations
- [ ] Starter rules:
  - [ ] No burnable material inside a keep-out zone (catches `deck_s`, currently 0.085 ft inside)
  - [ ] Keep-out zone must be concentric with its firepit
  - [ ] Keep-out zone must be contained by its parent region
  - [ ] Objects must not overlap unless explicitly stacked
  - [ ] Access clearance in front of a mechanical bay
- [ ] Violations surface in the editor next to the offending object, not in a log
- [ ] Rules are data, so new ones do not need code changes

## M4 — Material system

- [ ] Material definition schema: name, flat color, texture recipe, edge treatment
- [ ] Material library file, separate from scenes, so palettes swap independently
- [ ] Starter materials: lawn, planting bed, mulch, gravel, flagstone, concrete, deck/wood, water, stone wall, fence, mature tree/shrub canopy
- [ ] Pastel palette definition with a rule for keeping adjacent materials distinguishable
- [ ] Material resolution: object to material to render parameters, with sensible fallback
- [ ] Visual swatch picking — the designer chooses materials by appearance and name, never by hex code

## M5 — Renderer: flat pastel mode

- [ ] Rendering abstraction so both modes share scene traversal (backend-agnostic draw calls)
- [ ] Fill each region with its flat pastel color
- [ ] Outline style — weight, color, whether outlines are per-material
- [ ] Labels/callouts and an optional legend keyed to materials
- [ ] Vector-native output (clean SVG/PDF, no rasterization)

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

## M8 — Graphical editor  *(promoted: this is the primary interface)*

- [ ] Decide the UI stack (see open questions)
- [ ] Fast low-resolution preview render for interactive iteration
- [ ] Pan/zoom; toggle layers and render modes
- [ ] Select, move, resize and rotate objects directly
- [ ] Create objects from a palette of the M2 primitives
- [ ] Material assignment by visual swatch
- [ ] Edit relations as simple controls (a "keep centred on firepit" checkbox, a mirror link)
- [ ] Live rule-checker feedback attached to the offending object
- [ ] **Undo/redo**, and autosave that never silently discards hand edits
- [ ] Lossless round-trip: load YAML, edit, save, and a file the editor has not
      changed comes back byte-identical
- [ ] Watch-and-reload for files edited outside the editor
- [ ] Export straight from the editor

## M8b — CLI

- [ ] Batch/headless rendering for developer use and regression tests

## M9 — Validation and testing

- [ ] Unit tests: primitive generation, `waviness` behavior at parameter extremes, boolean ops
- [ ] Schema validation tests, including malformed scenes producing useful errors
- [ ] Golden-image regression tests for both render modes
- [ ] Round-trip check: scene to render, visually verified against the source PDF plan
- [ ] Determinism test across runs and platforms

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
