# -*- coding: utf-8 -*-
"""Résumé lisible des résultats du banc de charge.

    python summarize.py <dossier> [<dossier> ...]

Chaque dossier contient un fichier results.jsonl écrit par driver.py. Quand plusieurs dossiers sont donnés,
un même cas relancé plus tard remplace le résultat précédent (le dernier dossier l'emporte).
"""
import sys, os, json

if len(sys.argv) < 2:
    sys.exit(__doc__)

rows = {}
for out in sys.argv[1:]:
    chemin = os.path.join(out, "results.jsonl")
    for line in open(chemin, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        key = (r.get("case"), r.get("param"))
        rows.setdefault(key, {})[r.get("etape", "?")] = r


def g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


print("%-12s %-7s %-9s %8s %8s %8s %9s %7s %7s %9s %6s %6s" % (
    "cas", "param", "statut", "exp_s", "taille", "imp_s", "air/orig", "vol", "bbox_m", "chaine", "pic_e", "pic_i"))
for (case, param), steps in sorted(rows.items(), key=lambda kv: str(kv[0])):
    e, i = steps.get("export", {}), steps.get("import", {})
    status = "OK" if (e.get("status") == "OK" and i.get("status", "OK") == "OK" and "import" in steps) else (
        e.get("status") if e.get("status") != "OK" else i.get("status", "?"))
    c1, c2 = g(i, "comparaison", default={}), g(i, "comparaison2", default={})
    fid = "%s" % ("fidèle" if c1.get("fidele") else ("ECART" if c1 else "-"))
    chain = "%s" % ("fidèle" if c2.get("fidele") else ("ECART" if c2 else "-"))
    exp_s = g(e, "phases", "export", "s")
    imp_s = g(i, "phases_import", "import", "s")
    print("%-12s %-7s %-9s %8s %8s %8s %9s %7s %7s %9s %6s %6s" % (
        case, param, status, exp_s, e.get("size_mb"), imp_s,
        ("%.5f" % c1["area_ratio"]) if c1.get("area_ratio") else "-",
        ("%.5f" % c1["vol_ratio"]) if c1.get("vol_ratio") else "-",
        ("%.4f" % c1["bbox_max_diff_m"]) if c1.get("bbox_max_diff_m") is not None else "-",
        chain, e.get("peak_gb"), i.get("peak_gb_import")))
    if c1 and not c1.get("fidele"):
        print("    ECART import:", json.dumps(c1))
    if c2 and not c2.get("fidele"):
        print("    ECART chaîne:", json.dumps(c2))
    if status not in ("OK",):
        print("    ", e.get("erreur") or i.get("erreur"))
