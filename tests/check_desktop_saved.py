# -*- coding: utf-8 -*-
"""Relit dans Blender des fichiers .skp (ceux d'origine et leurs copies réenregistrées par SketchUp) et compare.

blender -b --factory-startup --python check_desktop_saved.py -- <rapport.json> <référence.skp> <copie.skp> [<copie.skp> ...]

Le premier fichier sert de référence. Pour chaque fichier on réimporte la scène, puis on mesure ce qui s'affiche :
nombre d'objets maillés, de triangles, aire totale, volume, boîte englobante, matériaux, collections. Les rapports
(copie / référence) valent 1 quand SketchUp n'a rien déformé en réenregistrant, y compris dans une version plus
ancienne du format (2013, 2017, 2020, 2021).
"""
import sys, os, json, time, traceback

ARGS = sys.argv[sys.argv.index("--") + 1:]
REPORT, FILES = ARGS[0], ARGS[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()

import bpy  # noqa: E402
import numpy as np  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402


def measure():
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    sl = bpy.context.scene.unit_settings.scale_length
    tris, area, vol, nobj = 0, 0.0, 0.0, 0
    mn, mx = np.full(3, np.inf), np.full(3, -np.inf)
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
        P = co.reshape(-1, 3).astype(np.float64)[ti.reshape(-1, 3)]
        M = np.array(inst.matrix_world, dtype=np.float64)
        Pw = P @ M[:3, :3].T + M[:3, 3]
        c = np.cross(Pw[:, 1] - Pw[:, 0], Pw[:, 2] - Pw[:, 0])
        area += 0.5 * np.sqrt((c * c).sum(1)).sum()
        vol += (Pw[:, 0] * c).sum() / 6.0
        flat = Pw.reshape(-1, 3)
        mn, mx = np.minimum(mn, flat.min(0)), np.maximum(mx, flat.max(0))
        tris += len(P)
        nobj += 1
    return {"objets_maille": nobj, "triangles": int(tris), "aire_m2": float(area * sl * sl),
            "volume_abs_m3": float(abs(vol) * sl ** 3),
            "boite_min_m": [round(float(v) * sl, 4) for v in mn], "boite_max_m": [round(float(v) * sl, 4) for v in mx],
            "materiaux": len(bpy.data.materials), "collections": len(bpy.data.collections),
            "cameras": sum(1 for o in bpy.data.objects if o.type == "CAMERA")}


def main():
    rep = {"blender": bpy.app.version_string, "fichiers": []}
    ref = None
    for path in FILES:
        row = {"fichier": os.path.basename(path), "octets": os.path.getsize(path) if os.path.exists(path) else None}
        t0 = time.time()
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            st = A.import_skp(path, bpy.context, memory_check=False)
            row["import_s"] = round(time.time() - t0, 2)
            row["import"] = {k: v for k, v in st.items() if k != "skip_reasons"}
            m = measure()
            row["mesure"] = m
            if ref is None:
                ref = m
            else:
                row["rapport_aire"] = round(m["aire_m2"] / ref["aire_m2"], 6) if ref["aire_m2"] else None
                row["rapport_volume"] = round(m["volume_abs_m3"] / ref["volume_abs_m3"], 6) if ref["volume_abs_m3"] else None
                row["ecart_boite_m"] = round(max(abs(a - b) for a, b in zip(
                    ref["boite_min_m"] + ref["boite_max_m"], m["boite_min_m"] + m["boite_max_m"])), 5)
                row["rapport_triangles"] = round(m["triangles"] / ref["triangles"], 6) if ref["triangles"] else None
                row["rapport_objets"] = round(m["objets_maille"] / ref["objets_maille"], 6) if ref["objets_maille"] else None
        except BaseException as exc:  # noqa
            row["erreur"] = "%s: %s" % (type(exc).__name__, exc)
            row["trace"] = traceback.format_exc()[-1500:]
        rep["fichiers"].append(row)
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sys.stdout.write("FIN_CHECK %d fichiers\n" % len(FILES))
    sys.stdout.flush()
    os._exit(0)


main()
