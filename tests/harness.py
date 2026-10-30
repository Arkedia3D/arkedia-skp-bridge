# -*- coding: utf-8 -*-
"""Banc de charge de l'add-on Arkedia SKP Bridge (Blender en arrière-plan, un cas par processus).

Usage : blender -b --factory-startup --python harness.py -- <cas> <param> <dossier_sortie> <plafond_Go> [keep]
Chaque cas : construit une scène, la mesure, l'exporte en .skp, vide la scène, réimporte le .skp,
mesure à nouveau et compare (surface, volume, boîte englobante, nombre de triangles).
Un garde-fou coupe le processus si la mémoire engagée dépasse le plafond.
"""
import sys, os, time, json, math, threading, ctypes, traceback, gc, collections
from ctypes import wintypes

ARGS = sys.argv[sys.argv.index("--") + 1:]
CASE, PARAM, OUTDIR = ARGS[0], ARGS[1], ARGS[2]
CAP_GB = float(ARGS[3]) if len(ARGS) > 3 else 4.0
MODE = ARGS[4] if len(ARGS) > 4 else "export"   # export | import | chain
KEEP = len(ARGS) > 5 and ARGS[5] == "keep"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()

os.makedirs(OUTDIR, exist_ok=True)
TAG = (CASE + "_" + PARAM).replace(":", "_").replace("/", "_")
LOG = open(os.path.join(OUTDIR, "log_" + TAG + "_" + MODE + ".txt"), "w", encoding="utf-8", buffering=1)
T0 = time.time()
PHASE = ["init"]
PEAK = [0.0]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_k32 = ctypes.windll.kernel32
_ps = ctypes.windll.psapi
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
_ps.GetProcessMemoryInfo.restype = wintypes.BOOL
_H = _k32.GetCurrentProcess()


def commit_gb():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    _ps.GetProcessMemoryInfo(_H, ctypes.byref(pmc), pmc.cb)
    return pmc.PagefileUsage / 2 ** 30


def log(msg):
    LOG.write("[%8.2fs | %5.2f Go | %s] %s\n" % (time.time() - T0, commit_gb(), PHASE[0], msg))
    LOG.flush()


