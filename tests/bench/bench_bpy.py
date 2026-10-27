# -*- coding: utf-8 -*-
"""Micro-mesure des appels bpy qui servent à l'import : où le temps devient-il quadratique ?

blender -b --factory-startup --python bench_bpy.py -- <N> <journal> [variante]
variante : base (comme l'import actuel : un maillage, une collection de source et un vide instanciant la collection)
           tpl (idem, mais maillages copiés depuis un gabarit déjà muni de son matériau)
           direct (objets réels qui partagent leur maillage, aucune collection de source)
           directtpl (objets réels + gabarit de matériau)
Chaque tranche de 2500 objets affiche le temps passé par opération : une valeur qui grandit d'une tranche à la
suivante signale un coût quadratique.
"""
import sys, time, os
import numpy as np
import bpy
import mathutils

ARGS = sys.argv[sys.argv.index("--") + 1:]
N, LOGP = int(ARGS[0]), ARGS[1]
VAR = ARGS[2] if len(ARGS) > 2 else "base"
USE_TPL = VAR in ("tpl", "directtpl")
DIRECT = VAR in ("direct", "directtpl")
LOG = open(LOGP, "w", encoding="utf-8", buffering=1)
bpy.ops.wm.read_factory_settings(use_empty=True)

mats = [bpy.data.materials.new("M%d" % i) for i in range(8)]
root = bpy.data.collections.new("root")
bpy.context.scene.collection.children.link(root)
layers = [bpy.data.collections.new("L%d" % i) for i in range(10)]
for c in layers:
    root.children.link(c)
src = bpy.data.collections.new("src")
root.children.link(src)

cube = np.array([[x, y, z] for z in (0, 1) for y in (0, 1) for x in (0, 1)], np.float32)
tri = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4],
                [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]], np.int32)
loop_start = np.arange(0, 36, 3, dtype=np.int32)
pc = time.perf_counter
KEYS = ("mesh_new", "mat", "geom", "update", "obj_new", "coll_new", "coll_objlink", "coll_childlink", "link", "matrix")
T = dict.fromkeys(KEYS, 0.0)
tpl = {}
CH = 2500
t_all = pc()
last = dict(T)

for i in range(N):
    key = i % 8
    t = pc()
    if USE_TPL:
        if key not in tpl:
            g = bpy.data.meshes.new("tpl%d" % key)
            g.materials.append(mats[key])
            tpl[key] = g
        me = tpl[key].copy()
        me.name = "m%d" % i
        T["mesh_new"] += pc() - t
    else:
        me = bpy.data.meshes.new("m%d" % i)
        T["mesh_new"] += pc() - t
        t = pc()
        me.materials.append(mats[key])
        T["mat"] += pc() - t
    t = pc()
    me.vertices.add(8)
    me.vertices.foreach_set("co", (cube * (1 + key)).ravel())
    me.loops.add(36)
    me.polygons.add(12)
    me.polygons.foreach_set("loop_start", loop_start)
    me.polygons.foreach_set("vertices", tri.ravel())
    T["geom"] += pc() - t
    t = pc()
    me.update(calc_edges=True)
    T["update"] += pc() - t
    t = pc()
    ob = bpy.data.objects.new("o%d" % i, me)
    T["obj_new"] += pc() - t
    M = mathutils.Matrix.Translation((i % 100, i // 100, 0.0))
    if DIRECT:
        t = pc()
        layers[i % 10].objects.link(ob)
        T["link"] += pc() - t
        t = pc()
        ob.matrix_world = M
        T["matrix"] += pc() - t
    else:
        t = pc()
        c = bpy.data.collections.new("c%d" % i)
        T["coll_new"] += pc() - t
        t = pc()
        c.objects.link(ob)
        T["coll_objlink"] += pc() - t
        t = pc()
        src.children.link(c)
        T["coll_childlink"] += pc() - t
        t = pc()
        e = bpy.data.objects.new("e%d" % i, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = c
        T["obj_new"] += pc() - t
        t = pc()
        layers[i % 10].objects.link(e)
        T["link"] += pc() - t
        t = pc()
        e.matrix_world = M
        T["matrix"] += pc() - t
    if (i + 1) % CH == 0:
        LOG.write("[%6d objets, %6.1f s] " % (i + 1, pc() - t_all) + " ".join("%s=%.2f" % (k, T[k] - last[k]) for k in KEYS) + "\n")
        last = dict(T)
LOG.write("TOTAL %.1f s : " % (pc() - t_all) + " ".join("%s=%.1f" % (k, T[k]) for k in KEYS) + "\n")
LOG.write("FIN\n")
LOG.flush()
os._exit(0)
