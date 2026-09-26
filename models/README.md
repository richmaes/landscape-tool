# 3D models (local only — never committed)

Put 3D model files here for the 3D view. **Nothing in this folder is
committed** except this README (see `.gitignore`): model licences, such as
TurboSquid's, don't allow redistributing the files, and a repository is
redistribution.

**Formats:** `.glb` / `.gltf` (best — keeps materials and textures), `.obj`
(with its `.mtl` and textures beside it), `.3ds`, `.stl`, `.ply`, `.wrl`.
FBX, MAX, C4D and Blender files aren't supported — export one of the above
from the modelling tool, or convert it in Blender.

**Subfolders are fine.** A scene refers to a model by its file name (or its
path inside this folder), and the editor searches the whole folder, so
files can be organised however you like.

**Placing one:** in the editor, **Create › Model…** lists what's here. The
model is placed at the page centre, sized by its proportions (4 ft across);
set its real width, depth (the Size row) and height (the Height row) — model
files' own units vary. It shows as its footprint on the plan and as the real
model in the 3D view.

**Missing a model?** A scene still opens and renders without it: the plan
marks it "model missing", and the 3D view draws a plain placeholder box of
its declared size in its place.

**Somewhere else:** set the `LANDSCAPE_MODELS` environment variable to use a
different folder.

**A simple hot tub, generated:** `.venv/bin/python tools/make_hot_tub_model.py`
writes `Simple Hot Tub/simple_hot_tub.obj` here (7 x 7 x 3 ft, wooden plank
exterior, off-white interior). The script is committed, so it can be
regenerated on any machine.

**OBJ textures not showing?** VTK's OBJ importer ignores *all* texture
coordinates in a file if any face lacks them (a face line like `f 1 2 3`
instead of `f 1/1 2/2 3/3`). Re-exporting with UVs on every face — or as
glTF/GLB — fixes it.
