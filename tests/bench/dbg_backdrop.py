# -*- coding: utf-8 -*-
"""Diagnostic de l'écartement des versos dupliqués : quels triangles sont retirés, et dans quelle primitive ?

blender -b --factory-startup --python dbg_backdrop.py -- <rapport.json> <fichier.skp> [<fichier.skp> ...]

Pour chaque ressource de maillage : la liste des primitives (couleur, nom SketchUp ou non, simple ou double face,
nombre de triangles) et, pour les triangles écartés, la primitive d'où ils viennent.
"""
import sys, os, json, traceback
from collections import Counter

ARGS = sys.argv[sys.argv.index("--") + 1:]
REPORT, FILES = ARGS[0], ARGS[1:]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import _env  # noqa: E402
_env.setup()

import numpy as np  # noqa: E402
import openskp  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402


def analyse(path):
    skp = openskp.SkpFile.open(path)
    model = skp.parse()
    scene = A._instanced_scene(skp)
    names = A._material_name_lookup(model)
    gm = getattr(scene, "gltf_materials", None) or []
    out = {"noms_materiaux": sorted(str(k) for k in names)[:30], "ressources": []}
    for res in scene.mesh_resources:
        prims = list(res.primitives)
        drops = A._back_face_drops(res, gm, names)
        info = {"definition": res.definition_name, "primitives": [], "ecartes_par_primitive": {}}
        for pi, prim in enumerate(prims):
            g = gm[prim.material_index] if 0 <= prim.material_index < len(gm) else {}
            pbr = g.get("pbrMetallicRoughness", {})
            col = pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1.0])
            nt = len(prim.indices) // 3
            info["primitives"].append({"i": pi, "couleur": [round(c * 255) for c in col[:3]] + [round(col[3] * 100)],
                                       "nomme": not A._is_unnamed_material(prim.material_index, gm, names),
                                       "double_face": bool(g.get("doubleSided")), "triangles": nt,
                                       "texture": bool(pbr.get("baseColorTexture"))})
        for pi, mask in drops.items():
            info["ecartes_par_primitive"][str(pi)] = int(mask.sum())
        out["ressources"].append(info)
    return out


def main():
    rep = {"fichiers": {}}
    for p in FILES:
        try:
            rep["fichiers"][os.path.basename(p)] = analyse(p)
        except BaseException as exc:  # noqa
            rep["fichiers"][os.path.basename(p)] = {"erreur": "%s: %s" % (type(exc).__name__, exc),
                                                     "trace": traceback.format_exc()[-1500:]}
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sys.stdout.write("FIN\n")
    sys.stdout.flush()
    os._exit(0)


main()
