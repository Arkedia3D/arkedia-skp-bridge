# -*- coding: utf-8 -*-
"""Rendus Workbench pour le README : une scène .blend, ou un .skp importé par l'extension.

blender -b --factory-startup --python render_readme.py -- <source.blend|source.skp> <sortie.png> [largeur hauteur]
"""
import sys, os, math
ARGS = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = ARGS[0], ARGS[1]
W, H = (int(ARGS[2]), int(ARGS[3])) if len(ARGS) >= 4 else (1280, 800)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()
import bpy, mathutils  # noqa: E402

if SRC.lower().endswith(".skp"):
    import arkedia_skp_bridge as A  # noqa: E402
    bpy.ops.wm.read_factory_settings(use_empty=True)
    A.import_skp(SRC, bpy.context)
else:
    bpy.ops.wm.open_mainfile(filepath=SRC)
sc = bpy.context.scene
# tout est visible, aucune caméra de la scène source n'est utilisée
for ob in list(bpy.data.objects):
    if ob.type in {"CAMERA", "LIGHT"}:
        bpy.data.objects.remove(ob)
pts = []
for ob in bpy.data.objects:
    if ob.type == "MESH" and ob.visible_get():
        pts += [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
lo = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr, diag = (lo + hi) / 2.0, (hi - lo).length
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
cam.data.lens = 40
direction = mathutils.Vector((1.0, -1.15, 0.78)).normalized()
cam.location = ctr + direction * diag * 1.25
cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
sc.camera = cam
sc.render.engine = "BLENDER_WORKBENCH"
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "Standard"
sh = sc.display.shading
sh.light = "STUDIO"
sh.color_type = "TEXTURE"
sh.show_object_outline = True
sh.object_outline_color = (0.0, 0.0, 0.0)
sh.show_cavity = False
sh.background_type = "VIEWPORT"
sh.background_color = (0.93, 0.95, 0.97)
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
sys.stdout.write("RENDU_OK %s\n" % OUT)
sys.stdout.flush()
os._exit(0)
