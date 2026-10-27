# -*- coding: utf-8 -*-
"""Profil de la lecture openskp seule (parse puis build_instanced_scene), sans Blender.

blender -b --factory-startup --python prof_openskp.py -- <fichier.skp> <rapport.txt>
"""
import sys, os, io, time, cProfile, pstats
ARGS = sys.argv[sys.argv.index("--") + 1:]
SKP, OUT = ARGS[0], ARGS[1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _env  # noqa: E402
_env.setup()
import openskp  # noqa: E402

rep = open(OUT, "w", encoding="utf-8", buffering=1)
sk = openskp.SkpFile.open(SKP)
pr = cProfile.Profile()
t = time.time()
pr.enable()
model = sk.parse()
pr.disable()
rep.write("=== parse : %.1f s ===\n" % (time.time() - t))
for key in ("tottime", "cumulative"):
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats(key).print_stats(22)
    rep.write("--- tri par %s ---\n%s\n" % (key, s.getvalue()))
pr = cProfile.Profile()
t = time.time()
pr.enable()
scene = sk.build_instanced_scene()
pr.disable()
rep.write("=== build_instanced_scene : %.1f s ===\n" % (time.time() - t))
for key in ("tottime", "cumulative"):
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats(key).print_stats(22)
    rep.write("--- tri par %s ---\n%s\n" % (key, s.getvalue()))
rep.write("FIN\n")
rep.flush()
os._exit(0)