def write_result(res):
    with open(os.path.join(OUTDIR, "results.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
    with open(os.path.join(OUTDIR, "result_" + TAG + "_" + MODE + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)


def watchdog():
    while True:
        c = commit_gb()
        if c > PEAK[0]:
            PEAK[0] = c
        if c > CAP_GB:
            LOG.write("ABORT_MEMOIRE %.2f Go > plafond %.1f Go pendant « %s »\n" % (c, CAP_GB, PHASE[0]))
            LOG.flush()
            write_result({"case": CASE, "param": PARAM, "status": "ABORT_MEMOIRE", "phase": PHASE[0],
                          "peak_gb": round(c, 2), "seconds": round(time.time() - T0, 1)})
            os._exit(42)
        time.sleep(0.05)


threading.Thread(target=watchdog, daemon=True).start()

import bpy, bmesh, mathutils  # noqa: E402
import numpy as np  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

TIMES = {}


class Phase:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        PHASE[0] = self.name
        self.t = time.time()
        log("début")
        return self

    def __exit__(self, et, ev, tb):
        dt = time.time() - self.t
        TIMES[self.name] = {"s": round(dt, 2), "gb": round(commit_gb(), 2), "peak_gb": round(PEAK[0], 2)}
        log("fin %.2fs" % dt + ((" ERREUR %s: %s" % (et.__name__, ev)) if et else ""))
        return False


# ---------------------------------------------------------------- utilitaires de scène

def wipe():
    # batch_remove : un seul passage sur les données (la suppression objet par objet est quadratique)
    for coll in (bpy.data.objects, bpy.data.collections, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras):
        ids = list(coll)
        if ids:
            bpy.data.batch_remove(ids)
    try:
        bpy.data.orphans_purge(do_recursive=True)
    except Exception:
        pass
    gc.collect()


def mats(n):
    out = []
    for i in range(n):
        m = bpy.data.materials.new("Mat_%02d" % i)
        try:
            m.use_nodes = True
        except Exception:
            pass
        col = (((i * 37) % 255) / 255.0, ((i * 91) % 255) / 255.0, ((i * 53) % 255) / 255.0, 1.0)
        b = A._principled(m, create=False)
        if b is not None:
            b.inputs["Base Color"].default_value = col
        m.diffuse_color = col
        out.append(m)
    return out


def box_arrays(sx, sy, sz, tri=True, ox=0.0, oy=0.0, oz=0.0):
    V = np.array([[0, 0, 0], [sx, 0, 0], [sx, sy, 0], [0, sy, 0],
                  [0, 0, sz], [sx, 0, sz], [sx, sy, sz], [0, sy, sz]], float) + np.array([ox, oy, oz])
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    if tri:
        F = [(q[0], q[1], q[2]) for q in quads] + [(q[0], q[2], q[3]) for q in quads]
        # ordre : deux triangles consécutifs par face
        F = [t for q in quads for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]
    else:
        F = quads
    return V, np.array(F, np.int32)


def merge_arrays(parts):
    Vs, Fs, off = [], [], 0
    for V, F in parts:
        Vs.append(V)
        Fs.append(F + off)
        off += len(V)
    return np.concatenate(Vs), np.concatenate(Fs)


def mesh_from(name, V, F):
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    return me


def link(ob, coll=None):
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def colls(n, prefix="Niveau"):
    out = []
    for i in range(n):
        c = bpy.data.collections.new("%s_%02d" % (prefix, i))
        bpy.context.scene.collection.children.link(c)
        out.append(c)
    return out


# ---------------------------------------------------------------- cas de test

def build_boxes(param):
    n = int(param)
    rng = np.random.default_rng(1)
    ms = mats(8)
    cs = colls(10)
    side = int(math.ceil(math.sqrt(n)))
    for i in range(n):
        V, F = box_arrays(rng.uniform(0.2, 5.0), rng.uniform(0.2, 5.0), rng.uniform(0.2, 3.0))
        me = mesh_from("Box_%05d" % i, V, F)
        me.materials.append(ms[i % 8])
        me.materials.append(ms[(i + 3) % 8])
        mi = np.array([0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1], np.int32)
        me.polygons.foreach_set("material_index", mi)
        me.update()
        ob = bpy.data.objects.new("Wall_%05d" % i, me)
        link(ob, cs[i % 10])
        ob.location = ((i % side) * 6.0, (i // side) * 6.0, (i % 10) * 3.2)
        ob.rotation_euler = (0.0, 0.0, float(rng.uniform(0, 6.28)))
    return {"objects": n}


def chair_arrays():
    parts = []
    for dx in (0.0, 0.4):
        for dy in (0.0, 0.4):
            parts.append(box_arrays(0.05, 0.05, 0.45, ox=dx, oy=dy))
    parts.append(box_arrays(0.45, 0.45, 0.05, oz=0.45))
    parts.append(box_arrays(0.45, 0.05, 0.5, oy=0.4, oz=0.5))
    return merge_arrays(parts)


def build_inst(param):
    n = int(param)
    ms = mats(3)
    cs = colls(5, "Zone")
    V, F = chair_arrays()
    me = mesh_from("Chaise", V, F)
    me.materials.append(ms[0])
    me.update()
    side = int(math.ceil(math.sqrt(n)))
    for i in range(n):
        ob = bpy.data.objects.new("Chaise_%06d" % i, me)
        link(ob, cs[i % 5])
        ob.location = ((i % side) * 0.8, (i // side) * 0.8, 0.0)
        ob.rotation_euler = (0.0, 0.0, (i % 7) * 0.4)
    return {"instances": n, "tris_per_instance": int(len(F))}


def build_sphere(param):
    s = int(param)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=s, radius=1.0)
    me = bpy.data.meshes.new("Sphere")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mats(1)[0])
    link(bpy.data.objects.new("Sphere", me))
    return {"tris": len(me.polygons)}


def grid_arrays(k, noise=0.0, holes=False, seed=3):
    xs = np.arange(k + 1, dtype=float)
    X, Y = np.meshgrid(xs, xs)
    Z = np.zeros_like(X)
    if noise:
        rng = np.random.default_rng(seed)
        Z = noise * (np.sin(X * 0.05) * np.cos(Y * 0.03) * 25 + rng.standard_normal(X.shape))
    V = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    idx = np.arange((k + 1) * (k + 1)).reshape(k + 1, k + 1)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]
    if holes:
        ii, jj = np.meshgrid(np.arange(k), np.arange(k), indexing="ij")
        keep = ~(((ii % 12) >= 4) & ((ii % 12) <= 7) & ((jj % 12) >= 4) & ((jj % 12) <= 7))
        a, b, c, d = a[keep], b[keep], c[keep], d[keep]
    a, b, c, d = a.ravel(), b.ravel(), c.ravel(), d.ravel()
    F = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)]).astype(np.int32)
    return V, F


def build_grid(param, noise=0.0, holes=False):
    k = int(param)
    V, F = grid_arrays(k, noise=noise, holes=holes)
    me = mesh_from("Grille", V, F)
    me.materials.append(mats(1)[0])
    link(bpy.data.objects.new("Grille", me))
    return {"tris": int(len(F)), "verts": int(len(V))}


def build_gridflat(param):
    return build_grid(param, 0.0, False)


def build_gridholes(param):
    return build_grid(param, 0.0, True)


def build_terrain(param):
    return build_grid(param, 0.02, False)


def build_degenerate(param):
    ms = mats(2)
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),  # 0-3 carré
         (2, 0, 0), (3, 0, 0), (4, 0, 0),  # 4-6 colinéaires
         (5, 0, 0), (5, 1, 0), (6, 0, 0), (5, 0, 0), (6, 0, 0), (5, 1, 0),  # 7-12 doubles (sommets coïncidents)
         (7, 0, 0), (8, 0, 0), (8, 1, 0.3), (7, 1, 0),  # 13-16 quad gauchi (non plan)
         (9, 0, 0), (10, 0, 0), (9.5, 1, 0),  # 17-19 triangle OK
         (9.5, -1, 0), (9.5, 0, 1),  # 20-21 ailerons : 3 faces sur l'arête 17-18
         (12, 0, 0), (12.00001, 0, 0), (12, 0.00001, 0),  # 22-24 micro-triangle
         (20, 0, 0), (21, 0, 0), (21, 1, 0), (20, 1, 0), (20.5, 0.5, 0),  # 25-29 polygone concave
         (30, 0, 0)]  # 30 sommet isolé
    F = [(0, 1, 2), (0, 2, 3),
         (4, 5, 6),  # zéro surface
         (7, 8, 9), (10, 11, 12),  # deux triangles de même géométrie, sommets distincts (z-fighting)
         (13, 14, 15, 16),
         (17, 18, 19), (17, 18, 20), (17, 18, 21),
         (22, 23, 24),
         (25, 26, 27, 28)]
    E = [(29, 25), (29, 27)]  # arêtes libres
    me = bpy.data.meshes.new("Degenere")
    me.from_pydata(V, E, F)
    me.validate(verbose=False)
    me.materials.append(ms[0])
    me.update()
    link(bpy.data.objects.new("Degenere", me))
    # objets vides, sans matériau, sans face
    link(bpy.data.objects.new("Vide", bpy.data.meshes.new("VideMesh")))
    V2, F2 = box_arrays(1, 1, 1)
    me2 = mesh_from("SansMateriau", V2, F2)
    ob2 = bpy.data.objects.new("SansMateriau", me2)
    link(ob2)
    ob2.location = (0, 5, 0)
    # objet non maillage (courbe, vide, caméra) : doit être ignoré sans erreur
    cu = bpy.data.curves.new("Courbe", "CURVE")
    sp = cu.splines.new("POLY")
    sp.points.add(3)
    link(bpy.data.objects.new("Courbe", cu))
    link(bpy.data.objects.new("UnVide", None))
    return {"note": "degenere", "expected_area_loss_m2": 0.5}


