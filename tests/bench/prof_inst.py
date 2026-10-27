# -*- coding: utf-8 -*-
"""Profil de l'export .skp pour N instances d'un même maillage (72 triangles).

blender -b --factory-startup --python prof_inst.py -- <N> <dossier_sortie> [profil]
"""
import sys, os, time, math, io, cProfile, pstats

ARGS = sys.argv[sys.argv.index("--") + 1:]
N, OUT = int(ARGS[0]), ARGS[1]
PROFILE = len(ARGS) > 2 and ARGS[2] == "profil"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _env  # noqa: E402
_env.setup()
os.makedirs(OUT, exist_ok=True)

import bpy, bmesh, mathutils  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

LOG = open(os.path.join(OUT, "prof_inst_%d.txt" % N), "w", encoding="utf-8", buffering=1)


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
parts = [(0.0, 0.0, 0.225, 0.05, 0.05, 0.45), (0.4, 0.0, 0.225, 0.05, 0.05, 0.45), (0.0, 0.4, 0.225, 0.05, 0.05, 0.45),
         (0.4, 0.4, 0.225, 0.05, 0.05, 0.45), (0.2, 0.2, 0.475, 0.45, 0.45, 0.05), (0.2, 0.4, 0.75, 0.45, 0.05, 0.5)]
for ox, oy, oz, sx, sy, sz in parts:
    m = mathutils.Matrix.Translation((ox, oy, oz)) @ mathutils.Matrix.Diagonal((sx, sy, sz, 1.0))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
me = bpy.data.meshes.new("Chaise")
bm.to_mesh(me)
bm.free()
mat = bpy.data.materials.new("Bois")
me.materials.append(mat)
colls = []
for i in range(5):
    c = bpy.data.collections.new("Zone_%d" % i)
    bpy.context.scene.collection.children.link(c)
    colls.append(c)
side = int(math.ceil(math.sqrt(N)))
t0 = time.time()
for i in range(N):
    ob = bpy.data.objects.new("Chaise_%06d" % i, me)
    colls[i % 5].objects.link(ob)
    ob.location = ((i % side) * 0.8, (i // side) * 0.8, 0.0)
    ob.rotation_euler = (0.0, 0.0, (i % 7) * 0.4)
bpy.context.view_layer.update()
log("construction %.1f s, %d objets, %d triangles/objet" % (time.time() - t0, N, len(me.polygons)))

out = os.path.join(OUT, "inst_%d.skp" % N)
t0 = time.time()
if PROFILE:
    pr = cProfile.Profile()
    pr.enable()
    stats = A.export_skp(out, bpy.context, only_selected=False)
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(35)
    log(s.getvalue())
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("tottime")
    ps.print_stats(20)
    log(s.getvalue())
else:
    stats = A.export_skp(out, bpy.context, only_selected=False)
log("export %.1f s" % (time.time() - t0), {k: v for k, v in stats.items() if k != "skip_reasons"})
log("FIN")
os._exit(0)
