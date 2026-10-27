# -*- coding: utf-8 -*-
"""Maison d'essai Arkedia : petit bâtiment complet pour valider l'export .skp dans SketchUp.

Contenu : murs triangulés à fenêtres (trous) et porte (encoche), plancher à trémie, dalle de fondation,
terrasse texturée, toiture à deux pans, annexe à toit monopente dont les sommets sont loin de l'origine
(bruit flottant), vitrages en composant partagé (4 instances tournées), chaises asymétriques (normale,
tournée, MIROIR), collection instanciée deux fois, matériaux dont un transparent, attributs perso.

Usage : blender -b --factory-startup --python feature_model.py -- <dossier_sortie>
"""
import sys, os, json, math, time, traceback

ARGS = sys.argv[sys.argv.index("--") + 1:]
OUT = ARGS[0]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
_env.setup()
os.makedirs(OUT, exist_ok=True)

import bpy, mathutils  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, geometry  # noqa: E402
import arkedia_skp_bridge as A  # noqa: E402

T = 0.25          # épaisseur des murs
H0 = 2.8          # hauteur d'étage


# ---------------------------------------------------------------- géométrie

def prism(outer, holes, depth, eu, ev, ew, o=(0.0, 0.0, 0.0), mat0=0, mat1=0, rim_mat=0):
    """Prisme droit : région plane (extérieur sens trigonométrique, trous sens horaire, coordonnées (u, v))
    extrudée de `depth` selon `ew`. Triangulé comme le ferait un export IFC.
    Retourne (sommets, triangles, indice de matériau par triangle)."""
    eu, ev, ew, o = (np.array(a, float) for a in (eu, ev, ew, o))
    V, vid, F, M = [], {}, [], []

    def P(u, v, w):
        return o + u * eu + v * ev + w * ew

    def vtx(p):
        key = tuple(np.round(p, 6))
        i = vid.get(key)
        if i is None:
            i = len(V)
            vid[key] = i
            V.append(p)
        return i

    rings = [list(outer)] + [list(h) for h in holes]
    flat = [pt for r in rings for pt in r]
    tris = geometry.tessellate_polygon([[Vector((u, v, 0.0)) for (u, v) in r] for r in rings])
    for w, want, m in ((0.0, -ew, mat0), (depth, ew, mat1)):
        for t in tris:
            ids = [vtx(P(flat[i][0], flat[i][1], w)) for i in t]
            a, b, c = (V[i] for i in ids)
            if np.dot(np.cross(b - a, c - a), want) < 0:
                ids = [ids[0], ids[2], ids[1]]
            F.append(tuple(ids))
            M.append(m)
    for ring in rings:
        n = len(ring)
        for i in range(n):
            (u0, v0), (u1, v1) = ring[i], ring[(i + 1) % n]
            exp = (v1 - v0) * eu - (u1 - u0) * ev          # normale sortante (hors matière)
            a0, a1 = vtx(P(u0, v0, 0.0)), vtx(P(u1, v1, 0.0))
            b1, b0 = vtx(P(u1, v1, depth)), vtx(P(u0, v0, depth))
            quad = [a0, a1, b1, b0]
            if np.dot(np.cross(V[a1] - V[a0], V[b0] - V[a0]), exp) < 0:
                quad = [a0, b0, b1, a1]
            F.append((quad[0], quad[1], quad[2]))
            F.append((quad[0], quad[2], quad[3]))
            mm = rim_mat(exp / np.linalg.norm(exp)) if callable(rim_mat) else rim_mat
            M += [mm, mm]
    return np.array(V), np.array(F, np.int32), np.array(M, np.int32)


def wall_arrays(L, windows=(), door=None, t=T, h=H0):
    """Mur : x le long, y épaisseur, z hauteur. Fenêtres = trous (x0, z0, w, h) ; porte = encoche (x0, w, h)."""
    outer = [(0.0, 0.0)]
    if door:
        x0, w, dh = door
        outer += [(x0, 0.0), (x0, dh), (x0 + w, dh), (x0 + w, 0.0)]
    outer += [(L, 0.0), (L, h), (0.0, h)]
    holes = [[(x0, z0), (x0, z0 + hh), (x0 + w, z0 + hh), (x0 + w, z0)] for (x0, z0, w, hh) in windows]
    return prism(outer, holes, t, (1, 0, 0), (0, 0, 1), (0, 1, 0), mat0=0, mat1=0, rim_mat=1)


