# -*- coding: utf-8 -*-
"""Chronomètre, opération par opération, la création de N objets qui partagent un maillage (comme l'import).

blender -b --factory-startup --python bench_walk.py -- <fichier.skp> <journal> [options]
options : names=orig|seq|rand  (noms d'objets : ceux du fichier, croissants, ou dans le désordre)
          sortfirst            (créer les objets dans l'ordre alphabétique des noms)
          n=40000              (limiter le nombre d'objets)
"""
import sys, os, time, gc

ARGS = sys.argv[sys.argv.index("--") + 1:]
SKP, LOGP = ARGS[0], ARGS[1]
OPT = set(ARGS[2:])
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _env  # noqa: E402
_env.setup()

LOG = open(LOGP, "w", encoding="utf-8", buffering=1)


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


import bpy, mathutils  # noqa: E402
import openskp  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

MODE = next((o.split("=")[1] for o in OPT if o.startswith("names=")), "orig")
LIMIT = next((int(o.split("=")[1]) for o in OPT if o.startswith("n=")), None)
bpy.ops.wm.read_factory_settings(use_empty=True)
log("options", sorted(OPT), "gc actif:", gc.isenabled())
t = time.time()
skp = openskp.SkpFile.open(SKP)
model = skp.parse()
scene = skp.build_instanced_scene()
log("lecture %.1f s" % (time.time() - t))
nodes = []
stack = list(reversed(scene.scene_hierarchy.children))
while stack:
    n = stack.pop()
    nodes.append(n)
    stack.extend(reversed(n.children))
if LIMIT:
    nodes = nodes[:LIMIT]
log("noeuds", len(nodes), "premiers noms:", [(x.name, x.definition_name, x.layer) for x in nodes[:3]])
resources = {r.id: r for r in scene.mesh_resources}
rid = next(n.mesh_resource_id for n in nodes if n.mesh_resource_id is not None)
names = A._material_name_lookup(model)
mesh = A._build_mesh_data(resources[rid].definition_name or rid, resources[rid], getattr(scene, "gltf_materials", None) or [],
                          names, getattr(scene, "textures", None) or [], {}, {}, True, None, 1.0)
root = bpy.data.collections.new("racine")
bpy.context.scene.collection.children.link(root)
colls = {}


def label_of(i):
    if MODE == "seq":
        return "Obj%06d" % i
    if MODE == "rand":
        return "Obj%06d" % ((i * 7919) % 100003)
    if MODE == "unpad":
        return "Obj%d" % i
    if MODE == "same":
        return "Chaise"
    if MODE == "mixed":
        pre = ["a", "B", "é", "É", "z", "Ω", "_", "1", "M", "à"]
        return pre[(i * 7919) % len(pre)] + "x%05d" % ((i * 104729) % 99991)
    nd = nodes[i]
    return nd.name or nd.definition_name or "Groupe"


order = list(range(len(nodes)))
TABLE = bytes((b + 128) & 0xFF for b in range(256))
if "sortfirst" in OPT:
    t = time.time()
    order.sort(key=label_of)
    log("tri préalable %.2f s" % (time.time() - t))
elif "keysigned" in OPT:
    order.sort(key=lambda i: label_of(i).encode("utf-8").lower().translate(TABLE) + b"\x80")
    log("tri octets signés")
elif "keyunsigned" in OPT:
    order.sort(key=lambda i: label_of(i).encode("utf-8").lower() + b"\x00")
    log("tri octets non signés")
acc = {"lecture_noeud": 0.0, "new": 0.0, "link": 0.0, "matrix": 0.0, "tag": 0.0}
perf = time.perf_counter
T0 = perf()
last = T0
STEP = 10000
for k, i in enumerate(order):
    node = nodes[i]
    a = perf()
    local = A._gltf_matrix_to_blender(node.matrix)
    world_b = A._YUP_TO_ZUP @ local @ A._ZUP_TO_YUP
    label = label_of(i)
    lay = node.layer or "Layer0"
    if lay not in colls:
        c = bpy.data.collections.new(lay)
        root.children.link(c)
        colls[lay] = c
    target = colls[lay]
    b = perf()
    acc["lecture_noeud"] += b - a
    obj = bpy.data.objects.new(label, mesh) if node.mesh_resource_id is not None else bpy.data.objects.new(label, None)
    c_ = perf()
    acc["new"] += c_ - b
    target.objects.link(obj)
    d = perf()
    acc["link"] += d - c_
    obj.matrix_world = world_b
    e = perf()
    acc["matrix"] += e - d
    if node.guid:
        obj["skp_guid"] = node.guid
    obj["skp_layer"] = lay
    f = perf()
    acc["tag"] += f - e
    if (k + 1) % STEP == 0:
        now = perf()
        log("[%7d objets, +%.1f s, total %.1f s] %s" % (k + 1, now - last, now - T0, " ".join("%s=%.1f" % (kk, v) for kk, v in acc.items())))
        last = now
        for kk in acc:
            acc[kk] = 0.0
now = perf()
log("[fin %d objets, total %.1f s] reste %s" % (len(nodes), now - T0, " ".join("%s=%.1f" % (kk, v) for kk, v in acc.items())))
log("FIN")
os._exit(0)
