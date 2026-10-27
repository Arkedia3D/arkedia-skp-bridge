# -*- coding: utf-8 -*-
"""Fidélité unité par unité : scène d'origine (.blend) contre sa réimportation depuis le .skp exporté.

blender -b --factory-startup --python check_roundtrip.py -- <origine.blend> <export.skp> <rapport.json>

Une « unité » est un objet maillé ou une instance de collection (exportée comme un seul composant). Pour chaque
unité d'origine, on cherche dans la scène réimportée l'unité dont le centre de surface est le plus proche, puis on
compare centre, aire, volume et boîte englobante. Un miroir mal rendu (accoudoir du mauvais côté) décale le centre
de surface : il apparaît ici alors qu'un contrôle d'aire ou de volume globaux ne le voit pas.
"""
import sys, os, json
import numpy as np

ARGS = sys.argv[sys.argv.index("--") + 1:]
BLEND, SKP, OUT = ARGS[0], ARGS[1], ARGS[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()

import bpy  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402


def collect():
    """Une fiche par unité : nom, nombre de maillages, aire, volume signé, centre de surface, boîte englobante."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    units = {}
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type != "MESH" or len(ob.data.polygons) == 0:
            continue
        me = ob.data
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        ti = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", ti)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        M = np.array(inst.matrix_world, dtype=np.float64)
        P = co.reshape(-1, 3).astype(np.float64)[ti.reshape(-1, 3)] @ M[:3, :3].T + M[:3, 3]
        parent = inst.parent
        key = parent.name if (inst.is_instance and parent is not None and parent.type == "EMPTY") else ob.name
        units.setdefault(key, []).append(P)
    rows = []
    for key, plist in units.items():
        P = np.concatenate(plist)
        a, b, c = P[:, 0], P[:, 1], P[:, 2]
        area_t = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
        area = float(area_t.sum())
        cen = (area_t[:, None] * (a + b + c) / 3.0).sum(axis=0) / area
        vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        pts = P.reshape(-1, 3)
        rows.append({"nom": key, "maillages": len(plist), "aire": area, "vol": vol, "centre": [float(x) for x in cen],
                     "min": [float(x) for x in pts.min(axis=0)], "max": [float(x) for x in pts.max(axis=0)]})
    return rows


bpy.ops.wm.open_mainfile(filepath=BLEND)
orig = collect()
bpy.ops.wm.read_factory_settings(use_empty=True)
stats = A.import_skp(SKP, bpy.context)
new = collect()

res, used = [], set()
for o in sorted(orig, key=lambda r: -r["aire"]):
    best, bd = None, 1e18
    for j, n in enumerate(new):
        if j in used:
            continue
        d = float(np.linalg.norm(np.array(o["centre"]) - np.array(n["centre"])))
        if d < bd:
            best, bd = j, d
    if best is None:
        res.append({"nom": o["nom"], "trouve": False})
        continue
    used.add(best)
    n = new[best]
    res.append({"nom": o["nom"], "maillages_origine": o["maillages"], "importe": n["nom"], "maillages_import": n["maillages"],
                "dist_centre_m": round(bd, 6), "aire_ratio": round(n["aire"] / o["aire"], 9),
                "vol_ratio": round(abs(n["vol"]) / abs(o["vol"]), 9) if o["vol"] else None,
                "ecart_boite_m": round(float(max(np.abs(np.array(o["min"]) - np.array(n["min"])).max(),
                                                  np.abs(np.array(o["max"]) - np.array(n["max"])).max())), 6)})

found = [r for r in res if r.get("trouve", True)]
rep = {"unites_origine": len(orig), "unites_importees": len(new), "non_appariees": len(new) - len(used),
       "pire_ecart_centre_m": max((r["dist_centre_m"] for r in found), default=None),
       "pire_ecart_boite_m": max((r["ecart_boite_m"] for r in found), default=None),
       "pire_ecart_aire": max((abs(r["aire_ratio"] - 1.0) for r in found), default=None),
       "import": {k: v for k, v in stats.items() if k != "skip_reasons"}, "unites": res}
json.dump(rep, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
sys.stdout.write("FIN_CHECK pire écart de centre %s m, %d unités d'origine, %d importées\n" % (rep["pire_ecart_centre_m"], len(orig), len(new)))
sys.stdout.flush()
os._exit(0)
