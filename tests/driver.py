# -*- coding: utf-8 -*-
"""Banc de charge : pour chaque cas, un processus Blender d'export puis un autre d'import (isolés).

    python driver.py <dossier_sortie> <plafond_Go> <cas> [<cas> ...]

Un cas s'écrit « nom:paramètre » (voir harness.py pour la liste). Un « + » en fin de cas (boxes:2000+) ajoute la
chaîne complète : réexport du modèle réimporté, puis seconde réimportation. Un « ! » garde les fichiers .skp.
Le plafond de mémoire engagée (en Go) coupe le processus de test qui le dépasse.

Variables d'environnement : ARK_BLENDER (chemin de Blender), ARK_DEV et ARK_SITE (voir _env.py), ARK_SANDBOX
(profil Blender jetable), CASE_TIMEOUT (secondes par processus, 2400 par défaut).
Le résultat de chaque cas est ajouté à <dossier_sortie>/results.jsonl ; « python summarize.py <dossier_sortie> »
en fait un tableau.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _env  # noqa: E402

BLENDER = _env.blender_exe()
HARNESS = os.path.join(HERE, "harness.py")
if len(sys.argv) < 4:
    raise SystemExit(__doc__)
out, cap = os.path.abspath(sys.argv[1]), sys.argv[2]
timeout = int(os.environ.get("CASE_TIMEOUT", "2400"))
cases = sys.argv[3:]
os.makedirs(out, exist_ok=True)
ENV = _env.sandbox_env()
dl = open(os.path.join(out, "driver_log.txt"), "a", encoding="utf-8", buffering=1)


def run(case, param, mode, keep):
    cmd = [BLENDER, "-b", "--factory-startup", "--python", HARNESS, "--", case, param, out, cap, mode] + (["keep"] if keep else [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=ENV)
        rc, tail = p.returncode, (p.stdout[-300:] + p.stderr[-300:]).decode("utf-8", "replace").replace("\n", " | ")
    except subprocess.TimeoutExpired:
        rc, tail = "TIMEOUT", ""
        with open(os.path.join(out, "results.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"case": case, "param": param, "status": "TIMEOUT", "etape": mode, "seconds": timeout}) + "\n")
    dl.write("  %s:%s [%s] rc=%s en %.1fs %s\n" % (case, param, mode, rc, time.time() - t0, "" if rc == 0 else tail))
    return rc


for spec in cases:
    keep = spec.endswith("!")
    chain = "+" in spec
    spec = spec.rstrip("!").replace("+", "")
    case, _, param = spec.partition(":")
    param = param or "0"
    dl.write("DEBUT %s:%s\n" % (case, param))
    rc = run(case, param, "export", keep)
    partial = os.path.join(out, "partial_%s_%s.json" % (case, param.replace(":", "_")))
    if rc == 0 and os.path.exists(partial):
        run(case, param, "chain" if chain else "import", keep)
dl.write("TOUT_FINI\n")
dl.close()
