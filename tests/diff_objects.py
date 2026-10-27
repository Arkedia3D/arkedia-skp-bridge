# -*- coding: utf-8 -*-
"""Compare, objet par objet, deux fichiers .skp relus dans Blender : surface, volume signé, sens des faces.

blender -b --factory-startup --python diff_objects.py -- <rapport.json> <référence.skp> <autre.skp> [nodrop]

Avec « nodrop », l'import garde les versos dupliqués (option « Ignorer les faces arrière dupliquées » décochée).

Sert à comprendre un écart de volume entre un fichier et sa copie réenregistrée par SketchUp : l'aire et la boîte
englobante peuvent rester identiques alors que des faces sont retournées (le volume signé change, et avec lui
l'orientation des normales dans Blender). Pour chaque objet commun, le rapport donne l'aire, le volume signé
(corrigé du signe du déterminant, donc juste pour les miroirs) et le nombre de faces dont la normale est inversée
d'un fichier à l'autre (faces appariées par leur centre).
"""
import sys, os, json, traceback

ARGS = sys.argv[sys.argv.index("--") + 1:]
REPORT, REF, OTHER = ARGS[0], ARGS[1], ARGS[2]
NODROP = "nodrop" in ARGS[3:]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()

import bpy  # noqa: E402
import numpy as np  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402


def collect():
    bpy.context.view_layer.update()
    sl = bpy.context.scene.unit_settings.scale_length
    out = {}
    for ob in bpy.data.objects:
        if ob.type != "MESH" or len(ob.data.polygons) == 0:
            continue
        me = ob.data
        M = np.array(ob.matrix_world, dtype=np.float64)
        R = M[:3, :3]
        det = float(np.linalg.det(R))
        sgn = 1.0 if det >= 0 else -1.0
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        ti = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", ti)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        P = co.reshape(-1, 3).astype(np.float64)[ti.reshape(-1, 3)] @ R.T + M[:3, 3]
        c = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        area = 0.5 * np.sqrt((c * c).sum(1)).sum()
        vol = sgn * (P[:, 0] * c).sum() / 6.0
        npoly = len(me.polygons)
        cen = np.empty(npoly * 3, np.float32)
        nor = np.empty(npoly * 3, np.float32)
        me.polygons.foreach_get("center", cen)
        me.polygons.foreach_get("normal", nor)
        cen_w = cen.reshape(-1, 3).astype(np.float64) @ R.T + M[:3, 3]
        nor_w = nor.reshape(-1, 3).astype(np.float64) @ np.linalg.inv(R)  # normales : (R^-1)^T appliqué en ligne
        nn = np.linalg.norm(nor_w, axis=1)
        nn[nn == 0] = 1.0
        nor_w = nor_w / nn[:, None]
        out[ob.name] = {"aire": float(area * sl * sl), "volume": float(vol * sl ** 3), "det": det,
                        "n_faces": npoly, "centres": cen_w * sl, "normales": nor_w}
    return out


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    A.import_skp(path, bpy.context, drop_back_faces=not NODROP, memory_check=False)
    return collect()


def main():
    rep = {"blender": bpy.app.version_string, "reference": os.path.basename(REF), "autre": os.path.basename(OTHER),
           "objets": [], "resume": {}}
    try:
        a = load(REF)
        b = load(OTHER)
        rep["resume"]["objets_reference"] = len(a)
        rep["resume"]["objets_autre"] = len(b)
        rep["resume"]["absents_de_autre"] = sorted(set(a) - set(b))[:20]
        rep["resume"]["absents_de_reference"] = sorted(set(b) - set(a))[:20]
        flips_tot, faces_tot, vol_a, vol_b = 0, 0, 0.0, 0.0
        for name in sorted(set(a) & set(b)):
            x, y = a[name], b[name]
            key = lambda arr: {tuple(np.round(r, 4)): i for i, r in enumerate(arr)}
            ka, kb = key(x["centres"]), key(y["centres"])
            common = set(ka) & set(kb)
            flips = 0
            for k in common:
                if float(np.dot(x["normales"][ka[k]], y["normales"][kb[k]])) < 0:
                    flips += 1
            row = {"objet": name, "faces": [x["n_faces"], y["n_faces"]], "apparies": len(common), "inversees": flips,
                   "aire": [round(x["aire"], 6), round(y["aire"], 6)],
                   "volume": [round(x["volume"], 6), round(y["volume"], 6)],
                   "det": [round(x["det"], 3), round(y["det"], 3)]}
            flips_tot += flips
            faces_tot += len(common)
            vol_a += x["volume"]
            vol_b += y["volume"]
            if flips or abs(x["volume"] - y["volume"]) > 1e-6 or abs(x["aire"] - y["aire"]) > 1e-6:
                rep["objets"].append(row)
        rep["resume"].update({"faces_appariees": faces_tot, "faces_inversees": flips_tot,
                              "volume_somme_reference": round(vol_a, 6), "volume_somme_autre": round(vol_b, 6),
                              "objets_differents": len(rep["objets"])})
        rep["statut"] = "OK"
    except BaseException as exc:  # noqa
        rep["statut"] = "ERREUR"
        rep["erreur"] = "%s: %s" % (type(exc).__name__, exc)
        rep["trace"] = traceback.format_exc()[-2500:]
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sys.stdout.write("FIN %s\n" % rep["statut"])
    sys.stdout.flush()
    os._exit(0)


main()