def box(ox, oy, oz, sx, sy, sz, mat):
    V = np.array([[0, 0, 0], [sx, 0, 0], [sx, sy, 0], [0, sy, 0], [0, 0, sz], [sx, 0, sz], [sx, sy, sz], [0, sy, sz]], float)
    V += (ox, oy, oz)
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    F = [t for q in quads for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]
    return V, np.array(F, np.int32), np.full(len(F), mat, np.int32)


def merge(parts):
    Vs, Fs, Ms, off = [], [], [], 0
    for V, F, M in parts:
        Vs.append(V)
        Fs.append(F + off)
        Ms.append(M)
        off += len(V)
    return np.concatenate(Vs), np.concatenate(Fs), np.concatenate(Ms)


def chair_arrays():
    """Chaise asymétrique : un accoudoir côté +x seulement (sert à repérer un miroir). 0 bois, 1 tissu."""
    parts = [box(dx, dy, 0.0, 0.04, 0.04, 0.43, 0) for dx in (0.0, 0.40) for dy in (0.0, 0.40)]
    parts += [box(0.0, 0.0, 0.43, 0.44, 0.44, 0.04, 1),        # assise
              box(0.0, 0.40, 0.47, 0.44, 0.04, 0.45, 0),       # dossier
              box(0.40, 0.04, 0.62, 0.04, 0.34, 0.04, 0),      # accoudoir (côté +x)
              box(0.40, 0.30, 0.47, 0.04, 0.04, 0.15, 0)]      # montant d'accoudoir
    return merge(parts)


def table_arrays():
    parts = [box(dx, dy, 0.0, 0.05, 0.05, 0.72, 0) for dx in (0.0, 0.95) for dy in (0.0, 0.65)]
    parts.append(box(-0.05, -0.05, 0.72, 1.15, 0.75, 0.04, 0))
    return merge(parts)


def lean_roof(X0, Y0, X1, Y1, z0, ax, ay, thick, nx, ny, top_mat, other_mat):
    """Toit monopente maillé (grille triangulée, plan incliné) : sert aux faces presque planes loin de l'origine."""
    xs = np.linspace(X0, X1, nx + 1)
    ys = np.linspace(Y0, Y1, ny + 1)
    XX, YY = np.meshgrid(xs, ys)
    ZT = z0 + ax * (XX - X0) + ay * (YY - Y0)
    top = np.stack([XX.ravel(), YY.ravel(), ZT.ravel()], 1)
    bot = top - (0, 0, thick)
    V = np.concatenate([top, bot])
    nvp = len(top)
    idx = np.arange(nvp).reshape(ny + 1, nx + 1)
    F, M = [], []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx[j, i], idx[j, i + 1], idx[j + 1, i + 1], idx[j + 1, i]
            F += [(a, b, c), (a, c, d)]
            M += [top_mat, top_mat]
            F += [(a + nvp, c + nvp, b + nvp), (a + nvp, d + nvp, c + nvp)]
            M += [other_mat, other_mat]
    ring = [idx[0, i] for i in range(nx)] + [idx[j, nx] for j in range(ny)] + \
           [idx[ny, i] for i in range(nx, 0, -1)] + [idx[j, 0] for j in range(ny, 0, -1)]
    for k in range(len(ring)):
        p, q = ring[k], ring[(k + 1) % len(ring)]
        F += [(p, p + nvp, q + nvp), (p, q + nvp, q)]
        M += [other_mat, other_mat]
    return V, np.array(F, np.int32), np.array(M, np.int32)


# ---------------------------------------------------------------- Blender

def srgb(r, g, b):
    return tuple(A._srgb_to_linear(c / 255.0) for c in (r, g, b))