def build_transforms(param):
    ms = mats(4)
    V, F = box_arrays(2, 1, 0.5)

    def mk(name, loc=(0, 0, 0), rot=(0, 0, 0), sc=(1, 1, 1), parent=None):
        me = mesh_from(name, V, F)
        me.materials.append(ms[len(bpy.data.objects) % 4])
        ob = link(bpy.data.objects.new(name, me))
        ob.location, ob.rotation_euler, ob.scale = loc, rot, sc
        if parent is not None:
            ob.parent = parent
        return ob

    mk("Normal")
    mk("Miroir_X", loc=(5, 0, 0), sc=(-1, 1, 1))
    mk("Miroir_XYZ", loc=(10, 0, 0), sc=(-1, -1, -1))
    mk("Tourne_etire", loc=(15, 0, 0), rot=(0.5, 0.7, 0.9), sc=(1, 2, 3))
    p = mk("Parent", loc=(0, 10, 0), rot=(0, 0, math.radians(45)), sc=(1.5, 1.5, 1.5))
    mk("Enfant_cisaille", loc=(2, 0, 0), rot=(math.radians(30), 0, 0), sc=(2, 1, 1), parent=p)
    mk("Tres_loin", loc=(6.7e6, 5.8e5, 0))
    mk("Minuscule", loc=(0, 20, 0), sc=(0.001, 0.001, 0.001))
    o = mk("Delta", loc=(0, 25, 0))
    o.delta_location = (3, 0, 0)
    o.delta_scale = (2, 2, 2)
    o.delta_rotation_euler = (0, 0, 0.3)
    return {"objects": len(bpy.data.objects)}


def build_mm(param):
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 0.001
    ms = mats(2)
    for i, (sx, sy, sz) in enumerate(((5000, 4000, 2700), (300, 200, 2700))):
        V, F = box_arrays(sx, sy, sz)
        me = mesh_from("Piece_%d" % i, V, F)
        me.materials.append(ms[i])
        ob = link(bpy.data.objects.new("Piece_%d" % i, me))
        ob.location = (i * 6000, 0, 0)
    return {"unit_scale": 0.001}


