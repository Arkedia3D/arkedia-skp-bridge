# -*- coding: utf-8 -*-
"""Profil de l'import d'un .skp (cProfile), pour trouver où part le temps.

blender -b --factory-startup --python prof_import.py -- <fichier.skp> <rapport.txt>
"""
import sys, os, time, io, cProfile, pstats

ARGS = sys.argv[sys.argv.index("--") + 1:]
SKP, OUT = ARGS[0], ARGS[1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _env  # noqa: E402
_env.setup()

import bpy  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
pr = cProfile.Profile()
t0 = time.time()
pr.enable()
st = A.import_skp(SKP, bpy.context, memory_check=False)
pr.disable()
dt = time.time() - t0
with open(OUT, "w", encoding="utf-8") as f:
    f.write("import %.1f s (profil actif) %s\n\n" % (dt, {k: v for k, v in st.items() if k != "skip_reasons"}))
    for key in ("cumulative", "tottime"):
        s = io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats(key).print_stats(30)
        f.write("=== tri %s ===\n%s\n" % (key, s.getvalue()))
print("FIN_PROFIL")
os._exit(0)
