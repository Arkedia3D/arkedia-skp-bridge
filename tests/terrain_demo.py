# -*- coding: utf-8 -*-
"""Terrain d'essai pour l'adoucissement des arêtes : le même relief exporté avec et sans adoucissement.

Le relief est une grille de triangles d'un mètre de côté avec un bruit de scan, deux vallonnements et un talus
raide (4 m de dénivelé sur une rangée de triangles). Entre les deux exports, seules changent les arêtes :
douces et lisses sous 35 degrés, toutes tracées sinon. Le talus doit rester marqué dans les deux cas.

Usage : python run_blender.py terrain_demo.py <dossier_sortie> [côté en mètres, 200 par défaut] [bruit en mètres, 0.15]
                                              [angle d'adoucissement en degrés, 35]
"""
import sys, os, json, time

ARGS = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGS[0]
SIDE = int(ARGS[1]) if len(ARGS) > 1 else 200
NOISE = float(ARGS[2]) if len(ARGS) > 2 else 0.15
ANGLE = float(ARGS[3]) if len(ARGS) > 3 else 35.0
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()
os.makedirs(OUT, exist_ok=True)

import bpy  # noqa: E402
import numpy as np  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402


def terrain(side):
    rng = np.random.default_rng(7)
    xs = np.arange(side + 1, dtype=float)
    X, Y = np.meshgrid(xs, xs)
    Z = 6.0 * np.sin(X / 35.0) * np.cos(Y / 50.0) + 3.0 * np.sin(X / 12.0 + Y / 17.0) + NOISE * rng.standard_normal(X.shape)
    Z += np.where(X >= side * 0.6, 4.0, 0.0)  # le talus : une marche de 4 m sur un mètre de plan
    V = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    idx = np.arange((side + 1) ** 2).reshape(side + 1, side + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    F = np.concatenate([np.column_stack([a, b, d]), np.column_stack([a, d, c])])
    return V, F


def scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    V, F = terrain(SIDE)
    me = bpy.data.meshes.new("Terrain")
    me.from_pydata(V.tolist(), [], F.tolist())
    mat = bpy.data.materials.new("Herbe")
    mat.use_nodes = True
    bsdf = A._principled(mat, create=False)
    lin = tuple(A._srgb_to_linear(c / 255.0) for c in (112, 150, 70))
    bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
    mat.diffuse_color = (*lin, 1.0)
    me.materials.append(mat)
    me.update()
    ob = bpy.data.objects.new("Terrain", me)
    bpy.context.scene.collection.objects.link(ob)
    return len(F)


def main():
    rep = {"bruit_m": NOISE, "angle_deg": ANGLE}
    t0 = time.time()
    try:
        rep["triangles"] = scene()
        for tag, soften in (("terrain_adouci", True), ("terrain_aretes", False)):
            path = os.path.join(OUT, tag + ".skp")
            rep[tag] = A.export_skp(path, bpy.context, only_selected=False, soften_dense=soften, soften_angle=ANGLE)
        rep["statut"] = "OK"
    except BaseException as exc:  # noqa
        import traceback
        rep["statut"] = "ERREUR"
        rep["erreur"] = "%s: %s" % (type(exc).__name__, exc)
        rep["trace"] = traceback.format_exc()[-3000:]
    rep["secondes"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT, "rapport.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sys.stdout.write("FIN %s\n" % rep["statut"])
    sys.stdout.flush()
    os._exit(0)


main()