def material(name, rgb, alpha=1.0, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = A._principled(m, create=False)
    lin = srgb(*rgb)
    b.inputs["Base Color"].default_value = (*lin, 1.0)
    b.inputs["Alpha"].default_value = alpha
    m.diffuse_color = (*lin, alpha)
    if image is not None:
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        m.node_tree.links.new(tex.outputs["Color"], b.inputs["Base Color"])
    return m


def parquet_image():
    n = 64
    px = np.zeros((n, n, 4), np.float32)
    px[..., 3] = 1.0
    tones = [(0.55, 0.36, 0.20), (0.62, 0.42, 0.24), (0.48, 0.30, 0.16), (0.58, 0.39, 0.22)]
    for y in range(n):
        plank = y // 16
        for x in range(n):
            shift = (x + plank * 21) // 32
            c = tones[(plank + shift) % 4]
            px[y, x, :3] = A._srgb_to_linear(c[0]), A._srgb_to_linear(c[1]), A._srgb_to_linear(c[2])
    px[::16, :, :3] *= 0.45          # joints entre lames
    img = bpy.data.images.new("Parquet", n, n)
    img.pixels.foreach_set(px.ravel())
    return img


def make_mesh(name, V, F, M, slots, uv_scale=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F.tolist() if hasattr(F, "tolist") else F)
    for m in slots:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", np.asarray(M, np.int32))
    if uv_scale is not None:
        uv = me.uv_layers.new(name="UVMap")
        loops = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", loops)
        co = np.asarray(V, float)[loops][:, :2] * uv_scale
        uv.data.foreach_set("uv", co.astype(np.float32).ravel())
    me.update()
    return me


def collection(name, exclude=False):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    if exclude:
        bpy.context.view_layer.layer_collection.children[name].exclude = True
    return c


def obj(name, me, coll, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), parent=None, props=None):
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    ob.location = loc
    ob.rotation_euler = rot
    ob.scale = scale
    for k, v in (props or {}).items():
        ob[k] = v
    return ob


