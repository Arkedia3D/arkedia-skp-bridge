# -*- coding: utf-8 -*-
"""Mémoire d'un import .skp par phase (lecture openskp, scène instanciée, construction Blender).

blender -b --factory-startup --python mem_import.py -- <fichier.skp> <plafond_Go> <fichier_journal>
Un garde-fou coupe le processus si la mémoire engagée dépasse le plafond.
"""
import sys, os, time, threading, ctypes, json, gc
from ctypes import wintypes

ARGS = sys.argv[sys.argv.index("--") + 1:]
SKP, CAP_GB, LOGP = ARGS[0], float(ARGS[1]), ARGS[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()

LOG = open(LOGP, "w", encoding="utf-8", buffering=1)


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_k32, _ps = ctypes.windll.kernel32, ctypes.windll.psapi
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
_ps.GetProcessMemoryInfo.restype = wintypes.BOOL
_H = _k32.GetCurrentProcess()
PEAK = [0.0]
T0 = time.time()
PHASE = ["init"]


def commit_gb():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    _ps.GetProcessMemoryInfo(_H, ctypes.byref(pmc), pmc.cb)
    return pmc.PagefileUsage / 2 ** 30


def log(msg):
    LOG.write("[%7.1fs | %5.2f Go | pic %5.2f | %s] %s\n" % (time.time() - T0, commit_gb(), PEAK[0], PHASE[0], msg))


def watchdog():
    while True:
        c = commit_gb()
        PEAK[0] = max(PEAK[0], c)
        if c > CAP_GB:
            log("ABORT_MEMOIRE plafond %.1f Go" % CAP_GB)
            LOG.flush()
            os._exit(42)
        time.sleep(0.05)


threading.Thread(target=watchdog, daemon=True).start()

import bpy  # noqa: E402
import openskp  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

size = os.path.getsize(SKP)
log("début, fichier %.1f Mo" % (size / 2 ** 20))

_parse, _scene = openskp.SkpFile.parse, openskp.SkpFile.build_instanced_scene


def parse(self, *a, **k):
    PHASE[0] = "parse"
    log("début parse")
    r = _parse(self, *a, **k)
    log("fin parse")
    PHASE[0] = "entre"
    return r


def scene(self, *a, **k):
    PHASE[0] = "scène"
    log("début build_instanced_scene")
    r = _scene(self, *a, **k)
    log("fin build_instanced_scene")
    PHASE[0] = "blender"
    return r


openskp.SkpFile.parse, openskp.SkpFile.build_instanced_scene = parse, scene
import openskp.instanced_scene as _isc  # noqa: E402

_bis = _isc.build_instanced_scene


def scene2(*a, **k):
    PHASE[0] = "scène"
    log("début build_instanced_scene (lecture partagée)")
    r = _bis(*a, **k)
    log("fin build_instanced_scene")
    PHASE[0] = "blender"
    return r


_isc.build_instanced_scene = scene2
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    st = A.import_skp(SKP, bpy.context, memory_check=False)
    log("fin import : %s" % json.dumps(st, default=str))
    gc.collect()
    log("après gc")
except BaseException as exc:  # noqa
    log("ERREUR %s: %s" % (type(exc).__name__, exc))
log("pic final %.2f Go, soit %.1f x la taille du fichier (hors base de 0,26 Go)" % (PEAK[0], (PEAK[0] - 0.26) * 2 ** 30 / size))
LOG.flush()
os._exit(0)
