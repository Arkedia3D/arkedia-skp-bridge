# -*- coding: utf-8 -*-
"""Garde-fou mémoire de l'import : décision pour plusieurs fichiers, avec la mémoire réelle puis une mémoire simulée.

blender -b --factory-startup --python guard_test.py -- <journal> <fichier.skp> [<fichier.skp> ...]
"""
import sys, os
ARGS = sys.argv[sys.argv.index("--") + 1:]
LOGP, FILES = ARGS[0], ARGS[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()
import bpy  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

LOG = open(LOGP, "w", encoding="utf-8")
real = A._available_memory_bytes
LOG.write("mémoire disponible réelle : %.1f Go\n" % (real() / 2 ** 30))
for label, avail in (("réelle", None), ("simulée 4 Go", 4 * 2 ** 30), ("simulée 8 Go", 8 * 2 ** 30), ("simulée 16 Go", 16 * 2 ** 30)):
    A._available_memory_bytes = (lambda a=avail: a) if avail is not None else real
    for f in FILES:
        size = os.path.getsize(f) / 2 ** 20
        try:
            A._check_import_memory(f)
            verdict = "accepté"
        except MemoryError as exc:
            verdict = "REFUSÉ : " + str(exc)[:140]
        LOG.write("[%s] %s (%.0f Mo) -> %s\n" % (label, os.path.basename(f), size, verdict))
LOG.write("FIN\n")
LOG.flush()
os._exit(0)