def build():
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    img = parquet_image()
    MAT = {
        "enduit": material("Enduit blanc", (236, 232, 222)),
        "beton": material("Béton brut", (158, 158, 152)),
        "tuile": material("Tuile terre cuite", (158, 56, 30)),
        "verre": material("Verre teinté", (140, 190, 215), alpha=0.35),
        "parquet": material("Parquet terrasse", (255, 255, 255), image=img),
        "bois": material("Bois chaise", (115, 76, 38)),
        "tissu": material("Tissu bleu", (50, 90, 150)),
    }
    C = {n: collection(n) for n in ("Niveau 0 Murs", "Niveau 1 Murs", "Dalles", "Toiture", "Menuiseries", "Mobilier", "Annexe")}
    src = collection("Sources (source geometry)", exclude=True)
    ens = bpy.data.collections.new("Ensemble_Table")
    src.children.link(ens)

    # --- murs du rez-de-chaussée (triangulés, fenêtres = trous, porte = encoche)
    W = [MAT["enduit"], MAT["beton"]]
    specs = [
        ("Mur_Sud", 8.0, [(4.0, 0.9, 1.4, 1.2)], (1.0, 0.9, 2.1), (0, 0, 0), 0.0,
         {"IfcClass": "IfcWall", "Reference": "M-S-01", "REI": "60", "Porteur": 1, "Hauteur_m": 2.8}),
        ("Mur_Nord", 8.0, [(1.2, 0.9, 1.4, 1.2), (5.0, 0.9, 1.4, 1.2)], None, (8.0, 6.0, 0), math.pi,
         {"IfcClass": "IfcWall", "Reference": "M-N-01", "REI": "60", "Porteur": 1}),
        ("Mur_Est", 6.0, [(2.3, 0.9, 1.4, 1.2)], None, (8.0, 0.0, 0), math.pi / 2,
         {"IfcClass": "IfcWall", "Reference": "M-E-01", "Porteur": 1}),
        ("Mur_Ouest", 6.0, [], None, (0.0, 6.0, 0), -math.pi / 2,
         {"IfcClass": "IfcWall", "Reference": "M-O-01", "Porteur": 0}),
    ]
    walls = {}
    for name, L, wins, door, loc, rz, props in specs:
        V, F, M = wall_arrays(L, windows=wins, door=door)
        walls[name] = (obj(name, make_mesh(name, V, F, M, W), C["Niveau 0 Murs"], loc, (0, 0, rz), props=props), wins)

    # --- murs de l'étage
    for name, L, wins, loc, rz in (("Mur_Sud_R1", 8.0, [(1.0, 0.9, 1.4, 1.2), (5.6, 0.9, 1.4, 1.2)], (0, 0, 3.0), 0.0),
                                   ("Mur_Nord_R1", 8.0, [(2.0, 0.9, 1.4, 1.2)], (8.0, 6.0, 3.0), math.pi)):
        V, F, M = wall_arrays(L, windows=wins)
        obj(name, make_mesh(name, V, F, M, W), C["Niveau 1 Murs"], loc, (0, 0, rz),
            props={"IfcClass": "IfcWall", "Niveau": "R+1"})

    # --- vitrages : un seul maillage, quatre instances (composant partagé, tournées avec les murs)
    V, F, M = box(0.0, 0.0, 0.0, 1.4, 0.02, 1.2, 0)
    vitre = make_mesh("Vitre_1400x1200", V, F, M, [MAT["verre"]])
    for wname in ("Mur_Sud", "Mur_Nord", "Mur_Est"):
        wob, wins = walls[wname]
        for i, (x0, z0, w, hh) in enumerate(wins):
            if wname == "Mur_Nord" and i == 1:
                continue            # 3 fenêtres vitrées sur 4
            obj("Vitre_%s_%d" % (wname[4:], i), vitre, C["Menuiseries"], (x0, T / 2 - 0.01, z0), parent=wob,
                props={"IfcClass": "IfcWindow"})

    # --- dalle de fondation, plancher R+1 à trémie, terrasse texturée
    B = [MAT["beton"]]
    V, F, M = prism([(-0.25, -0.25), (8.25, -0.25), (8.25, 6.25), (-0.25, 6.25)], [], 0.2, (1, 0, 0), (0, 1, 0), (0, 0, 1), o=(0, 0, -0.2))
    obj("Dalle_RDC", make_mesh("Dalle_RDC", V, F, M, B), C["Dalles"], props={"IfcClass": "IfcSlab"})
    V, F, M = prism([(0, 0), (8, 0), (8, 6), (0, 6)], [[(5.5, 1.0), (5.5, 3.4), (6.5, 3.4), (6.5, 1.0)]], 0.2,
                    (1, 0, 0), (0, 1, 0), (0, 0, 1), o=(0, 0, 2.8))
    obj("Plancher_R1", make_mesh("Plancher_R1", V, F, M, B), C["Dalles"],
        props={"IfcClass": "IfcSlab", "Trémie": "escalier 1,0 x 2,4 m"})
    V, F, M = prism([(-0.25, -3.0), (8.25, -3.0), (8.25, -0.25), (-0.25, -0.25)], [], 0.1, (1, 0, 0), (0, 1, 0), (0, 0, 1),
                    o=(0, 0, -0.1), mat0=0, mat1=1, rim_mat=0)
    obj("Terrasse", make_mesh("Terrasse", V, F, M, [MAT["beton"], MAT["parquet"]], uv_scale=2.0), C["Dalles"],
        props={"IfcClass": "IfcSlab", "Finition": "parquet"})

    # --- toiture à deux pans (extrusion d'un profil le long de x)
    prof = [(-0.4, 5.65), (3.0, 7.25), (6.4, 5.65), (6.4, 5.8), (3.0, 7.4), (-0.4, 5.8)]
    V, F, M = prism(prof, [], 8.8, (0, 1, 0), (0, 0, 1), (1, 0, 0), o=(-0.4, 0, 0), mat0=0, mat1=0,
                    rim_mat=lambda n: 1 if n[2] > 0.3 else 0)
    obj("Toiture_2pans", make_mesh("Toiture_2pans", V, F, M, [MAT["enduit"], MAT["tuile"]]), C["Toiture"],
        props={"IfcClass": "IfcRoof", "Pente_deg": 25.2})

    # --- annexe : sommets à ~360 m de l'origine, objet ramené par sa position (comme un maillage d'IFC géoréférencé)
    OX, OY = 350.0, 200.0
    x0, y0, x1, y1, t = 8.6 + OX, 0.5 + OY, 12.6 + OX, 4.5 + OY, 0.2
    V, F, M = prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [[(x0 + t, y0 + t), (x0 + t, y1 - t), (x1 - t, y1 - t), (x1 - t, y0 + t)]],
                    2.6, (1, 0, 0), (0, 1, 0), (0, 0, 1))
    obj("Annexe_Murs", make_mesh("Annexe_Murs", V, F, M, [MAT["beton"]]), C["Annexe"], loc=(-OX, -OY, 0),
        props={"IfcClass": "IfcWall", "Note": "sommets loin de l'origine"})
    V, F, M = lean_roof(x0 - 0.2, y0 - 0.2, x1 + 0.2, y1 + 0.2, 2.75, 0.05, 0.03, 0.15, 10, 8, 1, 0)
    obj("Annexe_Toit", make_mesh("Annexe_Toit", V, F, M, [MAT["beton"], MAT["tuile"]]), C["Annexe"], loc=(-OX, -OY, 0),
        props={"IfcClass": "IfcRoof", "Note": "plan incliné, grille triangulée"})

    # --- mobilier : trois chaises (normale, tournée, miroir) + collection instanciée deux fois
    V, F, M = chair_arrays()
    chaise = make_mesh("Chaise", V, F, M, [MAT["bois"], MAT["tissu"]])
    obj("Chaise_normale", chaise, C["Mobilier"], (1.0, -1.6, 0.0), props={"IfcClass": "IfcFurniture"})
    obj("Chaise_tournee45", chaise, C["Mobilier"], (2.8, -1.6, 0.0), (0, 0, math.radians(45)), props={"IfcClass": "IfcFurniture"})
    obj("Chaise_miroir", chaise, C["Mobilier"], (4.9, -1.6, 0.0), scale=(-1, 1, 1), props={"IfcClass": "IfcFurniture", "Note": "échelle x = -1"})
    V, F, M = table_arrays()
    table = make_mesh("Table", V, F, M, [MAT["bois"]])
    obj("Table_src", table, ens, (0.0, 0.0, 0.0))
    obj("Chaise_src_A", chaise, ens, (-0.2, -0.65, 0.0))
    obj("Chaise_src_B", chaise, ens, (0.65, 0.95, 0.0), (0, 0, math.pi))
    for i, (loc, rz) in enumerate((((6.0, -1.8, 0.0), 0.0), ((7.3, -1.4, 0.0), math.radians(90)))):
        e = bpy.data.objects.new("Ensemble_Table_%d" % (i + 1), None)
        e.instance_type = "COLLECTION"
        e.instance_collection = ens
        C["Mobilier"].objects.link(e)
        e.location = loc
        e.rotation_euler = (0, 0, rz)
    bpy.context.view_layer.update()


