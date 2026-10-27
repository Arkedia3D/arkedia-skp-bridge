# -*- coding: utf-8 -*-
"""Sens des boucles de faces tel que openskp les lit : le contour reconstitué tourne-t-il dans le sens de la normale ?

blender -b --factory-startup --python dump_faces.py -- <rapport.json> <fichier.skp> [<fichier.skp> ...]

Pour chaque face de chaque définition, calcule la normale de Newell du contour extérieur (dans l'ordre où openskp
reconstitue les sommets à partir des arêtes et de leur sens) et la compare à la normale enregistrée dans le fichier.
Un accord signifie que les triangles issus d'une boucle simple (triangle, quadrilatère, polygone convexe) sont
orientés comme le plan de la face ; un désaccord, qu'ils sortent retournés.
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
from openskp._face_groups import reconstruct_loop_vertices  # noqa: E402


def newell(P):
    n = np.zeros(3)
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return n


def analyse(path):
    skp = openskp.SkpFile.open(path)
    model = skp.parse()
    res = {"version": model.version, "units": model.units, "definitions": 0, "faces": 0, "accord": 0, "desaccord": 0,
           "sans_normale": 0, "par_forme": {}, "exemples": []}
    par_forme = Counter()
    defs = list(model.definitions.values()) + [model.root]
    for d in defs:
        res["definitions"] += 1
        edges = {eid: (e.v1_id, e.v2_id) for eid, e in d.edges.items()}
        for fid, f in d.faces.items():
            res["faces"] += 1
            if not f.normal or not any(f.normal):
                res["sans_normale"] += 1
                continue
            if not f.loops:
                continue
            ids = reconstruct_loop_vertices(f.loops[0], edges)
            if len(ids) < 3 or any(i not in d.vertices for i in ids):
                continue
            P = np.array([[d.vertices[i].x, d.vertices[i].y, d.vertices[i].z] for i in ids])
            n = newell(P)
            ok = float(np.dot(n, np.array(f.normal))) > 0
            shape = "tri" if len(ids) == 3 and len(f.loops) == 1 else ("quad" if len(ids) == 4 and len(f.loops) == 1
                                                                     else ("trous" if len(f.loops) > 1 else "poly"))
            par_forme[(shape, ok)] += 1
            if ok:
                res["accord"] += 1
            else:
                res["desaccord"] += 1
                if len(res["exemples"]) < 8:
                    res["exemples"].append({"def": d.name, "face": fid, "boucles": len(f.loops), "sommets": len(ids),
                                            "normale_fichier": [round(v, 4) for v in f.normal],
                                            "newell": [round(float(v), 4) for v in n / (np.linalg.norm(n) or 1)]})
    res["par_forme"] = {"%s:%s" % (k[0], "accord" if k[1] else "desaccord"): v for k, v in sorted(par_forme.items())}
    return res


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