def build_modifiers(param):
    ms = mats(3)
    V, F = box_arrays(1, 1, 1)
    me = mesh_from("Base", V, F)
    me.materials.append(ms[0])
    ob = link(bpy.data.objects.new("Reseau", me))
    m = ob.modifiers.new("Array", "ARRAY")
    m.count = 50
    m.relative_offset_displace = (1.5, 0, 0)
    mm = ob.modifiers.new("Mirror", "MIRROR")
    mm.use_axis[1] = True
    ms2 = ob.modifiers.new("Solidify", "SOLIDIFY")
    ms2.thickness = 0.05
    bv = ob.modifiers.new("Bevel", "BEVEL")
    bv.width = 0.02
    bv.segments = 2
    # sphère lissée avec subdivision
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
    me2 = bpy.data.meshes.new("SphereLissee")
    bm.to_mesh(me2)
    bm.free()
    for p in me2.polygons:
        p.use_smooth = True
    me2.materials.append(ms[1])
    ob2 = link(bpy.data.objects.new("SphereLissee", me2))
    ob2.location = (0, 10, 0)
    sub = ob2.modifiers.new("Sub", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2
    return {"modifiers": 5}


def build_texture(param):
    n = int(param)
    rng = np.random.default_rng(5)
    created = []
    for i in range(n):
        size = 2048 if i % 5 == 0 else 1024
        img = bpy.data.images.new("Tex_%02d" % i, size, size)
        px = rng.random((size, size, 4), dtype=np.float32)
        px[..., 3] = 1.0
        img.pixels.foreach_set(px.ravel())
        m = bpy.data.materials.new("Mat_tex_%02d" % i)
        m.use_nodes = True
        b = A._principled(m, create=False)
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = img
        m.node_tree.links.new(tex.outputs["Color"], b.inputs["Base Color"])
        V, F = grid_arrays(4)
        me = mesh_from("Plan_%02d" % i, V, F)
        me.materials.append(m)
        uv = me.uv_layers.new(name="UVMap")
        loops = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", loops)
        co = V[loops][:, :2] / 4.0
        uv.data.foreach_set("uv", co.astype(np.float32).ravel())
        ob = link(bpy.data.objects.new("Plan_%02d" % i, me))
        ob.location = (i * 5, 0, 0)
        created.append(size)
    return {"textures": n, "sizes": created}


def build_unicode(param):
    ms = mats(2)
    cs = []
    for nm in ("Niveau 0 / RDC é à ç", "Façades <ext> [nord]", "日本語 😀 collection", "a" * 150, "Calque|;,?`~=\""):
        c = bpy.data.collections.new(nm)
        bpy.context.scene.collection.children.link(c)
        cs.append(c)
    names = ["Mur extérieur é à ç ñ", "日本語の壁 😀", "x" * 300, "Mur", "Mur", "Mur.001", "Nom/avec/slash", "Nom\\antislash", "  espaces  ", ""]
    for i, nm in enumerate(names):
        V, F = box_arrays(1, 1, 1)
        me = mesh_from("Maillage é %d" % i, V, F)
        me.materials.append(ms[i % 2])
        ob = bpy.data.objects.new(nm or "sans nom", me)
        link(ob, cs[i % 5])
        ob.location = (i * 2, 0, 0)
        ob["note_perso"] = "valeur é à ç 😀"
        ob["entier"] = 3
        ob["liste"] = [1, 2]
        ob["longtexte"] = "description très longue " * 60
        ob["k" * 63] = "clé de 63 caractères"
        ob["emoji_long"] = "😀" * 200
        ob["chaine_254"] = "é" * 254
        ob["chaine_255"] = "é" * 255
    # masqués
    V, F = box_arrays(1, 1, 1)
    h = link(bpy.data.objects.new("Cache", mesh_from("Cache", V, F)))
    h.hide_viewport = True
    h.hide_set(True)
    return {"objects": len(bpy.data.objects)}


def build_mod(param):
    ms = mats(2)
    V, F = box_arrays(1, 1, 1)
    me = mesh_from("Base", V, F)
    me.materials.append(ms[0])
    ob = link(bpy.data.objects.new("Mod_" + param, me))
    if param == "array":
        m = ob.modifiers.new("Array", "ARRAY"); m.count = 50; m.relative_offset_displace = (1.5, 0, 0)
    elif param == "mirror":
        mm = ob.modifiers.new("Mirror", "MIRROR"); mm.use_axis[1] = True
    elif param == "solid":
        s = ob.modifiers.new("Solidify", "SOLIDIFY"); s.thickness = 0.05
    elif param == "bevel":
        bv = ob.modifiers.new("Bevel", "BEVEL"); bv.width = 0.02; bv.segments = 2
    elif param == "sub":
        sd = ob.modifiers.new("Sub", "SUBSURF"); sd.levels = 2; sd.render_levels = 2
    return {"modifier": param}


def build_collinst(param):
    """Collections instanciées : décalage d'instance, imbrication, miroir, échelle négative."""
    ms = mats(3)
    src = bpy.data.collections.new("Source_Chaise")
    V, F = chair_arrays()
    me = mesh_from("ChaiseSrc", V, F)
    me.materials.append(ms[0])
    ob = bpy.data.objects.new("ChaiseSrc", me)
    src.objects.link(ob)
    Vb, Fb = box_arrays(0.6, 0.6, 0.02, oz=0.75)
    me2 = mesh_from("PlateauSrc", Vb, Fb)
    me2.materials.append(ms[1])
    ob2 = bpy.data.objects.new("PlateauSrc", me2)
    ob2.location = (0.0, 0.0, 0.05)
    src.objects.link(ob2)
    src.instance_offset = (0.2, 0.2, 0.0)
    outer = bpy.data.collections.new("Source_Ensemble")
    e_in = bpy.data.objects.new("DansEnsemble", None)
    e_in.instance_type = "COLLECTION"
    e_in.instance_collection = src
    e_in.location = (1.0, 0.0, 0.0)
    e_in.rotation_euler = (0, 0, 0.5)
    outer.objects.link(e_in)
    # les sources sont dans le scénario réel exclues de la vue : on les met dans un lien non visible
    holder = bpy.data.collections.new("Sources (source geometry)")
    bpy.context.scene.collection.children.link(holder)
    holder.children.link(src)
    holder.children.link(outer)
    bpy.context.view_layer.layer_collection.children["Sources (source geometry)"].exclude = True
    cs = colls(2, "Zone")
    for i in range(6):
        e = bpy.data.objects.new("Chaise_inst_%d" % i, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = src if i % 2 == 0 else outer
        e.location = (i * 2.0, 0, 0)
        e.rotation_euler = (0, 0, i * 0.4)
        if i == 4:
            e.scale = (-1, 1, 1)
        if i == 5:
            e.scale = (1.5, 1.5, 1.5)
        link(e, cs[i % 2])
    return {"instances": 6}


def _prism_from_polygon(poly, z0, z1):
    """Volume fermé et orienté vers l'extérieur : un polygone shapely (trous compris) extrudé de z0 à z1."""
    import shapely
    from shapely.geometry.polygon import orient
    poly = orient(poly, 1.0)
    rings = [list(poly.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in poly.interiors]
    V, idx, F = [], {}, []
    for ring in rings:
        for x, y in ring:
            if (x, y) not in idx:
                idx[(x, y)] = len(V)
                V.append((x, y, z0))
                V.append((x, y, z1))
    for t in shapely.constrained_delaunay_triangles(poly).geoms:
        c = list(t.exterior.coords)[:-1]
        ids = [idx[q] for q in c]
        (x0, y0), (x1, y1), (x2, y2) = c
        if (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0) < 0:
            ids = ids[::-1]
        F.append((ids[2], ids[1], ids[0]))
        F.append((ids[0] + 1, ids[1] + 1, ids[2] + 1))
    for ring in rings:
        ids = [idx[q] for q in ring]
        for i in range(len(ids)):
            a, b = ids[i], ids[(i + 1) % len(ids)]
            F.append((a, b, b + 1, a + 1))
    return np.array(V, float), F


def build_pieces(param):
    """Pièces façon Bonsai : volumes « IfcSpace/… » masqués, collés au sol et aux murs (même plan, d'où le moirage),
    trois pièces rectangulaires, une en L et une qui contourne une trémie collée au mur (étranglement de 0,1 mm).
    Exportées avec l'option pièces : chacune doit revenir rentrée de 5 mm, nommée avec sa surface, sur une
    étiquette masquée ; le bâti ne bouge pas."""
    from shapely.geometry import Polygon
    ms = mats(2)
    piece = bpy.data.materials.new("Pièce")
    piece.diffuse_color = (0.55, 0.8, 0.92, 0.15)
    h, e = 2.7, 0.2
    rooms = {
        "IfcSpace/01": Polygon([(0, 0), (4, 0), (4, 3), (0, 3)]),
        "IfcSpace/02": Polygon([(4.2, 0), (8.2, 0), (8.2, 3), (4.2, 3)]),
        "IfcSpace/03": Polygon([(8.4, 0), (12.4, 0), (12.4, 3), (8.4, 3)]),
        "IfcSpace/04": Polygon([(0, 3.2), (5, 3.2), (5, 5.2), (2, 5.2), (2, 7.2), (0, 7.2)]),
        "IfcSpace/05": Polygon([(5.2, 3.2), (12.4, 3.2), (12.4, 7.2), (5.2, 7.2)],
                               [[(7, 5), (9.5, 5), (9.5, 7.1999), (7, 7.1999)]]),
    }
    expected = {}
    bati = colls(1, "Bati")[0]
    # dalle sous toutes les pièces, dessus à z = 0 ; plafond au-dessus, dessous à z = h
    Vd, Fd = box_arrays(12.4 + 2 * e, 7.2 + 2 * e, 0.2, ox=-e, oy=-e, oz=-0.2)
    sl = bpy.data.objects.new("Dalle", mesh_from("Dalle", Vd, Fd))
    sl.data.materials.append(ms[0])
    link(sl, bati)
    Vp, Fp = box_arrays(12.4 + 2 * e, 7.2 + 2 * e, 0.2, ox=-e, oy=-e, oz=h)
    pl = bpy.data.objects.new("Plafond", mesh_from("Plafond", Vp, Fp))
    pl.data.materials.append(ms[0])
    link(pl, bati)
    # un mur contre chaque côté de chaque pièce (face intérieure confondue avec la pièce)
    nmur = 0
    for nm, poly in rooms.items():
        ring = list(poly.exterior.coords)
        for (x0, y0), (x1, y1) in zip(ring[:-1], ring[1:]):
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            Vw, Fw = box_arrays(L, 0.1, h, oy=-0.1)
            ang = math.atan2(dy, dx)
            ob = bpy.data.objects.new("Mur_%d" % nmur, mesh_from("Mur_%d" % nmur, Vw, Fw))
            ob.data.materials.append(ms[1])
            ob.location = (x0, y0, 0)
            ob.rotation_euler = (0, 0, ang)
            link(ob, bati)
            nmur += 1
        V, F = _prism_from_polygon(poly, 0.0, h)
        ob = bpy.data.objects.new(nm, mesh_from(nm, V, F))
        ob.data.materials.append(piece)
        link(ob, bati)
        ob.hide_set(True)
        ob.hide_viewport = True
        x0, y0, x1, y1 = poly.bounds
        expected["Pièce " + nm.split("/", 1)[1]] = {"dims": [x1 - x0, y1 - y0, h], "aire": round(poly.area, 2)}
    return {"murs": nmur, "pieces_attendues": expected,
            "export_kw": {"export_spaces": True, "hide_spaces": True}}


def build_niveaux(param):
    """Deux niveaux façon Bonsai (collections « IfcBuildingStorey/… », sans IFC chargé) : dalle, quatre murs, une
    vitre translucide et une pièce masquée par niveau. Export par niveau avec les pièces : verso de chaque face
    peint de sa matière, une étiquette par niveau et par niveau de pièces, cinq scènes qui masquent les bonnes
    étiquettes, le nom et la surface de chaque pièce en texte."""
    from shapely.geometry import Polygon
    ms = mats(2)
    verre = bpy.data.materials.new("Vitrage")
    verre.diffuse_color = (0.8, 0.9, 0.95, 0.45)
    piece = bpy.data.materials.new("Pièce")
    piece.diffuse_color = (0.55, 0.8, 0.92, 0.15)
    racine = bpy.context.scene.collection
    h = 2.8
    textes = []
    for nom, code, z in (("Rez-de-chaussée", "R01", 0.0), ("1er étage", "E01", 3.2)):
        c = bpy.data.collections.new("IfcBuildingStorey/" + nom)
        racine.children.link(c)
        Vd, Fd = box_arrays(10.4, 6.4, 0.2, ox=-0.2, oy=-0.2, oz=z - 0.2)
        ob = bpy.data.objects.new("Dalle " + code, mesh_from("Dalle " + code, Vd, Fd))
        ob.data.materials.append(ms[0])
        link(ob, c)
        for i, (sx, sy, ox, oy) in enumerate(((10.4, 0.2, -0.2, -0.2), (10.4, 0.2, -0.2, 6.0),
                                              (0.2, 6.0, -0.2, 0.0), (0.2, 6.0, 10.0, 0.0))):
            Vw, Fw = box_arrays(sx, sy, h, ox=ox, oy=oy, oz=z)
            ob = bpy.data.objects.new("Mur %s %d" % (code, i), mesh_from("Mur %s %d" % (code, i), Vw, Fw))
            ob.data.materials.append(ms[1])
            link(ob, c)
        Vg, Fg = box_arrays(2.0, 0.02, 1.5, ox=4.0, oy=-0.3, oz=z + 0.9)
        ob = bpy.data.objects.new("Vitre " + code, mesh_from("Vitre " + code, Vg, Fg))
        ob.data.materials.append(verre)
        link(ob, c)
        V, F = _prism_from_polygon(Polygon([(0, 0), (10, 0), (10, 6), (0, 6)]), z, z + h)
        ob = bpy.data.objects.new("IfcSpace/" + code, mesh_from("IfcSpace/" + code, V, F))
        ob.data.materials.append(piece)
        link(ob, c)
        ob.hide_set(True)
        ob.hide_viewport = True
        textes.append(code + "\n" + A._fr_area(60.0))
    p_r, p_e = "Pièces - Rez-de-chaussée", "Pièces - 1er étage"
    attendu = {
        "scenes": ["Vue d'ensemble", "3D - Rez-de-chaussée", "3D - 1er étage", "Plan - Rez-de-chaussée",
                   "Plan - 1er étage"],
        "masquees": {
            "Vue d'ensemble": [p_e, p_r],
            "3D - Rez-de-chaussée": ["1er étage", p_e, p_r],
            "3D - 1er étage": [p_e, p_r],
            "Plan - Rez-de-chaussée": ["1er étage", p_e],
            "Plan - 1er étage": [p_r, "Rez-de-chaussée"],
        },
        "etiquettes": sorted(["Rez-de-chaussée", "1er étage", p_r, p_e]),
        "textes": sorted(textes),
    }
    return {"niveaux_attendus": attendu,
            "export_kw": {"layer_mode": "IFC_STOREY", "export_spaces": True, "hide_spaces": True}}


def build_presqueplan(param):
    """Arêtes presque coplanaires (0.3.1) : trois murs de 4 x 0,4 x 2,5 m dont la face avant est coupée en deux au
    milieu. Mur A : moitié droite pliée de 0,3° (même matériau), l'arête du pli doit être douce et lisse. Mur B :
    pli de 5°, arête réelle qui reste visible. Mur C : face avant plane en deux matériaux, l'arête du changement de
    matériau reste visible. Mur D : comme A, moitié droite tournée à l'envers (orientation contraire), son arête doit
    aussi être douce. Les angles droits restent visibles partout."""
    ms = mats(2)
    for nom, pli, deux, oy in (("Mur pli 0,3", 0.3, False, 0.0), ("Mur pli 5", 5.0, False, 2.0),
                               ("Mur deux matieres", 0.0, True, 4.0), ("Mur pli 0,3 envers", 0.3, None, 6.0)):
        dy = 2.0 * math.sin(math.radians(pli))
        V = [(0, oy, 0), (2, oy, 0), (4, oy + dy, 0), (0, oy, 2.5), (2, oy, 2.5), (4, oy + dy, 2.5),
             (0, oy + 0.4, 0), (4, oy + 0.4, 0), (0, oy + 0.4, 2.5), (4, oy + 0.4, 2.5)]
        F = [(0, 1, 4, 3), (1, 2, 5, 4), (7, 6, 8, 9), (0, 3, 8, 6), (2, 7, 9, 5), (0, 6, 7, 2, 1), (3, 4, 5, 9, 8)]
        if deux is None:
            F[1] = (4, 5, 2, 1)
        me = bpy.data.meshes.new(nom)
        me.from_pydata(V, [], F)
        me.update()
        me.materials.append(ms[0])
        me.materials.append(ms[1])
        if deux:
            me.polygons[1].material_index = 1
        link(bpy.data.objects.new(nom, me))
    return {"aretes_attendues": {"presque_douces_min": 2}}


BUILD = {
    "boxes": build_boxes, "inst": build_inst, "sphere": build_sphere, "gridflat": build_gridflat,
    "gridholes": build_gridholes, "terrain": build_terrain, "degenerate": build_degenerate,
    "transforms": build_transforms, "mm": build_mm, "modifiers": build_modifiers,
    "texture": build_texture, "unicode": build_unicode, "mod": build_mod, "collinst": build_collinst,
    "pieces": build_pieces, "niveaux": build_niveaux, "presqueplan": build_presqueplan,
}


# ---------------------------------------------------------------- mesure

def measure():
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    sl = bpy.context.scene.unit_settings.scale_length
    cache = {}
    tris, area, vol, nobj = 0, 0.0, 0.0, 0
    mn = np.full(3, np.inf)
    mx = np.full(3, -np.inf)
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type != "MESH":
            continue
        me = ob.data
        if len(me.polygons) == 0:
            continue
        key = me.as_pointer()
        P = cache.get(key)
        if P is None:
            me.calc_loop_triangles()
            nt = len(me.loop_triangles)
            ti = np.empty(nt * 3, np.int32)
            me.loop_triangles.foreach_get("vertices", ti)
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            P = co.reshape(-1, 3).astype(np.float64)[ti.reshape(-1, 3)]
            if len(cache) < 400:
                cache[key] = P
        M = np.array(inst.matrix_world, dtype=np.float64)
        Pw = P @ M[:3, :3].T + M[:3, 3]
        c = np.cross(Pw[:, 1] - Pw[:, 0], Pw[:, 2] - Pw[:, 0])
        area += 0.5 * np.sqrt((c * c).sum(1)).sum()
        vol += (Pw[:, 0] * c).sum() / 6.0
        flat = Pw.reshape(-1, 3)
        mn = np.minimum(mn, flat.min(0))
        mx = np.maximum(mx, flat.max(0))
        tris += len(P)
        nobj += 1
    return {"mesh_objects": nobj, "tris": int(tris), "area_m2": float(area * sl * sl),
            "vol_abs_m3": float(abs(vol) * sl ** 3),
            "bbox_min_m": [round(float(v) * sl, 4) for v in mn], "bbox_max_m": [round(float(v) * sl, 4) for v in mx]}


def compare(m0, m1, expected_loss=0.0):
    out = {}
    out["area_ratio"] = ((m1["area_m2"] + expected_loss) / m0["area_m2"]) if m0["area_m2"] else None
    out["vol_ratio"] = (m1["vol_abs_m3"] / m0["vol_abs_m3"]) if m0["vol_abs_m3"] > 1e-12 else None
    d = [abs(a - b) for a, b in zip(m0["bbox_min_m"] + m0["bbox_max_m"], m1["bbox_min_m"] + m1["bbox_max_m"])]
    out["bbox_max_diff_m"] = max(d) if d else None
    out["tri_ratio"] = (m1["tris"] / m0["tris"]) if m0["tris"] else None
    ok = (out["area_ratio"] is None or abs(out["area_ratio"] - 1) < 5e-4) and \
         (out["bbox_max_diff_m"] is None or out["bbox_max_diff_m"] < 2e-3 + 1e-6 * max(map(abs, m0["bbox_max_m"] + m0["bbox_min_m"] + [0])))
    out["fidele"] = bool(ok)
    return out


def check_pieces(attendues, inset_mm):
    """Pièces relues : nom « Pièce 01, 12,00 m² », retrait mesuré sur la boîte englobante, collection masquée."""
    out = {"attendues": len(attendues), "trouvees": 0, "retraits_mm": [], "noms": [], "masquees": True, "ok": False}
    d = inset_mm / 1000.0
    ok = True
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.name.startswith("Pièce "):
            continue
        base, _, surf = ob.name.partition(", ")
        ref = attendues.get(base)
        if ref is None:
            continue
        out["trouvees"] += 1
        out["noms"].append(ob.name)
        want = ("%.2f" % ref["aire"]).replace(".", ",") + "\u00a0m²"
        if surf != want:
            ok = False
        pts = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
        dims = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
        r = [round((ref["dims"][i] - dims[i]) / 2 * 1000, 3) for i in range(3)]
        out["retraits_mm"].append(r)
        if any(abs(x - inset_mm) > 0.05 for x in r):
            ok = False
        if not any(c.hide_viewport for c in ob.users_collection):
            out["masquees"] = False
    out["ok"] = bool(ok and out["trouvees"] == out["attendues"] and out["masquees"])
    return out


def check_niveaux(path, attendu):
    """Relit le .skp avec openskp : scènes et étiquettes qu'elles masquent, étiquettes, textes, verso des faces."""
    import openskp
    m = openskp.SkpFile.open(path).parse()
    defs = list(m.definitions.values()) + [m.root]
    nom = {i: mt.name for i, mt in m.materials_by_id.items()}
    faces = [f for d in defs for f in d.faces.values()]
    peintes = [f for f in faces if f.material_id is not None]
    out = {
        "scenes": [pg.name for pg in m.pages],
        "masquees": {pg.name: sorted(pg.hidden_layers) for pg in m.pages},
        "etiquettes": sorted(l.name for l in m.layers if l.name not in ("Layer0", "Untagged", "Sans étiquette")),
        "textes": sorted(t.text for d in defs for t in d.texts),
        "faces_matiere": len(peintes),
        "verso_peint": sum(1 for f in peintes if nom.get(f.back_material_id) == nom.get(f.material_id)),
    }
    out["ok"] = bool(
        out["scenes"] == attendu["scenes"]
        and all(out["masquees"].get(k) == sorted(v) for k, v in attendu["masquees"].items())
        and out["etiquettes"] == attendu["etiquettes"]
        and out["textes"] == attendu["textes"]
        and out["faces_matiere"] > 0 and out["verso_peint"] == out["faces_matiere"])
    return out


def check_aretes(path, attendu):
    """Relit le .skp avec openskp et classe les arêtes partagées par deux faces : presque coplanaires de même
    matériau (moins de 1°, doivent être douces), changement de matériau dans un même plan et angles francs (doivent
    rester visibles)."""
    import openskp
    m = openskp.SkpFile.open(path).parse()
    out = {"presque": 0, "presque_douces": 0, "matieres": 0, "matieres_douces": 0, "franches": 0, "franches_douces": 0}
    for d in list(m.definitions.values()) + [m.root]:
        V = d.vertices
        usage = collections.defaultdict(list)
        normales = {}
        for fid, f in d.faces.items():
            if not f.loops:
                continue
            pts = []
            for eid, sens in f.loops[0]:
                e = d.edges[eid]
                v = V[e.v1_id if sens == 1 else e.v2_id]
                pts.append((v.x, v.y, v.z))
            n = np.zeros(3)
            for i in range(len(pts)):
                a, b = np.array(pts[i]), np.array(pts[(i + 1) % len(pts)])
                n += np.cross(a, b)
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            normales[fid] = n / ln
            for loop in f.loops:
                for eid, _ in loop:
                    usage[eid].append(fid)
        for eid, fids in usage.items():
            if len(fids) != 2 or fids[0] not in normales or fids[1] not in normales:
                continue
            fa, fb = d.faces[fids[0]], d.faces[fids[1]]
            ang = math.degrees(math.acos(max(-1.0, min(1.0, abs(float(normales[fids[0]] @ normales[fids[1]]))))))
            douce = bool(d.edges[eid].soft)
            if ang < 1.0 and fa.material_id == fb.material_id:
                cle = "presque"
            elif ang < 1.0:
                cle = "matieres"
            else:
                cle = "franches"
            out[cle] += 1
            out[cle + "_douces"] += int(douce)
    out["ok"] = bool(out["presque"] >= attendu["presque_douces_min"] and out["presque_douces"] == out["presque"]
                     and out["matieres"] > 0 and out["matieres_douces"] == 0 and out["franches_douces"] == 0)
    return out


def main():
    res = {"case": CASE, "param": PARAM, "status": "OK", "blender": bpy.app.version_string}
    path = os.path.join(OUTDIR, TAG + ".skp")
    partial = os.path.join(OUTDIR, "partial_" + TAG + ".json")
    try:
        if MODE == "export":
            bpy.ops.wm.read_factory_settings(use_empty=True)
            with Phase("construction"):
                res["build"] = BUILD[CASE](PARAM)
            res["unit_scale"] = bpy.context.scene.unit_settings.scale_length
            with Phase("mesure_origine"):
                res["origine"] = measure()
            log("origine : %s" % json.dumps(res["origine"]))
            with Phase("export"):
                res["export"] = A.export_skp(path, bpy.context, only_selected=False,
                                             **(res["build"] or {}).get("export_kw", {}))
            res["size_mb"] = round(os.path.getsize(path) / 2 ** 20, 3)
            log("export : %s" % json.dumps(res["export"], default=str))
            if (res["build"] or {}).get("aretes_attendues"):
                with Phase("controle_aretes"):
                    res["aretes"] = check_aretes(path, res["build"]["aretes_attendues"])
                log("arêtes : %s" % json.dumps(res["aretes"], ensure_ascii=False))
            if (res["build"] or {}).get("niveaux_attendus"):
                with Phase("controle_niveaux"):
                    res["niveaux"] = check_niveaux(path, res["build"]["niveaux_attendus"])
                log("niveaux : %s" % json.dumps(res["niveaux"], ensure_ascii=False))
            res["phases"] = dict(TIMES)
            res["peak_gb"] = round(PEAK[0], 2)
            res["seconds"] = round(time.time() - T0, 1)
            with open(partial, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, default=str)
            write_result(dict(res, etape="export"))
        else:
            res = json.load(open(partial, encoding="utf-8"))
            res["status"] = "OK" if (res.get("niveaux") or {}).get("ok", True) else "ECART_NIVEAUX"
            if not (res.get("aretes") or {}).get("ok", True):
                res["status"] = "ECART_ARETES"
            bpy.ops.wm.read_factory_settings(use_empty=True)
            if res.get("unit_scale") and abs(res["unit_scale"] - 1.0) > 1e-12:
                bpy.context.scene.unit_settings.system = "METRIC"
                bpy.context.scene.unit_settings.scale_length = res["unit_scale"]
            with Phase("import"):
                res["import"] = A.import_skp(path, bpy.context)
            log("import : %s" % json.dumps(res["import"], default=str))
            with Phase("mesure_import"):
                res["reimport"] = measure()
            res["comparaison"] = compare(res["origine"], res["reimport"], (res.get("build") or {}).get("expected_area_loss_m2", 0.0))
            attendues = (res.get("build") or {}).get("pieces_attendues")
            if attendues:
                res["pieces"] = check_pieces(attendues, (res.get("export") or {}).get("space_inset_mm", 0.0))
                log("pièces : %s" % json.dumps(res["pieces"], ensure_ascii=False))
                if not res["pieces"]["ok"]:
                    res["status"] = "ECART_PIECES"
            log("comparaison : %s" % json.dumps(res["comparaison"]))
            if MODE == "chain":
                path2 = os.path.join(OUTDIR, TAG + "_2.skp")
                with Phase("reexport"):
                    res["reexport"] = A.export_skp(path2, bpy.context, only_selected=False)
                log("reexport : %s" % json.dumps(res["reexport"], default=str))
                with Phase("nettoyage"):
                    wipe()
                with Phase("reimport"):
                    res["import2"] = A.import_skp(path2, bpy.context)
                with Phase("mesure_reimport"):
                    res["reimport2"] = measure()
                res["comparaison2"] = compare(res["origine"], res["reimport2"], (res.get("build") or {}).get("expected_area_loss_m2", 0.0))
                log("comparaison chaîne : %s" % json.dumps(res["comparaison2"]))
                if not KEEP:
                    try:
                        os.remove(path2)
                    except OSError:
                        pass
            res["phases_import"] = dict(TIMES)
            res["peak_gb_import"] = round(PEAK[0], 2)
            res["seconds_import"] = round(time.time() - T0, 1)
            write_result(dict(res, etape="import"))
            if not KEEP:
                for fp in (path, partial):
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
    except BaseException as exc:  # noqa
        res["status"] = "ERREUR"
        res["etape"] = MODE
        res["erreur"] = "%s: %s" % (type(exc).__name__, exc)
        res["trace"] = traceback.format_exc()[-2500:]
        log("ERREUR " + res["erreur"] + "\n" + res["trace"])
        res["phases_" + MODE] = dict(TIMES)
        res["peak_gb_" + MODE] = round(PEAK[0], 2)
        write_result(res)
    LOG.close()
    os._exit(0)


main()