# ---------------------------------------------------------------- mesure (copie du banc de charge)

def measure():
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    sl = bpy.context.scene.unit_settings.scale_length
    tris, area, vol, nobj = 0, 0.0, 0.0, 0
    mn, mx = np.full(3, np.inf), np.full(3, -np.inf)
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type != "MESH" or len(ob.data.polygons) == 0:
            continue
        me = ob.data
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        ti = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", ti)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        P = co.reshape(-1, 3).astype(np.float64)[ti.reshape(-1, 3)]
        M = np.array(inst.matrix_world, dtype=np.float64)
        Pw = P @ M[:3, :3].T + M[:3, 3]
        c = np.cross(Pw[:, 1] - Pw[:, 0], Pw[:, 2] - Pw[:, 0])
        area += 0.5 * np.sqrt((c * c).sum(1)).sum()
        vol += (Pw[:, 0] * c).sum() / 6.0
        flat = Pw.reshape(-1, 3)
        mn, mx = np.minimum(mn, flat.min(0)), np.maximum(mx, flat.max(0))
        tris += len(P)
        nobj += 1
    return {"mesh_objects": nobj, "tris": int(tris), "area_m2": float(area * sl * sl), "vol_abs_m3": float(abs(vol) * sl ** 3),
            "bbox_min_m": [round(float(v) * sl, 4) for v in mn], "bbox_max_m": [round(float(v) * sl, 4) for v in mx]}


def main():
    rep = {"blender": bpy.app.version_string, "addon": getattr(A, "bl_info", None) and A.bl_info.get("version")}
    t0 = time.time()
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        build()
        rep["construction_s"] = round(time.time() - t0, 2)
        m0 = measure()
        rep["origine"] = m0
        rep["objets"] = {c.name: [o.name for o in c.objects] for c in bpy.data.collections}
        rep["export_fusion"] = A.export_skp(os.path.join(OUT, "maison_test.skp"), bpy.context, only_selected=False)
        rep["export_triangles"] = A.export_skp(os.path.join(OUT, "maison_test_triangles.skp"), bpy.context,
                                               only_selected=False, merge_planar=False)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "maison_test.blend"))
        for tag in ("maison_test", "maison_test_triangles"):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            rep["import_" + tag] = A.import_skp(os.path.join(OUT, tag + ".skp"), bpy.context)
            m1 = measure()
            rep["reimport_" + tag] = m1
            rep["ecarts_" + tag] = {
                "aire": m1["area_m2"] / m0["area_m2"], "volume": m1["vol_abs_m3"] / m0["vol_abs_m3"],
                "bbox_diff_m": max(abs(a - b) for a, b in zip(m0["bbox_min_m"] + m0["bbox_max_m"], m1["bbox_min_m"] + m1["bbox_max_m"])),
                "objets": m1["mesh_objects"]}
        rep["statut"] = "OK"
    except BaseException as exc:  # noqa
        rep["statut"] = "ERREUR"
        rep["erreur"] = "%s: %s" % (type(exc).__name__, exc)
        rep["trace"] = traceback.format_exc()[-3000:]
    rep["secondes"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT, "rapport.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    os._exit(0)


main()
