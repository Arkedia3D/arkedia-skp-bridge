"""Arkedia SKP Bridge : import et export SketchUp (.skp) pour Blender.

Construit sur la bibliothèque openskp (MIT, Python pur, aucune installation de
SketchUp requise). Reprend les bonnes pratiques de deux add-ons existants :

* OpenSKP Import/Export : instanciation réelle des composants (un composant
  placé 1 000 fois coûte un seul maillage), calques SketchUp en collections,
  textures, arêtes seules, export en groupes/composants natifs.
* Sketchup_Importer (RedHaloStudio) : noms de matériaux conservés, conversion
  sRGB vers linéaire, hiérarchie des groupes, scènes en caméras.

Corrige au passage ce qui casse dans un Blender dont l'interface n'est pas en
anglais : les nœuds de shader ne sont jamais cherchés par leur nom, mais par
leur type.

Spécifique au flux scan vers CAO/BIM : attributs et GUID SketchUp conservés en
propriétés personnalisées à l'import ; à l'export, classe IFC, GlobalId, nom et
jeux de propriétés (Bonsai) écrits comme dictionnaires d'attributs SketchUp,
niveaux ou classes IFC en calques.

Copyright (C) 2026 ARKEDIA 3D.
Licence GPL-3.0-or-later : ce programme est un logiciel libre, redistribuable et modifiable selon les termes de la
Licence publique générale GNU publiée par la Free Software Foundation, version 3 ou toute version ultérieure.
Il est distribué sans aucune garantie. SketchUp est une marque de Trimble Inc., sans lien avec ce projet.
"""

from __future__ import annotations

import collections
import json
import math
import os
import tempfile
import time

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

M_PER_INCH = 0.0254
INCH_PER_M = 1.0 / M_PER_INCH

# glTF Y-up (sortie d'openskp) vers Blender Z-up : (x, y, z) -> (x, -z, y)
_YUP_TO_ZUP = mathutils.Matrix(
    (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, -1.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
)
_ZUP_TO_YUP = _YUP_TO_ZUP.inverted()


# --------------------------------------------------------------------------
# Utilitaires communs
# --------------------------------------------------------------------------


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _principled(mat, create=True):
    """Nœud Principled BSDF cherché par TYPE, jamais par nom : le nom est
    traduit dans un Blender non anglophone ("BSDF guidé" en français)."""
    nt = mat.node_tree
    if nt is None:
        return None
    for node in nt.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    if not create:
        return None
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def _scene_k(context) -> float:
    """Unités Blender -> pouces SketchUp."""
    return context.scene.unit_settings.scale_length * INCH_PER_M


def _unit_factor(context) -> float:
    """Unités Blender par mètre : 1 pour une scène en mètres, 1000 pour une scène en millimètres."""
    s = context.scene.unit_settings.scale_length
    return 1.0 / s if s > 1e-12 else 1.0


def _su(text, limit=240):
    """Chaîne acceptée par le format SKP : sans caractère de contrôle et de moins de 255 unités UTF-16.

    openskp refuse une chaîne de 255 unités ou plus ; un nom Blender peut en compter 255 et un
    texte de propriété IFC bien davantage. Une seule chaîne trop longue ferait échouer tout l'export.
    """
    s = "".join(ch if (ch >= " " and ch != "\x7f") else " " for ch in str(text))
    try:
        raw = s.encode("utf-16-le", "surrogatepass")
    except Exception:
        s = s.encode("utf-8", "replace").decode("utf-8", "replace")
        raw = s.encode("utf-16-le", "replace")
    if len(raw) // 2 <= limit:
        return s
    return raw[: (limit - 1) * 2].decode("utf-16-le", errors="ignore").rstrip() + "…"


# --------------------------------------------------------------------------
# IMPORT
# --------------------------------------------------------------------------


def _gltf_matrix_to_blender(m):
    return mathutils.Matrix(
        (
            (m[0], m[4], m[8], m[12]),
            (m[1], m[5], m[9], m[13]),
            (m[2], m[6], m[10], m[14]),
            (m[3], m[7], m[11], m[15]),
        )
    )


def _material_name_lookup(model):
    """Table (r, g, b, alpha%) -> nom SketchUp. openskp n'expose pas le nom
    des matériaux dans la scène instanciée ; on le retrouve par la couleur.

    Les fichiers SketchUp 2021 et suivants listent en plus une matière « Layer_<étiquette> » par étiquette : c'est la
    couleur d'étiquette que prennent les faces sans peinture. Ce n'est pas une matière de l'utilisateur : la garder
    ferait passer le verso non peint d'une face pour « nommé », et `_back_face_drops` écarterait alors au hasard le
    recto ou le verso (la moitié des faces d'un mur ressortaient retournées)."""
    layer_materials = set()
    for layer in getattr(model, "layers", []) or []:
        layer_name = getattr(layer, "name", None)
        if layer_name:
            layer_materials.add("Layer_" + str(layer_name))
    lookup = {}
    for m in getattr(model, "materials", []) or []:
        if getattr(m, "name", None) in layer_materials:
            continue
        try:
            r, g, b = m.color[0], m.color[1], m.color[2]
            alpha = int(round(float(m.transparency) * 100))
            lookup.setdefault((r, g, b, alpha), m.name)
        except Exception:
            continue
    return lookup


def _texture_image(texture_index, textures, image_cache):
    if texture_index in image_cache:
        return image_cache[texture_index]
    if textures is None or not (0 <= texture_index < len(textures)):
        return None
    tex = textures[texture_index]
    ext = ".png" if tex.mime_type == "image/png" else ".jpg"
    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(tex.data)
        image = bpy.data.images.load(path)
        image.pack()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    image.name = (os.path.basename(tex.filename) if tex.filename else "") or f"skp_texture_{texture_index}"
    image_cache[texture_index] = image
    return image


def _build_material(index, gltf_materials, names, textures, image_cache, cache):
    if index in cache:
        return cache[index]
    gm = gltf_materials[index] if 0 <= index < len(gltf_materials) else {}
    pbr = gm.get("pbrMetallicRoughness", {})
    r, g, b, a = pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1.0])
    key = (round(r * 255), round(g * 255), round(b * 255), int(round(a * 100)))
    name = names.get(key) or f"skp_material_{index}"

    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    lin = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))
    mat.diffuse_color = (*lin, a)
    if a < 1.0:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        elif hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
    if gm.get("doubleSided") is False and hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = True

    bsdf = _principled(mat) if mat.node_tree else None
    if bsdf is not None:
        tex_ref = pbr.get("baseColorTexture")
        image = _texture_image(tex_ref.get("index"), textures, image_cache) if tex_ref else None
        if image is not None:
            tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex_node.image = image
            tex_node.location = (bsdf.location.x - 320, bsdf.location.y)
            mat.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            if image.depth in (32, 128):
                mat.node_tree.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
        else:
            bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
            bsdf.inputs["Alpha"].default_value = a
        bsdf.inputs["Roughness"].default_value = float(pbr.get("roughnessFactor", 0.8))
        bsdf.inputs["Metallic"].default_value = float(pbr.get("metallicFactor", 0.0))
    cache[index] = mat
    return mat


def _buf(values, dtype):
    """Tableau numpy sur un tampon openskp (bytes, array ou liste)."""
    import numpy as np

    try:
        return np.frombuffer(values, dtype=dtype)
    except (TypeError, ValueError, AttributeError):
        return np.asarray(values, dtype=dtype)


_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB


def _mix64(x):
    """Mélange de bits (finaliseur splitmix64) sur un tableau uint64 : bijectif, sans collision en pratique."""
    import numpy as np

    with np.errstate(over="ignore"):
        x = x ^ (x >> np.uint64(30))
        x = x * np.uint64(_MIX_A)
        x = x ^ (x >> np.uint64(27))
        x = x * np.uint64(_MIX_B)
        x = x ^ (x >> np.uint64(31))
    return x


def _vertex_hashes(pos, scale=1e5):
    """Empreinte 64 bits de chaque position (arrondie au 1/scale de mètre) : deux sommets confondus ont la même."""
    import numpy as np

    q = np.round(pos * scale).astype(np.int64).astype(np.uint64)
    with np.errstate(over="ignore"):
        return _mix64(q[:, 2] + _mix64(q[:, 1] + _mix64(q[:, 0])))


def _back_face_drops(resource, gltf_materials, names):
    """Triangles qui ne sont que le verso (copie retournée) d'une autre face de la même ressource.

    openskp émet deux jeux de triangles quand le recto d'une face est peint et son verso non (ou
    d'une autre couleur) : dans Blender, cela double toute la géométrie et crée des faces
    coïncidentes. On repère chaque triangle qui existe aussi en sens inverse et on en écarte un des
    deux : celui dont la matière n'a pas de nom SketchUp (couleur par défaut), sinon celui de la
    primitive la plus tardive. Les empreintes sont des hachages 64 bits bien mélangés (un
    hachage spatial classique perdait un tiers des sommets d'une sphère par collisions) et les
    groupes de plus de deux triangles identiques (faces coïncidentes dans le modèle d'origine)
    sont appariés recto contre verso, un par un.

    Renvoie {indice de primitive: masque booléen des triangles à écarter}.
    """
    import numpy as np

    prims = list(resource.primitives)
    if not prims:
        return {}
    keys, orient, valid, pid, loc = [], [], [], [], []
    sizes = []
    for pi, prim in enumerate(prims):
        pos = _buf(prim.positions, np.float32).reshape(-1, 3).astype(np.float64)
        idx = _buf(prim.indices, np.uint32).reshape(-1, 3)
        sizes.append(idx.shape[0])
        if idx.shape[0] == 0:
            continue
        h = _vertex_hashes(pos)
        ht = h[idx]
        with np.errstate(over="ignore"):
            keys.append(_mix64(ht[:, 0]) + _mix64(ht[:, 1]) + _mix64(ht[:, 2]))
        asc = (ht[:, 0] < ht[:, 1]).astype(np.int8) + (ht[:, 1] < ht[:, 2]) + (ht[:, 2] < ht[:, 0])
        orient.append(asc == 2)  # sens horaire ou antihoraire, invariant par permutation circulaire
        valid.append((ht[:, 0] != ht[:, 1]) & (ht[:, 1] != ht[:, 2]) & (ht[:, 0] != ht[:, 2]))
        pid.append(np.full(idx.shape[0], pi, dtype=np.int32))
        loc.append(np.arange(idx.shape[0], dtype=np.int64))
    if not keys:
        return {}
    key, orient = np.concatenate(keys), np.concatenate(orient)
    valid, pid, loc = np.concatenate(valid), np.concatenate(pid), np.concatenate(loc)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    brk = np.nonzero(ks[1:] != ks[:-1])[0] + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [ks.size]))
    gsize = ends - starts
    if not (gsize > 1).any():
        return {}

    unnamed_cache = {}

    def unnamed(pi):
        if pi not in unnamed_cache:
            unnamed_cache[pi] = _is_unnamed_material(prims[pi].material_index, gltf_materials, names)
        return unnamed_cache[pi]

    pairs_a, pairs_b = [], []
    # cas courant : un recto et un verso
    g2 = np.nonzero(gsize == 2)[0]
    if g2.size:
        a, b = order[starts[g2]], order[starts[g2] + 1]
        ok = (orient[a] != orient[b]) & valid[a] & valid[b]
        pairs_a.append(a[ok])
        pairs_b.append(b[ok])
    # groupes plus grands : recto et verso appariés un à un
    extra_a, extra_b = [], []
    for g in np.nonzero(gsize > 2)[0].tolist():
        members = order[starts[g]:ends[g]]
        members = members[valid[members]]
        plus = members[orient[members]].tolist()
        minus = members[~orient[members]].tolist()
        used = set()
        for m in minus:
            for pidx in plus:
                if pidx not in used:
                    used.add(pidx)
                    extra_a.append(pidx)
                    extra_b.append(m)
                    break
    if extra_a:
        pairs_a.append(np.asarray(extra_a, dtype=np.int64))
        pairs_b.append(np.asarray(extra_b, dtype=np.int64))
    if not pairs_a:
        return {}
    a, b = np.concatenate(pairs_a), np.concatenate(pairs_b)
    if a.size == 0:
        return {}
    pa_all, pb_all = pid[a], pid[b]
    un = {pi: unnamed(pi) for pi in set(pa_all.tolist()) | set(pb_all.tolist())}
    masks = {}
    for ia, ib, pa, pb in zip(a.tolist(), b.tolist(), pa_all.tolist(), pb_all.tolist()):
        if un[pa] and not un[pb]:
            drop = ia
        elif un[pb] and not un[pa]:
            drop = ib
        elif pa != pb:
            drop = ia if pa > pb else ib
        else:
            drop = max(ia, ib)
        pd = int(pid[drop])
        if pd not in masks:
            masks[pd] = np.zeros(sizes[pd], dtype=bool)
        masks[pd][int(loc[drop])] = True
    return masks


def _is_unnamed_material(index, gltf_materials, names):
    gm = gltf_materials[index] if 0 <= index < len(gltf_materials) else {}
    pbr = gm.get("pbrMetallicRoughness", {})
    if pbr.get("baseColorTexture"):
        return False
    r, g, b, a = pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1.0])
    return (round(r * 255), round(g * 255), round(b * 255), int(round(a * 100))) not in names


def _yup_to_zup(points, uf):
    """(n, 3) en repère glTF Y-up (mètres) -> repère Z-up de Blender, dans l'unité de la scène."""
    import numpy as np

    out = np.empty_like(points, dtype=np.float64)
    out[:, 0] = points[:, 0]
    out[:, 1] = -points[:, 2]
    out[:, 2] = points[:, 1]
    return out * uf


def _build_mesh_data(name, resource, gltf_materials, names, textures, image_cache, mat_cache,
                     drop_backs=True, stats=None, uf=1.0):
    """Maillage Blender (données seules, sans objet) d'une ressource openskp, construit par blocs numpy."""
    import numpy as np

    prims = list(resource.primitives)
    drops = _back_face_drops(resource, gltf_materials, names) if drop_backs else {}
    vchunks, uchunks, tchunks, schunks = [], [], [], []
    slot_of, mesh_mats = {}, []
    base = 0
    for pi, prim in enumerate(prims):
        pos = _buf(prim.positions, np.float32).reshape(-1, 3)
        idx = _buf(prim.indices, np.uint32).reshape(-1, 3).astype(np.int64)
        uv_raw = _buf(prim.uvs, np.float32) if len(prim.uvs) else None
        uv = uv_raw.reshape(-1, 2) if (uv_raw is not None and uv_raw.size == 2 * len(pos)) else None
        keep = np.ones(idx.shape[0], dtype=bool)
        mask = drops.get(pi)
        if mask is not None:
            keep &= ~mask
            if stats is not None:
                stats["back_faces_dropped"] = stats.get("back_faces_dropped", 0) + int(mask.sum())
        if idx.shape[0]:
            # triangles sans surface (points alignés) : la tessellation de grandes faces SketchUp en laisse
            p64 = pos.astype(np.float64)
            d1, d2 = p64[idx[:, 1]] - p64[idx[:, 0]], p64[idx[:, 2]] - p64[idx[:, 0]]
            flat = np.linalg.norm(np.cross(d1, d2), axis=1) <= 1e-5 * np.linalg.norm(d1, axis=1) * np.linalg.norm(d2, axis=1) + 1e-15
            flat &= keep
            if flat.any():
                keep &= ~flat
                if stats is not None:
                    stats["degenerate_dropped"] = stats.get("degenerate_dropped", 0) + int(flat.sum())
        if not keep.all():
            idx = idx[keep]
            if idx.shape[0]:
                used, inverse = np.unique(idx, return_inverse=True)
                pos = pos[used]
                uv = uv[used] if uv is not None else None
                idx = inverse.reshape(-1, 3)
        if idx.shape[0] == 0:
            continue
        if prim.material_index not in slot_of:
            slot_of[prim.material_index] = len(mesh_mats)
            mesh_mats.append(_build_material(prim.material_index, gltf_materials, names, textures, image_cache, mat_cache))
        vchunks.append(pos)
        uchunks.append(uv)
        tchunks.append(idx + base)
        schunks.append(np.full(idx.shape[0], slot_of[prim.material_index], dtype=np.int32))
        base += len(pos)

    mesh = bpy.data.meshes.new(name)
    for m in mesh_mats:
        mesh.materials.append(m)
    if tchunks:
        verts = _yup_to_zup(np.concatenate(vchunks).astype(np.float64), uf).astype(np.float32)
        tris = np.concatenate(tchunks).astype(np.int32)
        slots = np.concatenate(schunks)
        nv, nt = len(verts), len(tris)
        mesh.vertices.add(nv)
        mesh.vertices.foreach_set("co", verts.ravel())
        mesh.loops.add(3 * nt)
        mesh.polygons.add(nt)
        mesh.polygons.foreach_set("loop_start", np.arange(0, 3 * nt, 3, dtype=np.int32))
        mesh.polygons.foreach_set("vertices", tris.ravel())
        if len(mesh_mats) > 1:
            mesh.polygons.foreach_set("material_index", slots)
        if any(u is not None for u in uchunks):
            uv_all = np.concatenate([u if u is not None else np.zeros((len(v), 2), np.float32)
                                     for u, v in zip(uchunks, vchunks)])
            layer = mesh.uv_layers.new(name="UVMap")
            layer.data.foreach_set("uv", uv_all[tris.ravel()].astype(np.float32).ravel())
        mesh.update(calc_edges=True)
    return mesh


def _build_curve_data(name, resource, uf=1.0):
    """Maillage d'arêtes seules (lignes SketchUp) d'une ressource de courbes."""
    import numpy as np

    verts, edges = [], []
    for curve in resource.curves:
        base = len(verts)
        pts = curve.points_m
        verts.extend(pts)
        for i in range(len(pts) - 1):
            edges.append((base + i, base + i + 1))
        if curve.closed and len(pts) > 2:
            edges.append((base + len(pts) - 1, base))
    mesh = bpy.data.meshes.new(name)
    if verts:
        mesh.from_pydata(_yup_to_zup(np.asarray(verts, dtype=np.float64), uf).tolist(), edges, [])
        mesh.update()
    return mesh


def _import_pages(model, root_collection, stats, uf=1.0):
    """Scènes SketchUp -> caméras Blender (œil, cible, haut, champ)."""
    for pg in getattr(model, "pages", []) or []:
        try:
            eye = mathutils.Vector(pg.eye) * (M_PER_INCH * uf)
            target = mathutils.Vector(pg.target) * (M_PER_INCH * uf)
            up = mathutils.Vector(pg.up)
            z = (eye - target).normalized()
            x = up.cross(z)
            if x.length < 1e-9:
                x = mathutils.Vector((1, 0, 0))
            x.normalize()
            y = z.cross(x)
            rot = mathutils.Matrix((x, y, z)).transposed().to_4x4()
            rot.translation = eye
            cam = bpy.data.cameras.new(f"Scene_{pg.name}")
            if getattr(pg, "parallel", False):
                cam.type = "ORTHO"
                cam.ortho_scale = max(0.01, float(pg.ortho_height) * M_PER_INCH * uf)
            else:
                cam.angle = math.radians(float(pg.fov) or 35.0)
            obj = bpy.data.objects.new(f"Scene_{pg.name}", cam)
            obj.matrix_world = rot
            obj["skp_hidden_layers"] = json.dumps(list(getattr(pg, "hidden_layers", []) or []))
            root_collection.objects.link(obj)
            stats["cameras"] += 1
        except Exception as exc:  # une scène illisible ne bloque pas l'import
            print(f"arkedia_skp: scène '{getattr(pg, 'name', '?')}' ignorée ({exc})")


def _available_memory_bytes():
    """Mémoire physique disponible (octets), ou None si le système ne la donne pas."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
            return None
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="ascii", errors="ignore") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_AVPHYS_PAGES"))
    except Exception:
        return None


# Noms uniques et ordre de création. Blender garde chaque liste de données (objets, maillages…) triée par nom
# et place un nouvel élément en remontant depuis la fin : la comparaison se fait octet par octet (UTF-8, valeurs
# non signées), sans tenir compte de la casse des lettres ASCII ; « Obj10 » passe donc avant « Obj2 ».
_MAX_NAME_BYTES = 63


def _clip_name(text, limit=_MAX_NAME_BYTES):
    """Nom limité à `limit` octets UTF-8, sans couper un caractère en deux."""
    raw = str(text).encode("utf-8", "replace")
    if len(raw) <= limit:
        return raw.decode("utf-8", "replace")
    return raw[:limit].decode("utf-8", "ignore")


def _unique_names(bases, limit=_MAX_NAME_BYTES):
    """Noms distincts à la manière de Blender (« Nom », « Nom.001 », « Nom.002 »…), dans l'ordre de `bases`."""
    used, next_n, out = set(), {}, []
    for base in bases:
        base = _clip_name(base or "", limit) or "Sans nom"
        name = base
        if name in used:
            n = next_n.get(base, 1)
            while True:
                suffix = ".%03d" % n
                name = _clip_name(base, limit - len(suffix)) + suffix
                n += 1
                if name not in used:
                    break
            next_n[base] = n
        used.add(name)
        out.append(name)
    return out


def _blender_sort_key(name):
    """Clé de tri qui range les noms comme la liste triée de Blender."""
    return name.encode("utf-8", "replace").lower()


# Mémoire d'import mesurée (pic de mémoire engagée, Blender 5.2 sous Windows) : 41 Mo de fichier donnent 1,4 Go,
# 56 Mo donnent 1,9 Go et 85 Mo donnent 2,9 Go, soit environ 0,26 Go de base plus 27 à 32 fois la taille du
# fichier. On retient 40 fois plus 0,3 Go : une marge d'un quart pour les textures (une image compressée occupe
# bien plus en mémoire décodée) sans refuser à tort, et assez de réserve pour que Blender ne fige pas l'ordinateur.
_IMPORT_BYTES_PER_FILE_BYTE = 40
_IMPORT_BASE_BYTES = int(0.3 * 2 ** 30)


def _check_import_memory(filepath):
    """Refuse, avec un message clair, un import qui épuiserait la mémoire disponible."""
    size = os.path.getsize(filepath)
    need = _IMPORT_BASE_BYTES + _IMPORT_BYTES_PER_FILE_BYTE * size
    avail = _available_memory_bytes()
    if avail is not None and need > 0.85 * avail:
        raise MemoryError(
            f"ce fichier de {size / 2 ** 20:.0f} Mo demanderait environ {need / 2 ** 30:.1f} Go de mémoire à "
            f"l'import pour {avail / 2 ** 30:.1f} Go disponibles : Blender risquerait de figer l'ordinateur. "
            "Fermer d'autres applications, découper le modèle dans SketchUp (un fichier par zone), ou cocher "
            "« Ignorer la vérification de mémoire »"
        )


def _instanced_scene(skp):
    """Scène instanciée bâtie sur la lecture déjà faite par `parse()`.

    `SkpFile.build_instanced_scene()` relit le fichier entier et reconstruit tout depuis zéro : après `parse()`,
    c'est une seconde lecture complète, soit 30 à 40 % du temps d'import et de la mémoire d'un gros modèle.
    On réutilise donc la lecture brute que `parse()` garde ; en cas de souci, retour à la méthode d'origine.
    """
    parsed = getattr(skp, "_parsed", None)
    if parsed is not None:
        try:
            from openskp import instanced_scene

            return instanced_scene.build_instanced_scene(parsed)
        except Exception as exc:
            print(f"arkedia_skp: lecture partagée impossible ({exc}), relecture du fichier")
    return skp.build_instanced_scene()


def import_skp(filepath, context, keep_hierarchy=True, import_scenes=True, store_attributes=True,
               drop_back_faces=True, memory_check=True):
    """Importe un .skp dans la scène courante ; renvoie les statistiques de l'import."""
    wm = context.window_manager
    try:
        wm.progress_begin(0, 1000)
    except Exception:
        pass

    def progress(fraction):
        try:
            wm.progress_update(int(1000 * min(max(fraction, 0.0), 1.0)))
        except Exception:
            pass

    try:
        return _import_skp_impl(filepath, context, keep_hierarchy, import_scenes, store_attributes,
                                drop_back_faces, memory_check, progress)
    finally:
        try:
            wm.progress_end()
        except Exception:
            pass


def _import_skp_impl(filepath, context, keep_hierarchy, import_scenes, store_attributes,
                     drop_back_faces, memory_check, progress):
    import openskp

    t0 = time.time()
    if memory_check:
        _check_import_memory(filepath)
    uf = _unit_factor(context)
    skp = openskp.SkpFile.open(filepath)
    model = skp.parse()
    scene = _instanced_scene(skp)
    skp._parsed = None  # la lecture brute n'est plus utile : c'est la plus grosse part de la mémoire
    progress(0.1)  # la lecture du fichier (la moitié du temps pour un gros modèle) ne donne pas de détail

    names = _material_name_lookup(model)
    gltf_materials = getattr(scene, "gltf_materials", None) or []
    textures = getattr(scene, "textures", None) or []
    resources = {r.id: r for r in scene.mesh_resources}
    curve_resources = {r.id: r for r in getattr(scene, "curve_resources", None) or []}
    layer_hidden = getattr(scene, "layer_hidden", None) or {}

    # L'API "instanced scene" aplatit les groupes et perd leur calque / attributs :
    # on les relit dans le modèle brut (racine + définitions), file par nom.
    raw_info = {}

    def _collect_raw(insts):
        for inst in insts or []:
            nm = getattr(inst, "name", None)
            if nm:
                raw_info.setdefault(nm, collections.deque()).append(inst)

    try:
        _collect_raw(model.root.instances)
    except Exception:
        pass

    mat_cache, image_cache = {}, {}
    layer_colls = {}
    stats = {
        "unique_meshes": 0, "placements": 0, "triangles": 0, "back_faces_dropped": 0, "curve_groups": 0,
        "materials": 0, "textures": 0, "layers": 0, "cameras": 0, "objects": 0,
    }

    stem = os.path.splitext(os.path.basename(filepath))[0]
    root = bpy.data.collections.new(stem)
    context.scene.collection.children.link(root)

    def layer_collection(name):
        name = name or "Layer0"
        if name not in layer_colls:
            coll = bpy.data.collections.new(name)
            root.children.link(coll)
            layer_colls[name] = coll
        return layer_colls[name]

    def _raw_for(node):
        lst = raw_info.get(node.name or "")
        return lst.popleft() if lst else None

    def _layer_of(node, raw):
        if raw is not None and getattr(raw, "layer", None) and (not node.layer or node.layer == "Layer0"):
            return raw.layer
        return node.layer

    # Passe 1 : le modèle mis à plat dans l'ordre de parcours (un parent précède toujours ses enfants), avec la
    # matrice de placement, le calque et les ressources de maillage de chaque nœud.
    root_node = scene.scene_hierarchy
    root_world = _gltf_matrix_to_blender(root_node.matrix)
    recs = []
    seen_mesh, seen_curve, mesh_ids, curve_ids = set(), set(), [], []
    stack = [(child, -1, root_world) for child in reversed(root_node.children)]
    while stack:
        node, parent_index, parent_world = stack.pop()
        world_y = parent_world @ _gltf_matrix_to_blender(node.matrix)
        # Les maillages sont stockés en Z-up (repère natif de SketchUp) : la matrice de placement est
        # donc conjuguée par le changement d'axes, et sa translation passée dans l'unité de la scène.
        world_b = _YUP_TO_ZUP @ world_y @ _ZUP_TO_YUP
        world_b.translation = world_b.translation * uf
        raw = _raw_for(node)
        index = len(recs)
        recs.append((node, parent_index, world_b, raw, _layer_of(node, raw)))
        if node.mesh_resource_id is not None and node.mesh_resource_id not in seen_mesh:
            seen_mesh.add(node.mesh_resource_id)
            mesh_ids.append(node.mesh_resource_id)
        if node.curve_resource_id is not None and node.curve_resource_id not in seen_curve:
            seen_curve.add(node.curve_resource_id)
            curve_ids.append(node.curve_resource_id)
        for child in reversed(node.children):
            stack.append((child, index, world_y))
    progress(0.12)

    # Blender garde chaque liste de données triée par nom (octet par octet, casse ASCII ignorée) et place un
    # nouvel élément en remontant depuis la fin de la liste : un nom plus petit que le dernier oblige à
    # parcourir tout ce qui est plus grand. Créer 100 000 objets dans le désordre revient à 100 000 parcours
    # de liste (90 s mesurées pour 100 000 copies d'un composant, 4 s dans l'ordre alphabétique). Les noms sont
    # donc rendus uniques ici, une fois pour toutes, puis maillages et objets créés dans l'ordre alphabétique.
    #
    # Tous les maillages sont construits avant le premier objet : `Mesh.materials.append` parcourt les objets
    # du fichier à chaque appel, donc un maillage créé après 20 000 objets coûte 20 000 fois plus qu'au début
    # (temps quadratique : 100 s pour 20 000 groupes uniques, moins de 10 s dans cet ordre). Les composants
    # répétés deviennent des objets réels qui partagent le même maillage, pas des collections instanciées :
    # on peut les convertir en IFC, les exporter ou les éditer sans « rendre les instances réelles ».
    bases = [resources[rid].definition_name or rid for rid in mesh_ids]
    bases += [(curve_resources[rid].definition_name or rid) + " (lignes)" for rid in curve_ids]
    mesh_names = _unique_names(bases)
    mesh_data, curve_data = {}, {}
    build_order = sorted(range(len(bases)), key=lambda j: _blender_sort_key(mesh_names[j]))
    for n, j in enumerate(build_order):
        if j < len(mesh_ids):
            rid = mesh_ids[j]
            mesh_data[rid] = _build_mesh_data(mesh_names[j], resources[rid], gltf_materials, names, textures,
                                              image_cache, mat_cache, drop_back_faces, stats, uf)
            stats["unique_meshes"] += 1
            stats["triangles"] += len(mesh_data[rid].polygons)
        else:
            rid = curve_ids[j - len(mesh_ids)]
            curve_data[rid] = _build_curve_data(mesh_names[j], curve_resources[rid], uf)
            stats["curve_groups"] += 1
        if n % 50 == 0:
            progress(0.12 + 0.43 * n / max(1, len(build_order)))

    # Passe 2 : les objets, un par nœud (plus un objet d'arêtes pour les lignes seules), créés dans l'ordre
    # alphabétique de leurs noms puis rangés dans la collection de leur calque.
    tasks = []
    for i, (node, _, _, _, _) in enumerate(recs):
        label = node.name or node.definition_name or "Groupe"
        tasks.append((label, i, False))
        if node.curve_resource_id is not None:
            tasks.append((label + " (lignes)", i, True))
    obj_names = _unique_names([t[0] for t in tasks])
    for rec in recs:
        layer_collection(rec[4])  # collections de calques créées dans l'ordre du modèle
    objs, line_objs = [None] * len(recs), {}
    for n, k in enumerate(sorted(range(len(tasks)), key=lambda k: _blender_sort_key(obj_names[k]))):
        _, i, is_lines = tasks[k]
        node = recs[i][0]
        if is_lines:
            ob = bpy.data.objects.new(obj_names[k], curve_data[node.curve_resource_id])
            line_objs[i] = ob
        else:
            if node.mesh_resource_id is not None:
                ob = bpy.data.objects.new(obj_names[k], mesh_data[node.mesh_resource_id])
                stats["placements"] += 1
            else:
                ob = bpy.data.objects.new(obj_names[k], None)
                ob.empty_display_type = "PLAIN_AXES"
                ob.empty_display_size = 0.05
            objs[i] = ob
        layer_collection(recs[i][4]).objects.link(ob)
        stats["objects"] += 1
        if n % 100 == 0:
            progress(0.55 + 0.35 * n / max(1, len(tasks)))

    def tag(obj, node, raw=None, layer=None):
        if not store_attributes:
            return
        guid = node.guid or (getattr(raw, "guid", "") if raw is not None else "")
        if guid:
            obj["skp_guid"] = guid
        if node.definition_name:
            obj["skp_definition"] = node.definition_name
        lay = layer or node.layer
        if lay:
            obj["skp_layer"] = lay
        attrs = node.attribute_dictionaries or (getattr(raw, "attribute_dictionaries", None) if raw is not None else None)
        if attrs:
            obj["skp_attributes"] = json.dumps(attrs, ensure_ascii=False, default=str)
        props = node.properties or (getattr(raw, "properties", None) if raw is not None else None)
        if props:
            obj["skp_properties"] = json.dumps(props, ensure_ascii=False, default=str)

    def place(obj, world_blender, parent):
        if keep_hierarchy and parent is not None:
            obj.parent = parent
            obj.matrix_parent_inverse = parent.matrix_world.inverted()
        obj.matrix_world = world_blender

    # Passe 3 : parentés, matrices et attributs, dans l'ordre du modèle (le parent est placé avant ses enfants).
    for i, (node, parent_index, world_b, raw, lay_name) in enumerate(recs):
        ob = objs[i]
        place(ob, world_b, objs[parent_index] if parent_index >= 0 else None)
        tag(ob, node, raw, lay_name)
        if i in line_objs:
            place(line_objs[i], world_b, ob)
        if i % 200 == 0:
            progress(0.9 + 0.1 * i / max(1, len(recs)))

    if import_scenes:
        _import_pages(model, root, stats, uf)

    stats["layers"] = len(layer_colls)
    stats["materials"] = len(mat_cache)
    stats["textures"] = len(image_cache)
    for name, coll in layer_colls.items():
        if layer_hidden.get(name, False):
            coll.hide_viewport = True
            coll.hide_render = True
    stats["seconds"] = round(time.time() - t0, 3)
    return stats


# --------------------------------------------------------------------------
# EXPORT
# --------------------------------------------------------------------------

_FORBIDDEN_LAYER_CHARS = '<>[]{}|;,?`~="'
_MESHLIKE = {"MESH", "CURVE", "SURFACE", "FONT", "META"}


def _clean_layer_name(name: str) -> str:
    name = str(name).replace("/", " - ")
    for ch in _FORBIDDEN_LAYER_CHARS:
        name = name.replace(ch, "_")
    return _su(name.strip(), 120) or "Calque"


def _clean_material_name(name: str) -> str:
    return (_su(str(name), 200).replace("[", "(").replace("]", ")")).strip() or "Matériau"


def _attr_value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v if abs(v) < 2 ** 31 else float(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return _su(v, 240)
    return None


def _clean_attrs(d):
    out = {}
    for k, v in d.items():
        v = _attr_value(v)
        if v is not None:
            out[_su(str(k), 120)] = v
    return out


def _bonsai_tool():
    for modname in ("bonsai.tool", "bl_ext.blender_org.bonsai.tool", "blenderbim.tool"):
        try:
            import importlib

            return importlib.import_module(modname)
        except Exception:
            continue
    return None


def _ifc_info(obj, tool, with_psets):
    """Infos IFC de l'objet (Bonsai) : classe, GlobalId, nom, jeux de propriétés."""
    info, dicts = {}, []
    if tool is None:
        return info, dicts
    try:
        ent = tool.Ifc.get_entity(obj)
    except Exception:
        ent = None
    if ent is None:
        return info, dicts
    try:
        info["ifc_class"] = ent.is_a()
        info["ifc_guid"] = getattr(ent, "GlobalId", "") or ""
        info["ifc_name"] = getattr(ent, "Name", "") or ""
        if getattr(ent, "PredefinedType", None):
            info["ifc_predefined_type"] = str(ent.PredefinedType)
        long_name = getattr(ent, "LongName", None)
        if long_name:
            info["ifc_long_name"] = str(long_name)
    except Exception:
        pass
    storey = _ifc_storey_name(ent)
    if storey:
        info["ifc_storey"] = storey
    if with_psets:
        try:
            import ifcopenshell.util.element as ue

            for pset, props in (ue.get_psets(ent) or {}).items():
                entries = _clean_attrs({k: v for k, v in props.items() if k != "id"})
                if entries:
                    dicts.append((_clean_layer_name(f"IFC_{pset}"), entries))
        except Exception:
            pass
    return info, dicts


def _ifc_storey_name(ent):
    """Nom du niveau (IfcBuildingStorey) qui contient ou agrège l'entité, en remontant conteneurs et agrégats.

    Une volée d'escalier est agrégée à son escalier, lui-même contenu dans le niveau ; une pièce (IfcSpace) est
    agrégée au niveau. None si l'entité n'est rattachée à aucun niveau ou si IfcOpenShell est absent.
    """
    try:
        import ifcopenshell.util.element as ue
    except Exception:
        return None
    for _ in range(20):
        if ent is None:
            return None
        try:
            if ent.is_a("IfcBuildingStorey"):
                return str(ent.Name or getattr(ent, "LongName", None) or "Niveau")
            nxt = ue.get_container(ent)
            if nxt is None:
                nxt = ue.get_aggregate(ent)
        except Exception:
            return None
        ent = nxt
    return None


def _ifc_entity(tool, obj):
    if tool is None:
        return None
    try:
        return tool.Ifc.get_entity(obj)
    except Exception:
        return None


def _is_ifc_space(obj, ent):
    """Volume de pièce d'un projet Bonsai : classe IfcSpace, ou nom « IfcSpace/... » si l'IFC n'est pas chargé."""
    if ent is not None:
        try:
            return bool(ent.is_a("IfcSpace"))
        except Exception:
            return False
    return obj.name.startswith("IfcSpace/")


_SPACE_OPACITY = 0.2
_SPACE_TAG_RGB = (0, 196, 204)
_SPACE_DEFAULT_RGB = (140, 205, 235)
# Retrait des faces des pièces : leurs faces tombent sur celles des sols, plafonds et murs, et SketchUp ne sait pas
# laquelle dessiner devant (moirage). Dans SketchUp 2027, le moirage disparaît dès 1 mm sur la vue d'ensemble d'une
# villa de 20 m ; 5 mm gardent de la marge pour un bâtiment plus grand ou une vue plus lointaine, très en deçà des
# 2 cm du relevé.
_SPACE_INSET_MM = 5.0


def _fr_area(area_m2):
    """« 5,69 m² » : deux décimales, virgule, espace insécable avant l'unité."""
    return f"{area_m2:.2f}".replace(".", ",") + " m²"


def _space_label(obj, info, area_m2=None):
    """Nom SketchUp d'une pièce : « Pièce 01 Chambre » (numéro et nom long IFC), sinon le nom de l'objet.

    Avec une surface : « Pièce 01 Chambre, 5,69 m² ».
    """
    parts = [str(x) for x in (info.get("ifc_name"), info.get("ifc_long_name")) if x]
    if parts:
        label = "Pièce " + " ".join(parts)
    else:
        name = obj.name.split("/", 1)[1] if obj.name.startswith("IfcSpace/") else obj.name
        label = "Pièce " + name
    if area_m2 is not None and area_m2 > 0:
        label += ", " + _fr_area(area_m2)
    return label


def _ifc_space_area_m2(ent, tool):
    """Surface de la pièce dans l'IFC (Qto_SpaceBaseQuantities : NetFloorArea, sinon GrossFloorArea), en m²."""
    if ent is None or tool is None:
        return None
    try:
        import ifcopenshell.util.element as ue

        qto = (ue.get_psets(ent, qtos_only=True) or {}).get("Qto_SpaceBaseQuantities") or {}
        value = qto.get("NetFloorArea") or qto.get("GrossFloorArea")
        if not value:
            return None
        scale = 1.0
        try:
            import ifcopenshell.util.unit as uu

            scale = float(uu.calculate_unit_scale(tool.Ifc.get(), "AREAUNIT"))
        except Exception:
            pass
        area = float(value) * scale
        return area if area > 0 else None
    except Exception:
        return None


def _mesh_floor_area_m2(mesh, matrix_world, unit_factor):
    """Surface au sol d'un volume : projection horizontale des faces tournées vers le bas, en m²."""
    import numpy as np

    A = _mesh_arrays(mesh)
    if not A["n_poly"]:
        return None
    M = np.array(matrix_world, dtype=np.float64)
    co = A["co"] @ M[:3, :3].T + M[:3, 3]
    lv, ls, lt = A["lv"], A["lstart"], A["ltotal"]
    poly_of_loop = np.repeat(np.arange(A["n_poly"]), lt)
    idx = np.arange(len(lv))
    last = (ls + lt - 1)[poly_of_loop]
    nxt = np.where(idx == last, ls[poly_of_loop], idx + 1)
    N = np.zeros((A["n_poly"], 3))
    np.add.at(N, poly_of_loop, np.cross(co[lv], co[lv[nxt]]))
    lens = np.linalg.norm(N, axis=1)
    down = (N[:, 2] < 0) & (np.abs(N[:, 2]) > 0.94 * np.maximum(lens, 1e-30))
    area_bu = 0.5 * float(np.abs(N[down, 2]).sum())
    return area_bu / (unit_factor * unit_factor) if area_bu > 0 else None


def _inset_offsets(co, lv, lstart, ltotal, d, weld=1e-6):
    """Déplacements qui rentrent chaque face d'un volume fermé de `d` le long de sa normale.

    `co` : sommets (n, 3) ; `lv`, `lstart`, `ltotal` : boucles des polygones, comme dans Blender. Les sommets
    confondus à `weld` près sont traités ensemble. Chaque sommet recule pour que tous les plans qui le touchent
    reculent de `d` (moindres carrés, solution de norme minimale) : sur un prisme, même à murs obliques ou à angle
    rentrant, les faces restent planes et gardent leurs angles. Renvoie None si le volume n'est pas fermé et
    orienté de façon cohérente, si un sommet devait bouger de plus de 4 `d` (pointe aiguë) ou si une face se
    retournerait (pièce plus mince que 2 `d`).
    """
    import numpy as np

    co = np.asarray(co, dtype=np.float64)
    lv = np.asarray(lv, dtype=np.int64)
    lstart = np.asarray(lstart, dtype=np.int64)
    ltotal = np.asarray(ltotal, dtype=np.int64)
    n_poly = len(lstart)
    if d <= 0 or n_poly < 4 or len(co) < 4:
        return None
    # sommets soudés par position
    q = np.round(co / weld).astype(np.int64)
    _u, wid = np.unique(q, axis=0, return_inverse=True)
    wid = wid.reshape(-1)
    nw = int(wid.max()) + 1
    lw = wid[lv]
    poly_of_loop = np.repeat(np.arange(n_poly), ltotal)
    idx = np.arange(len(lv))
    last = (lstart + ltotal - 1)[poly_of_loop]
    nxt = np.where(idx == last, lstart[poly_of_loop], idx + 1)
    a, b = lw, lw[nxt]
    if (a == b).any():
        return None
    # volume fermé et orienté : chaque arête parcourue une fois dans chaque sens
    fwd = a * nw + b
    rev = b * nw + a
    uniq, cnt = np.unique(fwd, return_counts=True)
    if (cnt != 1).any() or not np.isin(rev, uniq).all():
        return None
    # normales de Newell (polygones quelconques), sens donné par le signe du volume
    N = np.zeros((n_poly, 3))
    np.add.at(N, poly_of_loop, np.cross(co[lv], co[lv[nxt]]))
    vol = float(np.einsum("ij,ij->i", N, co[lv[lstart]]).sum()) / 6.0
    if abs(vol) < 1e-15:
        return None
    lens = np.linalg.norm(N, axis=1)
    ok = lens > 1e-18
    nrm = np.zeros_like(N)
    nrm[ok] = N[ok] / lens[ok, None]
    if vol < 0:
        nrm = -nrm
    # plans distincts autour de chaque sommet soudé
    order = np.argsort(lw, kind="stable")
    polys_sorted = poly_of_loop[order]
    bounds = np.searchsorted(lw[order], np.arange(nw + 1))
    disp_w = np.zeros((nw, 3))
    lim = 4.0 * d
    for w in range(nw):
        cand = nrm[np.unique(polys_sorted[bounds[w]:bounds[w + 1]])]
        planes = []
        for n in cand:
            if float(n @ n) > 0.25 and all(abs(float(n @ m)) < 1.0 - 1e-9 for m in planes):
                planes.append(n)
        if not planes:
            continue
        P = np.array(planes)
        v = np.linalg.lstsq(P, np.full(len(P), -d), rcond=None)[0]
        if not np.isfinite(v).all() or float(np.linalg.norm(v)) > lim:
            return None
        disp_w[w] = v
    disp = disp_w[wid]
    # contrôle : volume réduit, aucune face retournée
    co2 = co + disp
    N2 = np.zeros((n_poly, 3))
    np.add.at(N2, poly_of_loop, np.cross(co2[lv], co2[lv[nxt]]))
    vol2 = float(np.einsum("ij,ij->i", N2, co2[lv[lstart]]).sum()) / 6.0
    if vol2 * vol <= 0 or abs(vol2) >= abs(vol):
        return None
    if (np.einsum("ij,ij->i", N2[ok], N[ok]) <= 0).any():
        return None
    return disp


def _inset_prism(co, lv, lstart, ltotal, d, slope_cos=0.94, vert_tol=0.02):
    """Pièce « 2,5D » (murs verticaux, sol et plafond plans ou en pente douce) rentrée de `d`, en coordonnées
    monde : l'emprise est décalée par shapely, ce qui supprime aussi un étranglement plus mince que 2 `d` (pièce
    qui contourne une trémie collée à un mur), puis le volume est reconstruit entre le sol et le plafond, chacun
    remonté ou abaissé de `d`. Renvoie (sommets (n, 3), faces) ou None si la pièce n'a pas cette forme.
    """
    import numpy as np

    try:
        import shapely
        from shapely.geometry import Polygon
        from shapely.geometry.polygon import orient
    except Exception:
        return None
    co = np.asarray(co, dtype=np.float64)
    lv = np.asarray(lv, dtype=np.int64)
    lstart = np.asarray(lstart, dtype=np.int64)
    ltotal = np.asarray(ltotal, dtype=np.int64)
    n_poly = len(lstart)
    if d <= 0 or n_poly < 4:
        return None
    poly_of_loop = np.repeat(np.arange(n_poly), ltotal)
    idx = np.arange(len(lv))
    last = (lstart + ltotal - 1)[poly_of_loop]
    nxt = np.where(idx == last, lstart[poly_of_loop], idx + 1)
    N = np.zeros((n_poly, 3))
    np.add.at(N, poly_of_loop, np.cross(co[lv], co[lv[nxt]]))
    vol = float(np.einsum("ij,ij->i", N, co[lv[lstart]]).sum()) / 6.0
    if abs(vol) < 1e-12:
        return None
    if vol < 0:
        N = -N
    lens = np.linalg.norm(N, axis=1)
    live = lens > 1e-14
    nz = np.zeros(n_poly)
    nz[live] = N[live, 2] / lens[live]
    floor = live & (nz < -slope_cos)
    ceil = live & (nz > slope_cos)
    wall = live & (np.abs(nz) < vert_tol)
    if not floor.any() or not ceil.any() or (live & ~(floor | ceil | wall)).any():
        return None
    union_all = getattr(shapely, "union_all", None)
    if union_all is None:
        from shapely.ops import unary_union as union_all

    def footprint(mask):
        polys = []
        for p in np.nonzero(mask)[0].tolist():
            ring = co[lv[lstart[p]:lstart[p] + ltotal[p]], :2]
            g = Polygon(ring)
            if not g.is_valid:
                g = g.buffer(0)
            if g.area > 0:
                polys.append(g)
        return union_all(polys) if polys else None

    fl, ce = footprint(floor), footprint(ceil)
    if fl is None or ce is None or fl.area <= 0:
        return None
    if fl.symmetric_difference(ce).area > 1e-6 * max(fl.area, 1.0) + 1e-8:
        return None  # plafond et sol d'emprises différentes : pas un prisme
    inset = fl.buffer(-d, join_style=2, mitre_limit=5.0)
    if inset.is_empty:
        return None
    parts = [inset] if inset.geom_type == "Polygon" else [g for g in getattr(inset, "geoms", []) if g.geom_type == "Polygon"]
    parts = [orient(g, 1.0) for g in parts if g.area > (2 * d) ** 2]
    if not parts:
        return None

    # plans du sol et du plafond : (normale unitaire, point) par polygone
    def planes(mask):
        out = []
        for p in np.nonzero(mask)[0].tolist():
            ring = co[lv[lstart[p]:lstart[p] + ltotal[p]]]
            out.append((N[p] / lens[p], ring[0], Polygon(ring[:, :2])))
        return out

    fl_planes, ce_planes = planes(floor), planes(ceil)

    def z_on(planes_, x, y, shift):
        from shapely.geometry import Point
        pt = Point(x, y)
        best = min(planes_, key=lambda t: t[2].distance(pt))
        n, p0, _g = best
        z = p0[2] - (n[0] * (x - p0[0]) + n[1] * (y - p0[1])) / n[2]
        return z + shift / abs(n[2])

    verts, faces = [], []
    for part in parts:
        rings = [list(part.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in part.interiors]
        index = {}
        ring_ids = []
        for ring in rings:
            ids = []
            for x, y in ring:
                key = (round(x, 9), round(y, 9))
                if key in index:
                    ids.append(index[key])
                    continue
                zb = z_on(fl_planes, x, y, +d)
                zt = z_on(ce_planes, x, y, -d)
                if zt - zb <= 0:
                    return None
                index[key] = len(verts)
                verts.append((x, y, zb))
                verts.append((x, y, zt))
                ids.append(index[key])
            ring_ids.append(ids)
        tris = shapely.constrained_delaunay_triangles(part)
        for t in getattr(tris, "geoms", []):
            c = list(t.exterior.coords)[:-1]
            if len(c) != 3:
                continue
            try:
                ids = [index[(round(x, 9), round(y, 9))] for x, y in c]
            except KeyError:
                return None  # point ajouté par la triangulation : on renonce
            (x0, y0), (x1, y1), (x2, y2) = c
            ccw = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0) > 0
            if not ccw:
                ids = ids[::-1]
            faces.append([ids[2], ids[1], ids[0]])          # sol, normale vers le bas
            faces.append([ids[0] + 1, ids[1] + 1, ids[2] + 1])  # plafond, normale vers le haut
        for ids in ring_ids:
            m = len(ids)
            for i in range(m):
                a, b = ids[i], ids[(i + 1) % m]
                faces.append([a, b, b + 1, a + 1])
    return np.array(verts), faces


def _inset_space(mesh, matrix_world, d):
    """Rentre une pièce de `d` unités Blender, mesurées dans le repère du monde.

    D'abord sommet par sommet, ce qui garde le maillage d'origine ; sinon, pour une pièce à murs verticaux, par
    reconstruction depuis son emprise décalée. Renvoie (méthode, maillage) : (« sommets », le maillage temporaire
    modifié sur place), (« emprise », un nouveau maillage à supprimer après usage) ou (None, None).
    """
    import numpy as np

    A = _mesh_arrays(mesh)
    if not A["n_poly"]:
        return None, None
    M = np.array(matrix_world, dtype=np.float64)
    try:
        Minv = np.linalg.inv(M)
    except Exception:
        return None, None
    co_w = A["co"] @ M[:3, :3].T + M[:3, 3]
    disp = _inset_offsets(co_w, A["lv"], A["lstart"], A["ltotal"], d)
    if disp is not None:
        loc = (co_w + disp) @ Minv[:3, :3].T + Minv[:3, 3]
        mesh.vertices.foreach_set("co", loc.astype(np.float32).ravel())
        mesh.update()
        return "sommets", mesh
    rebuilt = _inset_prism(co_w, A["lv"], A["lstart"], A["ltotal"], d)
    if rebuilt is None:
        return None, None
    verts, faces = rebuilt
    loc = verts @ Minv[:3, :3].T + Minv[:3, 3]
    tmp = bpy.data.meshes.new("_arkedia_piece_rentree")
    tmp.from_pydata([tuple(float(c) for c in p) for p in loc], [], faces)
    tmp.update()
    return "emprise", tmp


def _space_layer(mode, info):
    if mode == "NONE":
        return None
    if mode == "IFC_CLASS":
        return info.get("ifc_class") or "IfcSpace"
    storey = info.get("ifc_storey")
    return f"Pièces - {storey}" if storey else "Pièces"


def _collection_index():
    """{nom complet de l'objet: [collections qui le contiennent]}, calculé en un seul passage.

    `Object.users_collection` recopie la liste d'objets de chaque collection à chaque appel : avec
    30 000 objets répartis en 5 collections, 131 s d'un export de 140 s passaient là (temps quadratique,
    plus d'une demi-heure pour 100 000 objets). L'ordre des collections est celui de `users_collection`.
    """
    index = {}
    for coll in bpy.data.collections:
        for ob in coll.objects:
            index.setdefault(ob.name_full, []).append(coll)
    return index


def _object_layer(obj, mode, info, index):
    if mode == "NONE":
        return None
    if mode == "IFC_CLASS":
        cls = info.get("ifc_class")
        if not cls:
            head = obj.name.split("/", 1)[0]
            cls = head if head.startswith("Ifc") else None
        return cls
    if mode == "IFC_STOREY" and info.get("ifc_storey"):
        # niveau lu dans l'IFC (conteneur, puis agrégat) : rattache aussi les éléments d'un agrégat (volées d'escalier)
        return info["ifc_storey"]
    for coll in index.get(obj.name_full, ()):
        nm = coll.name
        if nm in ("Collection", "Scene Collection") or nm.endswith("(source geometry)"):
            continue
        if mode == "IFC_STOREY":
            if not nm.startswith("IfcBuildingStorey"):
                continue
            # étiquette au nom du niveau, sans le préfixe de la collection Bonsai (« IfcBuildingStorey/RDC » -> « RDC »)
            return nm.split("/", 1)[1] if "/" in nm and nm.split("/", 1)[1].strip() else nm
        return nm
    return None


_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_MAX_TEXTURE_PIXELS = 16384 * 16384


def _is_png_or_jpeg(head):
    return head[:8] == _PNG_SIG or head[:3] == b"\xff\xd8\xff"


def _texture_stem(name):
    s = "".join("_" if (ch in '\\/:*?"<>|' or ch < " ") else ch for ch in str(name)).strip(" .")
    return (s or "texture")[:80]


def _png_from_pixels(img, path):
    """Dernier recours : PNG 8 bits écrit à la main depuis les pixels de l'image (aucun état Blender modifié)."""
    import struct
    import zlib

    import numpy as np

    w, h = int(img.size[0]), int(img.size[1])
    if w * h == 0 or w * h > _MAX_TEXTURE_PIXELS // 4:
        raise ValueError("image vide ou trop grande pour un encodage direct")
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    px = np.clip(buf.reshape(h, w, 4), 0.0, 1.0)
    if img.is_float and img.colorspace_settings.name != "sRGB" and img.colorspace_settings.name != "Non-Color":
        lin = px[..., :3]
        px[..., :3] = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 1e-12), 1.0 / 2.4) - 0.055)
    rows = (px[::-1] * 255.0 + 0.5).astype(np.uint8).reshape(h, w * 4)  # Blender stocke les lignes de bas en haut
    raw = np.concatenate((np.zeros((h, 1), dtype=np.uint8), rows), axis=1).tobytes()

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(_PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _texture_file(img, tmpdir, name):
    """(chemin PNG/JPEG à embarquer | None, remarque | None) pour une image Blender.

    Ordre : fichier d'origine tel quel (aucune perte, aucun réencodage) ; octets empaquetés ; rendu PNG
    sRGB 8 bits par une scène temporaire (images générées, modifiées, flottantes ou d'un autre format) ;
    encodage direct des pixels. L'image et les scènes de l'utilisateur ne sont jamais modifiées.

    L'ancienne méthode (img.copy() puis save) écrivait une image NOIRE pour une image générée ou modifiée
    et échouait en silence pour un fichier non chargé : la texture disparaissait de l'export.
    """
    stem = _texture_stem(name)
    eight_bit = (not img.is_float) and img.depth in (24, 32)
    try:
        if img.source == "FILE" and eight_bit and not img.is_dirty and not img.packed_file:
            src = bpy.path.abspath(img.filepath, library=img.library)
            if os.path.splitext(src)[1].lower() in (".png", ".jpg", ".jpeg") and os.path.isfile(src):
                with open(src, "rb") as f:
                    if _is_png_or_jpeg(f.read(8)):
                        return src, None
    except Exception:
        pass
    try:
        pf = img.packed_file
        if pf is not None and eight_bit and not img.is_dirty and img.file_format in ("PNG", "JPEG"):
            data = bytes(pf.data)
            if _is_png_or_jpeg(data[:8]):
                out = os.path.join(tmpdir, stem + (".png" if data[:8] == _PNG_SIG else ".jpg"))
                with open(out, "wb") as f:
                    f.write(data)
                return out, None
    except Exception:
        pass
    out = os.path.join(tmpdir, stem + ".png")
    err = None
    sc = None
    try:
        sc = bpy.data.scenes.new("arkedia_skp_tmp")
        sc.view_settings.view_transform = "Standard"
        sc.view_settings.look = "None"
        sc.view_settings.exposure = 0.0
        sc.view_settings.gamma = 1.0
        sc.display_settings.display_device = "sRGB"
        fmt = sc.render.image_settings
        fmt.file_format = "PNG"
        fmt.color_mode = "RGBA"
        fmt.color_depth = "8"
        img.save_render(out, scene=sc)
        with open(out, "rb") as f:
            if f.read(8) == _PNG_SIG:
                return out, None
        err = "fichier PNG illisible"
    except Exception as exc:
        err = str(exc).strip().splitlines()[0][:120] if str(exc).strip() else type(exc).__name__
    finally:
        if sc is not None:
            try:
                bpy.data.scenes.remove(sc)
            except Exception:
                pass
    try:
        _png_from_pixels(img, out)
        return out, None
    except Exception as exc:
        return None, "%s ; encodage direct impossible (%s)" % (err, str(exc)[:80])


def _material_info(mat, tmpdir, notes=None):
    """(nom, rgb 0-255, opacité|None, chemin_texture|None) d'un matériau Blender."""
    r, g, b, a = mat.diffuse_color
    image_path = None
    bsdf = _principled(mat, create=False) if mat.node_tree else None
    if bsdf is not None:
        col = bsdf.inputs["Base Color"].default_value
        r, g, b = col[0], col[1], col[2]
        a = bsdf.inputs["Alpha"].default_value
        link = bsdf.inputs["Base Color"].links[0] if bsdf.inputs["Base Color"].is_linked else None
        if link is not None and link.from_node.type == "TEX_IMAGE" and link.from_node.image is not None:
            img = link.from_node.image
            image_path, why = _texture_file(img, tmpdir, mat.name)
            if image_path is None and notes is not None:
                notes.append("texture de « %s » non exportée (%s) : couleur unie à la place" % (mat.name, why))
            elif image_path is not None and notes is not None and max(img.size) > 8192:
                notes.append("texture de « %s » très grande (%d × %d) : SketchUp web risque de la refuser ou de ralentir"
                             % (mat.name, img.size[0], img.size[1]))
    rgb = tuple(int(round(_linear_to_srgb(c) * 255)) for c in (r, g, b))
    opacity = None if a >= 0.999 else float(a)
    return _clean_material_name(mat.name), rgb, opacity, image_path


def _add_texture(builder, name, image_path, opacity):
    """add_texture_material sans inscrire le chemin local de l'image (session Windows, dossier temporaire) dans le .skp."""
    writer = getattr(builder, "_material_writer", None)
    orig = getattr(writer, "write_textured_material", None)
    if orig is None:
        return builder.add_texture_material(name, image_path, opacity=opacity)

    def neutral(n, image_bytes, texture_path, **kw):
        return orig(n, image_bytes, os.path.basename(texture_path), **kw)

    writer.write_textured_material = neutral
    try:
        return builder.add_texture_material(name, image_path, opacity=opacity)
    finally:
        try:
            del writer.write_textured_material
        except AttributeError:
            pass


def _matrix3_row_major(m3):
    return tuple(m3[i][j] for i in range(3) for j in range(3))


def _skip_face(stats, exc, count=1):
    """Comptabilise une face non écrite : sans surface (aire nulle, invisible) ou refusée (à signaler)."""
    text = str(exc)
    if "collinear or degenerate" in text:
        stats["faces_degenerate"] = stats.get("faces_degenerate", 0) + count
        return
    stats["faces_skipped"] += count
    key = (type(exc).__name__ + " : " + text)[:110]
    reasons = stats.setdefault("skip_reasons", {})
    reasons[key] = reasons.get(key, 0) + count


# --- lecture vectorisée d'un maillage Blender ------------------------------------------------


def _mesh_arrays(mesh):
    """Tableaux numpy du maillage (une lecture foreach_get par attribut, aucune boucle RNA)."""
    import numpy as np

    n_vert, n_poly, n_loop = len(mesh.vertices), len(mesh.polygons), len(mesh.loops)

    def fetch(coll, attr, dtype, width=1, count=None):
        n = len(coll) if count is None else count
        arr = np.empty(n * width, dtype=dtype)
        if n:
            coll.foreach_get(attr, arr)
        return arr.reshape(-1, width) if width > 1 else arr

    return {
        "n_vert": n_vert, "n_poly": n_poly, "n_loop": n_loop,
        "co": fetch(mesh.vertices, "co", np.float64, 3),
        "nrm": fetch(mesh.polygons, "normal", np.float64, 3),
        "cen": fetch(mesh.polygons, "center", np.float64, 3),
        "mat": fetch(mesh.polygons, "material_index", np.int32),
        "smooth": fetch(mesh.polygons, "use_smooth", np.bool_),
        "lstart": fetch(mesh.polygons, "loop_start", np.int32),
        "ltotal": fetch(mesh.polygons, "loop_total", np.int32),
        "lv": fetch(mesh.loops, "vertex_index", np.int32),
        "le": fetch(mesh.loops, "edge_index", np.int32),
    }


def _planar_mask(A, tol):
    """Vrai pour les polygones plans à `tol` près (unités Blender, écart absolu) ; les triangles le sont toujours."""
    import numpy as np

    n = A["n_poly"]
    ok = np.ones(n, dtype=bool)
    lt, ls, lv, co, nrm, cen = A["ltotal"], A["lstart"], A["lv"], A["co"], A["nrm"], A["cen"]
    quads = np.nonzero(lt == 4)[0]
    if quads.size:
        Q = lv[ls[quads][:, None] + np.arange(4)]
        P = co[Q]
        dist = np.abs(np.einsum("nij,nj->ni", P - cen[quads][:, None, :], nrm[quads])).max(axis=1)
        ok[quads] = dist <= tol
    for p in np.nonzero(lt > 4)[0].tolist():
        P = co[lv[ls[p]:ls[p] + lt[p]]]
        ok[p] = bool((np.abs((P - cen[p]) @ nrm[p]) <= tol).all())
    return ok


def _plane_tolerance_in(co, k):
    """Tolérance de planéité en pouces : celle de SketchUp (0,001 po) plus le bruit des flottants 32 bits.

    Blender stocke les sommets en simple précision : à 100 m de l'origine, deux coordonnées voisines
    diffèrent de 8 microns. openskp exige 1e-6 de l'étendue de la face, soit moins que ce bruit pour
    une petite face loin de l'origine : toutes ces faces seraient refusées.
    """
    peak = float(abs(co).max()) * k if getattr(co, "size", 0) else 0.0
    return min(0.02, 0.001 + 1.2e-7 * peak)


def _fit_plane(points):
    """Plan (normale unitaire, distance) d'un contour par la méthode de Newell, ou None si dégénéré."""
    n = len(points)
    nx = ny = nz = 0.0
    for i in range(n):
        x0, y0, z0 = points[i]
        x1, y1, z1 = points[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length < 1e-9:
        return None
    nx, ny, nz = nx / length, ny / length, nz / length
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    cz = sum(p[2] for p in points) / n
    return (nx, ny, nz), nx * cx + ny * cy + nz * cz


def _fits_one_plane(outer, holes, tol_in):
    """Le contour et ses trous tiennent dans le plan du contour à `tol_in` près (pouces)."""
    plane = _fit_plane(outer)
    if plane is None:
        return False
    (nx, ny, nz), d = plane
    for ring in [outer] + list(holes):
        for p in ring:
            if abs(nx * p[0] + ny * p[1] + nz * p[2] - d) > tol_in:
                return False
    return True


# Tolérance de planéité imposée à l'écrivain openskp pendant un export (pouces).
_PLANE_TOL = [0.001]
_ARK_TOL_SRC_OLD = "tol = max(span, 1.0) * 1e-6"
_ARK_TOL_SRC_NEW = "tol = max(max(span, 1.0) * 1e-6, _ARK_PLANE_TOL[0])"


def _relaxed_plane_functions(mod):
    """Remplacements de `_plane_from_polygon` et `_is_coplanar` d'openskp avec la tolérance `_PLANE_TOL`."""
    SkpWriteError = mod.SkpWriteError

    def fit(points):
        n = len(points)
        nx = ny = nz = 0.0
        for i in range(n):
            x0, y0, z0 = points[i]
            x1, y1, z1 = points[(i + 1) % n]
            nx += (y0 - y1) * (z0 + z1)
            ny += (z0 - z1) * (x0 + x1)
            nz += (x0 - x1) * (y0 + y1)
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length < 1e-9:
            raise SkpWriteError("face points are collinear or degenerate; cannot compute a plane")
        nx, ny, nz = nx / length, ny / length, nz / length
        cx = sum(p[0] for p in points) / n
        cy = sum(p[1] for p in points) / n
        cz = sum(p[2] for p in points) / n
        d = nx * cx + ny * cy + nz * cz
        span = max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))
        return nx, ny, nz, d, max(max(span, 1.0) * 1e-6, _PLANE_TOL[0])

    def plane_from_polygon(points):
        nx, ny, nz, d, tol = fit(points)
        for p in points:
            dist = nx * p[0] + ny * p[1] + nz * p[2] - d
            if abs(dist) > tol:
                raise SkpWriteError(
                    f"face points are not coplanar (point {p} is {abs(dist):.6g} units "
                    "off the fitted plane) - openskp.create only supports planar faces"
                )
        return nx, ny, nz, d

    def is_coplanar(points):
        nx, ny, nz, d, tol = fit(points)
        return all(abs(nx * p[0] + ny * p[1] + nz * p[2] - d) <= tol for p in points)

    return plane_from_polygon, is_coplanar


class _relaxed_openskp:
    """Le temps d'un export, openskp accepte les faces planes à la tolérance de SketchUp près.

    Trois contrôles d'openskp comparent les sommets d'une face à son plan avec une tolérance de
    1e-6 de l'étendue de la face (contour, test de repli et trous). Le troisième est écrit en ligne
    dans `write_face` : on en recompile le texte avec la tolérance de `_PLANE_TOL`. Tout est remis
    en place à la sortie (la bibliothèque est partagée avec les autres add-ons) ; si la version
    d'openskp ne ressemble pas à celle attendue, rien n'est modifié et les faces limites sont
    simplement découpées en triangles.
    """

    def __enter__(self):
        import importlib
        import inspect
        import textwrap

        self._saved = {}
        self.patched = False
        try:
            mod = importlib.import_module("openskp.create")
            cls = mod._ArchiveWriter
            src = textwrap.dedent(inspect.getsource(cls.write_face))
            if src.count(_ARK_TOL_SRC_OLD) != 1:
                return self
            ns = {}
            mod.__dict__["_ARK_PLANE_TOL"] = _PLANE_TOL
            exec(compile(src.replace(_ARK_TOL_SRC_OLD, _ARK_TOL_SRC_NEW), "<arkedia write_face>", "exec"), mod.__dict__, ns)
            plane_fn, coplanar_fn = _relaxed_plane_functions(mod)
            self._saved = {
                "mod": mod, "cls": cls, "write_face": cls.write_face,
                "plane": mod._plane_from_polygon, "coplanar": mod._is_coplanar,
            }
            cls.write_face = ns["write_face"]
            mod._plane_from_polygon = plane_fn
            mod._is_coplanar = coplanar_fn
            self.patched = True
        except Exception:
            self._restore()
        return self

    def _restore(self):
        sv = self._saved
        if sv:
            try:
                sv["cls"].write_face = sv["write_face"]
                sv["mod"]._plane_from_polygon = sv["plane"]
                sv["mod"]._is_coplanar = sv["coplanar"]
                sv["mod"].__dict__.pop("_ARK_PLANE_TOL", None)
            except Exception:
                pass
        self._saved = {}
        self.patched = False

    def __exit__(self, *exc):
        self._restore()
        return False


def _drop_collinear(ring, flags):
    """Retire d'un contour les sommets alignés qui n'appartiennent qu'à la région fusionnée."""
    import numpy as np

    n = len(ring)
    if n <= 3 or not any(flags):
        return ring
    P = np.asarray(ring, dtype=np.float64)
    a = P - np.roll(P, 1, axis=0)
    b = np.roll(P, -1, axis=0) - P
    la, lb = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
    cross = np.linalg.norm(np.cross(a, b), axis=1)
    straight = (cross <= 1e-9 * la * lb + 1e-12) & (np.einsum("ij,ij->i", a, b) > 0)
    keep = ~(straight & np.asarray(flags, dtype=bool))
    if int(keep.sum()) < 3:
        return ring
    return [ring[i] for i in np.nonzero(keep)[0].tolist()]


_UV_FIT_TOL = 2e-3  # écart maximal (en répétitions d'image) entre les UV de Blender et une projection plane unique


def _uv_pins(xy, uv_loops, pos_loops, c0, u, v, k):
    """Trois points de calage (point en pouces, UV) qui reproduisent les UV de Blender sur une région plane.

    Les UV de tous les coins de la région doivent suivre une même fonction affine de la position dans le plan
    (u = a + b·x + c·y, idem pour v) : c'est le cas d'une dalle ou d'un mur déroulé d'un seul tenant. Sinon
    (îlots d'UV décalés, miroirs, coutures) la région ne peut pas devenir une seule face texturée : renvoie None.
    """
    import numpy as np

    M = np.column_stack([np.ones(len(pos_loops)), pos_loops[:, 0], pos_loops[:, 1]])
    uv64 = uv_loops.astype(np.float64)
    sol, *_ = np.linalg.lstsq(M, uv64, rcond=None)
    if float(np.abs(M @ sol - uv64).max()) > _UV_FIT_TOL:
        return None
    (x0, y0), (x1, y1) = xy.min(axis=0), xy.max(axis=0)
    if x1 - x0 < 1e-9 or y1 - y0 < 1e-9:
        return None
    pins = []
    for x, y in ((x0, y0), (x1, y0), (x0, y1)):
        w = c0 + x * u + y * v
        t = sol[0] + sol[1] * x + sol[2] * y
        pins.append(((round(float(w[0]) * k, 6), round(float(w[1]) * k, 6), round(float(w[2]) * k, 6)),
                     (float(t[0]), float(t[1]))))
    return pins


def _coplanar_groups(A, pts, k, skip_slots, planar, tol, exclude=None, uv=None, uv_slots=frozenset()):
    """Regroupe les polygones voisins, coplanaires et de même matériau en faces SketchUp.

    Un maillage IFC sort de Bonsai en triangles : sans cette étape, SketchUp affiche une
    diagonale sur chaque face. Les triangles coplanaires sont fusionnés (shapely, dans le plan
    de la face) en polygones avec leurs trous : une baie dans un mur devient un vrai trou,
    comme dans un modèle dessiné à la main. Les sommets alignés qui n'appartiennent qu'à la
    région (bord libre d'une dalle, contour d'un trou) sont supprimés.

    Pour un matériau texturé (`uv_slots`, avec les UV par coin `uv`), la région n'est fusionnée que si ses UV
    suivent une seule projection plane ; la face reçoit alors trois points de calage qui la reproduisent.

    Renvoie une liste de dictionnaires {members, mat, smooth, faces:[(extérieur, [trous])], uv_pins},
    les points étant en pouces et repris tels quels de `pts` (partage exact des sommets).
    Les polygones non fusionnables restent à la charge de l'appelant.
    """
    import numpy as np

    try:
        import shapely
        from shapely.geometry import Polygon
        from shapely.geometry.polygon import orient
    except Exception:
        return []

    n_poly = A["n_poly"]
    if n_poly < 2:
        return []
    co, nrm, cen, mat, smooth = A["co"], A["nrm"], A["cen"], A["mat"], A["smooth"]
    lstart, ltotal, lv, le = A["lstart"], A["ltotal"], A["lv"], A["le"]

    eligible = planar.copy()
    if skip_slots:
        eligible &= ~np.isin(mat, np.array(sorted(skip_slots), dtype=np.int32))
    if exclude is not None:
        eligible &= ~exclude

    # voisinage par arête (deux polygones qui partagent une arête)
    lp = np.repeat(np.arange(n_poly, dtype=np.int32), ltotal)
    order = np.argsort(le, kind="stable")
    le_s, lp_s = le[order], lp[order]
    idx = np.nonzero(le_s[1:] == le_s[:-1])[0]
    a, b = lp_s[idx], lp_s[idx + 1]
    ok = (a != b) & eligible[a] & eligible[b] & (mat[a] == mat[b]) & (smooth[a] == smooth[b])
    a, b = a[ok], b[ok]
    if a.size == 0:
        return []
    dots = np.einsum("ij,ij->i", nrm[a], nrm[b])
    d_ab = np.abs(np.einsum("ij,ij->i", nrm[a], cen[b] - cen[a]))
    d_ba = np.abs(np.einsum("ij,ij->i", nrm[b], cen[a] - cen[b]))
    ok = (dots > 1.0 - 1e-6) & (d_ab < tol) & (d_ba < tol)
    a, b = a[ok], b[ok]
    if a.size == 0:
        return []

    # composantes connectées (union-find ; scipy n'est pas livré avec Blender)
    parent = np.arange(n_poly).tolist()

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for x, y in zip(a.tolist(), b.tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry
    involved = np.unique(np.concatenate([a, b]))
    labels = np.fromiter((find(i) for i in involved.tolist()), dtype=np.int64, count=involved.size)
    order = np.argsort(labels, kind="stable")
    involved, labels = involved[order], labels[order]
    groups = np.split(involved, np.nonzero(labels[1:] != labels[:-1])[0] + 1)

    incident_total = np.bincount(lv, minlength=A["n_vert"])
    union_all = getattr(shapely, "union_all", None)
    if union_all is None:
        from shapely.ops import unary_union as union_all

    result = []
    for members in groups:
        if members.size < 2:
            continue
        try:
            n = nrm[members].mean(axis=0)
            length = float(np.linalg.norm(n))
            if length < 1e-9:
                continue
            n /= length
            c0 = cen[members[0]]
            vsets = [lv[lstart[p]:lstart[p] + ltotal[p]] for p in members.tolist()]
            cat = np.concatenate(vsets)
            allv = np.unique(cat)
            rel = co[allv] - c0
            if float(np.abs(rel @ n).max()) > tol:
                continue  # dérive de plan le long d'une grande région : on ne fusionne pas
            helper = np.zeros(3)
            helper[int(np.argmin(np.abs(n)))] = 1.0
            u = np.cross(helper, n)
            u /= np.linalg.norm(u)
            v = np.cross(n, u)
            xy = np.stack([rel @ u, rel @ v], axis=1)
            pins = None
            if uv is not None and int(mat[members[0]]) in uv_slots:
                loops = np.concatenate([np.arange(lstart[p], lstart[p] + ltotal[p]) for p in members.tolist()])
                pins = _uv_pins(xy, uv[loops], xy[np.searchsorted(allv, lv[loops])], c0, u, v, k)
                if pins is None:
                    continue  # UV qui ne suivent pas une projection plane unique : polygones séparés, chacun avec ses UV
            polys = [Polygon(xy[np.searchsorted(allv, vs)]) for vs in vsets]
            if not all(p.is_valid and p.area > 0 for p in polys):
                continue
            merged = union_all(polys)
            total = sum(p.area for p in polys)
            if (not merged.is_valid) or abs(merged.area - total) > 1e-6 * max(total, 1e-12):
                continue  # recouvrement ou faces en double : topologie d'origine conservée
            parts = [merged] if merged.geom_type == "Polygon" else [
                g for g in getattr(merged, "geoms", []) if g.geom_type == "Polygon"
            ]
            lookup = {(float(xy[i, 0]), float(xy[i, 1])): i for i in range(len(allv))}
            # sommet utilisé par aucun polygone hors de la région : supprimable s'il est aligné
            removable = np.bincount(np.searchsorted(allv, cat), minlength=len(allv)) == incident_total[allv]

            def to_ring(coords):
                ring, flags = [], []
                for x, y in coords:
                    li = lookup.get((float(x), float(y)))
                    if li is not None:
                        p3, fl = pts[int(allv[li])], bool(removable[li])
                    else:
                        w = c0 + x * u + y * v
                        p3, fl = (round(float(w[0]) * k, 6), round(float(w[1]) * k, 6), round(float(w[2]) * k, 6)), False
                    if not ring or ring[-1] != p3:
                        ring.append(p3)
                        flags.append(fl)
                if len(ring) > 1 and ring[0] == ring[-1]:
                    ring.pop()
                    flags.pop()
                return _drop_collinear(ring, flags)

            faces = []
            for part in parts:
                part = orient(part, 1.0)
                outer = to_ring(list(part.exterior.coords)[:-1])
                holes = [r for r in (to_ring(list(i.coords)[:-1]) for i in part.interiors) if len(r) >= 3]
                if len(outer) >= 3:
                    faces.append((outer, holes))
            if faces:
                m0 = int(members[0])
                result.append({"members": members.tolist(), "mat": int(mat[m0]),
                               "smooth": bool(smooth[m0]), "faces": faces, "uv_pins": pins})
        except Exception:
            continue
    return result


def _duplicate_polygons(A, k):
    """Polygones strictement identiques (mêmes sommets, même matériau), un seul à écrire.

    Un maillage booléen, un scan fusionné ou deux objets confondus laissent des faces superposées ;
    SketchUp, qui fusionne les faces confondues quand on dessine, afficherait un scintillement.
    Retourne (masque des doublons à ignorer, ensemble des polygones conservés dont un doublon est
    retourné : leur verso reçoit alors le même matériau).
    """
    import numpy as np

    n = A["n_poly"]
    if n < 2:
        return None, set()
    q = np.round(A["co"] * (k * 1e6)).astype(np.int64).astype(np.uint64)
    with np.errstate(over="ignore"):
        vh = _mix64(q[:, 2] + _mix64(q[:, 1] + _mix64(q[:, 0])))
        loops = _mix64(vh[A["lv"]])
        key = np.add.reduceat(loops, A["lstart"])
        key = _mix64(key ^ (A["ltotal"].astype(np.uint64) << np.uint64(40)) ^ (A["mat"].astype(np.uint64) << np.uint64(20)))
    order = np.argsort(key, kind="stable")
    ks = key[order]
    same = ks[1:] == ks[:-1]
    if not same.any():
        return None, set()
    run_start = np.concatenate(([True], ~same))
    first = order[np.maximum.accumulate(np.where(run_start, np.arange(ks.size), 0))]
    dup = np.zeros(n, dtype=bool)
    dup[order[1:][same]] = True
    kept = first[1:][same]
    gone = order[1:][same]
    flipped = np.einsum("ij,ij->i", A["nrm"][gone], A["nrm"][kept]) < -0.5
    return dup, set(kept[flipped].tolist())


def _soften_mask(A, angle_deg):
    """Polygones entourés de voisins presque coplanaires (angle entre normales ≤ `angle_deg` sur chaque arête).

    Les polygones qui touchent un bord libre du maillage n'en font pas partie : leur contour reste visible.
    """
    import numpy as np

    n_poly = A["n_poly"]
    lp = np.repeat(np.arange(n_poly, dtype=np.int32), A["ltotal"])
    order = np.argsort(A["le"], kind="stable")
    le_s, lp_s = A["le"][order], lp[order]
    idx = np.nonzero(le_s[1:] == le_s[:-1])[0]
    a, b = lp_s[idx], lp_s[idx + 1]
    keep = a != b
    a, b = a[keep], b[keep]
    if a.size == 0:
        return np.zeros(n_poly, dtype=bool)
    cosang = np.einsum("ij,ij->i", A["nrm"][a], A["nrm"][b])
    ang = np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))
    worst = np.zeros(n_poly)
    np.maximum.at(worst, a, ang)
    np.maximum.at(worst, b, ang)
    shared = np.bincount(np.concatenate([a, b]), minlength=n_poly)
    return (shared >= A["ltotal"]) & (worst <= angle_deg)


def _write_mesh(target, mesh, k, handles, textured, stats, use_uv, merge=True, soften=None):
    """Écrit les polygones d'un maillage Blender (unités de la scène) dans un groupe ou un composant.

    `soften` = {"angle": degrés, "min_faces": n} : les polygones d'un maillage d'au moins n faces dont tous les
    voisins sont à moins de `angle` degrés reçoivent des arêtes douces et lisses (comme l'outil Adoucir de SketchUp).
    Un terrain ou un maillage de scan de plusieurs centaines de milliers de triangles s'affiche ainsi ombré, et non
    noir sous le trait des arêtes. Les polygones qui gardent des arêtes vives sont écrits en premier : une arête
    partagée avec eux reste visible (SketchUp retient le réglage de la première face qui la crée).
    """
    import numpy as np

    A = _mesh_arrays(mesh)
    n_poly = A["n_poly"]
    if n_poly == 0:
        return
    co = A["co"]
    bad_vert = ~np.isfinite(co).all(axis=1)
    poly_nonfinite = None
    if bad_vert.any():
        co = np.where(bad_vert[:, None], 0.0, co)
        A["co"] = co
        poly_nonfinite = np.add.reduceat(bad_vert[A["lv"]].astype(np.int32), A["lstart"]) > 0
    pts = list(map(tuple, np.round(co * k, 6).tolist()))
    tol_in = _plane_tolerance_in(co, k)
    tol_bu = tol_in / k
    _PLANE_TOL[0] = tol_in
    planar = _planar_mask(A, tol_bu)
    lv_l, ls_l, lt_l = A["lv"].tolist(), A["lstart"].tolist(), A["ltotal"].tolist()
    mat_l, smooth_l = A["mat"].tolist(), A["smooth"].tolist()

    uv_arr = None
    if use_uv and textured and mesh.uv_layers.active is not None:
        uv_arr = np.empty(A["n_loop"] * 2, dtype=np.float32)
        mesh.uv_layers.active.data.foreach_get("uv", uv_arr)
        uv_arr = uv_arr.reshape(-1, 2)

    def uv_of(loops):
        return [(pts[lv_l[l]], (float(uv_arr[l, 0]), float(uv_arr[l, 1]))) for l in loops]

    def front_uv(p):
        s, t = ls_l[p], lt_l[p]
        loops = list(range(s, s + t))
        if t == 3:
            trio = loops
        else:
            P = co[A["lv"][loops]]
            best = None
            for i in range(1, t - 1):
                for j in range(i + 1, t):
                    area = float(np.linalg.norm(np.cross(P[i] - P[0], P[j] - P[0])))
                    if best is None or area > best[0]:
                        best = (area, i, j)
            if best is None or best[0] < 1e-12:
                return None
            trio = [loops[0], loops[best[1]], loops[best[2]]]
        return uv_of(trio)

    def handle_for(index):
        return handles[index] if 0 <= index < len(handles) else None

    absorbed = np.zeros(n_poly, dtype=bool)
    dup_mask, flipped_keep = _duplicate_polygons(A, k)
    if dup_mask is not None:
        absorbed |= dup_mask
        stats["faces_duplicate"] = stats.get("faces_duplicate", 0) + int(dup_mask.sum())
    if poly_nonfinite is not None:
        n_bad = int((poly_nonfinite & ~absorbed).sum())
        absorbed |= poly_nonfinite
        if n_bad:
            _skip_face(stats, ValueError("coordonnées non finies"), n_bad)

    if merge and n_poly > 1:
        textured_slots = {i for i, h in enumerate(handles) if h is not None and h in textured}
        # sans UV exploitables, un matériau texturé garde ses polygones séparés (rien ne dit comment l'étaler)
        skip = set() if uv_arr is not None else textured_slots
        try:
            groups = _coplanar_groups(A, pts, k, skip, planar, tol_bu, exclude=absorbed,
                                      uv=uv_arr, uv_slots=frozenset(textured_slots) if uv_arr is not None else frozenset())
        except Exception as exc:  # une fusion ratée ne doit jamais bloquer l'export
            groups = []
            stats["warnings"].append(f"fusion des faces coplanaires ignorée : {exc}")
        for grp in groups:
            if not all(_fits_one_plane(outer, holes, tol_in) for outer, holes in grp["faces"]):
                stats["groups_split"] = stats.get("groups_split", 0) + 1
                continue  # région trop gauchie pour une seule face : ses polygones passent un par un
            written = 0
            try:
                for outer, holes in grp["faces"]:
                    kw = {"material": handle_for(grp["mat"])}
                    if grp["smooth"]:
                        kw["soft_edges"] = True
                        kw["smooth_edges"] = True
                    if holes:
                        kw["holes"] = holes
                    if grp.get("uv_pins"):
                        kw["front_uv"] = grp["uv_pins"]
                    target.add_face(outer, **kw)
                    written += 1
            except Exception:
                stats["groups_split"] = stats.get("groups_split", 0) + 1
                if written == 0:
                    continue  # rien d'écrit : les polygones d'origine passent par la boucle ci-dessous
            absorbed[grp["members"]] = True
            stats["faces"] += written
            stats["faces_merged"] = stats.get("faces_merged", 0) + len(grp["members"])
            stats["holes"] = stats.get("holes", 0) + sum(len(h) for _, h in grp["faces"])

    soft_l = None
    sequence = range(n_poly)
    if soften and n_poly >= soften["min_faces"]:
        dense = _soften_mask(A, soften["angle"]) & ~absorbed
        if dense.any():
            stats["objects_softened"] = stats.get("objects_softened", 0) + 1
            stats["faces_softened"] = stats.get("faces_softened", 0) + int(dense.sum())
            soft_l = dense.tolist()
            soft_all = dense | A["smooth"]
            sequence = np.concatenate([np.nonzero(~soft_all)[0], np.nonzero(soft_all)[0]]).tolist()

    bad = []
    for p in sequence:
        if absorbed[p]:
            continue
        if not planar[p]:
            bad.append(p)
            continue
        s, t = ls_l[p], lt_l[p]
        ring = [pts[i] for i in lv_l[s:s + t]]
        kwargs = {"material": handle_for(mat_l[p])}
        if smooth_l[p] or (soft_l is not None and soft_l[p]):
            kwargs["soft_edges"] = True
            kwargs["smooth_edges"] = True
        if p in flipped_keep and kwargs["material"] is not None:
            kwargs["back_material"] = kwargs["material"]
        if uv_arr is not None and kwargs["material"] is not None and kwargs["material"] in textured:
            uv = front_uv(p)
            if uv:
                kwargs["front_uv"] = uv
        try:
            target.add_face(ring, **kwargs)
            stats["faces"] += 1
        except Exception as exc:
            if t > 3 and "coplanar" in str(exc):
                bad.append(p)  # presque plan mais refusé : découpé en triangles
            else:
                _skip_face(stats, exc)
    if bad:
        mesh.calc_loop_triangles()
        nt = len(mesh.loop_triangles)
        tv = np.empty(nt * 3, dtype=np.int32)
        tl = np.empty(nt * 3, dtype=np.int32)
        tp = np.empty(nt, dtype=np.int32)
        tm = np.empty(nt, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tv)
        mesh.loop_triangles.foreach_get("loops", tl)
        mesh.loop_triangles.foreach_get("polygon_index", tp)
        mesh.loop_triangles.foreach_get("material_index", tm)
        tv, tl = tv.reshape(-1, 3), tl.reshape(-1, 3)
        for i in np.nonzero(np.isin(tp, np.unique(np.asarray(bad, dtype=np.int32))))[0].tolist():
            handle = handle_for(int(tm[i]))
            kwargs = {"material": handle}
            if smooth_l[int(tp[i])] or (soft_l is not None and soft_l[int(tp[i])]):
                kwargs["soft_edges"] = True
                kwargs["smooth_edges"] = True
            if uv_arr is not None and handle is not None and handle in textured:
                kwargs["front_uv"] = uv_of(tl[i].tolist())
            try:
                target.add_face([pts[j] for j in tv[i].tolist()], **kwargs)
                stats["faces"] += 1
                stats["faces_triangulated"] += 1
            except Exception as exc:
                _skip_face(stats, exc)


def _is_collection_instance(obj):
    return obj.type == "EMPTY" and obj.instance_type == "COLLECTION" and obj.instance_collection is not None


def _flatten_collection(coll, matrix, depth=0, seen=frozenset()):
    """(objet, matrice) de tout ce qu'une instance de `coll` affiche : sous-collections et instances imbriquées."""
    if depth > 6 or coll.name_full in seen:
        return
    seen = seen | {coll.name_full}
    for ob in coll.objects:
        if ob.hide_viewport:
            continue
        if ob.type in _MESHLIKE:
            yield ob, matrix @ ob.matrix_world
        elif _is_collection_instance(ob):
            inner = ob.instance_collection
            offset = mathutils.Matrix.Translation(-mathutils.Vector(inner.instance_offset))
            yield from _flatten_collection(inner, matrix @ ob.matrix_world @ offset, depth + 1, seen)
    for child in coll.children:
        yield from _flatten_collection(child, matrix, depth, seen)


# --- vue enregistrée dans le fichier ------------------------------------------------------------
#
# openskp écrit une caméra « Iso » parallèle à 173 pouces (4,4 m) de l'origine. SketchUp web découpe tout
# ce qui se trouve entre l'œil et le plan de coupe : un bâtiment de plus de quelques mètres s'ouvre
# amputé de moitié, avec des murs manquants et des bandes de couleur. On recadre donc la caméra sur la
# boîte englobante du modèle. Les octets modifiés sont ceux de la caméra du gabarit d'openskp
# (décalages absolus, valeurs lues avant d'écrire : si elles ne sont pas celles attendues, rien n'est touché).
_CAM_EYE, _CAM_TARGET, _CAM_UP = 2987, 3011, 3035
_CAM_PERSPECTIVE, _CAM_FOV, _CAM_HEIGHT = 3075, 3076, 3084
_CAM_EXPECTED = ((100.0, -100.0, 100.0), (0.0, 0.0, 0.0), (-0.40824829046386, 0.40824829046386, 0.81649658092773))
_CAM_DIRECTION = (1.0, -1.0, 1.0)  # œil au sud-est, en hauteur : la vue « Iso » classique de SketchUp
_CAM_FOV_DEG = 30.0
_CAM_MARGIN = 1.08
_CAM_MIN_RADIUS_IN = 12.0


def _frame_camera(buf, lo, hi, mode="PERSPECTIVE"):
    """Recadre sur place (`buf` : bytearray du .skp) la caméra enregistrée sur la boîte (lo, hi) en pouces.

    L'œil recule juste assez pour que les huit coins de la boîte tiennent dans l'angle de vue de 30 degrés
    (la plus petite dimension de la fenêtre), avec 8 % de marge. Renvoie True si la caméra a été écrite.
    """
    import struct

    if len(buf) < _CAM_HEIGHT + 8:
        return False
    try:
        got = tuple(struct.unpack_from("<3d", buf, off) for off in (_CAM_EYE, _CAM_TARGET, _CAM_UP))
        if any(abs(a - b) > 1e-6 for g, e in zip(got, _CAM_EXPECTED) for a, b in zip(g, e)):
            return False
        if any(not math.isfinite(v) for v in tuple(lo) + tuple(hi)):
            return False
        center = [(a + b) / 2.0 for a, b in zip(lo, hi)]
        radius = max(math.sqrt(sum(((b - a) / 2.0) ** 2 for a, b in zip(lo, hi))), _CAM_MIN_RADIUS_IN)
        half = math.radians(_CAM_FOV_DEG / 2.0)
        norm = math.sqrt(sum(c * c for c in _CAM_DIRECTION))
        view = [c / norm for c in _CAM_DIRECTION]  # de la cible vers l'œil
        up = (-view[2] * view[0], -view[2] * view[1], 1.0 - view[2] * view[2])  # +Z projeté sur le plan de vue
        un = math.sqrt(sum(c * c for c in up))
        up = [c / un for c in up]
        fwd = [-c for c in view]
        right = (fwd[1] * up[2] - fwd[2] * up[1], fwd[2] * up[0] - fwd[0] * up[2], fwd[0] * up[1] - fwd[1] * up[0])
        reach, dist = 0.0, 1.1 * radius
        for cx in (lo[0], hi[0]):
            for cy in (lo[1], hi[1]):
                for cz in (lo[2], hi[2]):
                    o = (cx - center[0], cy - center[1], cz - center[2])
                    lateral = max(abs(sum(o[i] * right[i] for i in range(3))), abs(sum(o[i] * up[i] for i in range(3))))
                    reach = max(reach, lateral)
                    dist = max(dist, sum(o[i] * view[i] for i in range(3)) + _CAM_MARGIN * lateral / math.tan(half))
        if mode != "PERSPECTIVE":
            dist = max(dist, _CAM_MARGIN * radius / math.sin(half))  # œil hors du modèle : pas de coupe en vue parallèle
        eye = [center[i] + view[i] * dist for i in range(3)]
        struct.pack_into("<3d", buf, _CAM_EYE, *eye)
        struct.pack_into("<3d", buf, _CAM_TARGET, *center)
        struct.pack_into("<3d", buf, _CAM_UP, *up)
        buf[_CAM_PERSPECTIVE] = 1 if mode == "PERSPECTIVE" else 0
        struct.pack_into("<d", buf, _CAM_FOV, _CAM_FOV_DEG)
        height = 2.0 * dist * math.tan(half) if mode == "PERSPECTIVE" else 2.0 * _CAM_MARGIN * max(reach, _CAM_MIN_RADIUS_IN / 2.0)
        struct.pack_into("<d", buf, _CAM_HEIGHT, height)
        return True
    except Exception:
        return False


# --- unités d'affichage ------------------------------------------------------------------------------
#
# Le gabarit d'openskp s'ouvre en pouces, format architectural : 2,80 m s'affiche « 9' 2 1/4" » et une surface en
# pouces carrés. On réécrit donc les entiers du dictionnaire d'options « UnitsOptions » du gabarit (même longueur,
# aucun décalage). Sens des valeurs, vérifié dans SketchUp 2027 : LengthUnit 0 pouce, 1 pied, 2 mm, 3 cm, 4 m ;
# LengthFormat 0 décimal ; AreaUnit 0 po², 1 pied², 2 mm², 3 cm², 4 m² ; VolumeUnit 0 po³, 1 pied³, 2 mm³, 3 cm³, 4 m³.
_UNIT_PRESETS = {
    "METERS": {"LengthUnit": 4, "LengthFormat": 0, "LengthPrecision": 3, "AreaUnit": 4, "VolumeUnit": 4},
    "CENTIMETERS": {"LengthUnit": 3, "LengthFormat": 0, "LengthPrecision": 1, "AreaUnit": 4, "VolumeUnit": 4},
    "MILLIMETERS": {"LengthUnit": 2, "LengthFormat": 0, "LengthPrecision": 0, "AreaUnit": 4, "VolumeUnit": 4},
}


def _units_choice(context, units):
    """Réglage d'unités à écrire : « SCENE » reprend celui de la scène Blender, « INCHES » laisse le gabarit."""
    if units != "SCENE":
        return units
    settings = context.scene.unit_settings
    if settings.system == "IMPERIAL":
        return "INCHES"
    return {"MILLIMETERS": "MILLIMETERS", "CENTIMETERS": "CENTIMETERS"}.get(settings.length_unit, "METERS")


def _set_units(buf, preset):
    """Écrit sur place (`buf` : bytearray du .skp) les unités d'affichage du réglage `preset`. Renvoie True si fait."""
    values = _UNIT_PRESETS.get(preset)
    if not values:
        return False
    head = 16384  # le dictionnaire d'options est au début du fichier, dans la partie reprise du gabarit
    spots = []
    for key in values:
        tag = bytes([len(key)]) + key.encode("utf-16-le") + b"\x04"
        at = buf.find(tag, 0, head)
        if at < 0 or buf.find(tag, at + 1, head) >= 0 or at + len(tag) + 4 > len(buf):
            return False  # gabarit inattendu : on ne touche à rien
        spots.append((at + len(tag), values[key]))
    for pos, value in spots:
        buf[pos:pos + 4] = int(value).to_bytes(4, "little")
    return True


def _scene_bounds(pool, inst_empties, inst_parts, depsgraph, use_modifiers):
    """Boîte englobante monde (unités Blender) de ce qui est exporté : (mini, maxi) ou None."""
    import numpy as np

    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)

    def grow(matrix, bound_box):
        corners = np.array([(c[0], c[1], c[2], 1.0) for c in bound_box], dtype=np.float64)
        world = (corners @ np.array(matrix, dtype=np.float64).T)[:, :3]
        world = world[np.isfinite(world).all(axis=1)]
        if world.size:
            np.minimum(lo, world.min(axis=0), out=lo)
            np.maximum(hi, world.max(axis=0), out=hi)

    for obj in pool:
        holder = obj
        if obj.type != "MESH" or (use_modifiers and obj.modifiers):
            try:
                holder = obj.evaluated_get(depsgraph)
            except Exception:
                holder = obj
        try:
            grow(obj.matrix_world, holder.bound_box)
        except Exception:
            continue
    for e in inst_empties:
        entry = inst_parts.get(e.instance_collection.name_full)
        for ob, mtx in (entry[1] if entry else ()):
            try:
                grow(e.matrix_world @ mtx, ob.bound_box)
            except Exception:
                continue
    if np.isfinite(lo).all() and np.isfinite(hi).all() and (hi >= lo).all():
        return lo, hi
    return None


def export_skp(filepath, context, *args, **options):
    """Exporte la scène en .skp (voir `_export_skp_impl` pour les options), tolérance de planéité assouplie."""
    with _relaxed_openskp() as patch:
        stats = _export_skp_impl(filepath, context, *args, **options)
        stats["plane_patch"] = patch.patched
        if not patch.patched:
            stats["warnings"].append(
                "tolérance de planéité d'openskp non assouplie (version inattendue) : les faces presque planes "
                "sont découpées en triangles")
    return stats


_SOFTEN_ANGLE_DEG = 35.0
_SOFTEN_MIN_FACES = 2000


def _export_skp_impl(filepath, context, only_selected=True, use_components=True, use_modifiers=True,
                     layer_mode="COLLECTION", use_textures=True, store_attributes=True, export_psets=True,
                     merge_planar=True, view_mode="PERSPECTIVE", soften_dense=True, units="SCENE",
                     soften_angle=_SOFTEN_ANGLE_DEG, export_spaces=False, hide_spaces=True,
                     space_inset_mm=_SPACE_INSET_MM, space_area_in_name=True):
    from openskp import create

    t0 = time.time()
    k = _scene_k(context)
    uf = _unit_factor(context)
    inset_bu = max(0.0, float(space_inset_mm or 0.0)) * 1e-3 * uf
    soften = {"angle": min(89.0, max(1.0, float(soften_angle))), "min_faces": _SOFTEN_MIN_FACES} if soften_dense else None
    depsgraph = context.evaluated_depsgraph_get()

    selection = only_selected and bool(context.selected_objects)
    candidates = context.selected_objects if selection else context.scene.objects
    pool = [o for o in candidates if o.type in _MESHLIKE and o.visible_get()]
    inst_empties = [o for o in candidates if _is_collection_instance(o) and o.visible_get()]
    ignored = [o for o in candidates if o.type in ("GPENCIL", "GREASEPENCIL", "VOLUME", "POINTCLOUD", "CURVES")
               and o.visible_get()]

    need_ifc = store_attributes or export_spaces or layer_mode in ("IFC_STOREY", "IFC_CLASS")
    tool = _bonsai_tool() if need_ifc else None

    # pièces (IfcSpace) : Bonsai les masque ; elles partent quand même, avec leur étiquette et une matière translucide.
    # Avec « Sélection uniquement », seules celles des niveaux touchés par la sélection.
    spaces = set()
    if export_spaces:
        in_layer = context.view_layer.objects
        wanted_storeys = None
        if selection:
            wanted_storeys = set()
            for o in context.selected_objects:
                ent = _ifc_entity(tool, o)
                if _is_ifc_space(o, ent) and o.type in _MESHLIKE:
                    spaces.add(o.name)
                st = _ifc_storey_name(ent) if ent is not None else None
                if st:
                    wanted_storeys.add(st)
        for o in context.scene.objects:
            if o.type not in _MESHLIKE or o.name in spaces or o.name not in in_layer:
                continue
            ent = _ifc_entity(tool, o)
            if not _is_ifc_space(o, ent):
                continue
            if wanted_storeys is not None:
                st = _ifc_storey_name(ent) if ent is not None else None
                if st is None or st not in wanted_storeys:
                    continue
            spaces.add(o.name)
        in_pool = {o.name for o in pool}
        pool = pool + [o for o in context.scene.objects if o.name in spaces and o.name not in in_pool]

    if not pool and not inst_empties:
        raise RuntimeError("Aucun objet maillage à exporter (sélection vide ou masquée).")
    tmpdir = tempfile.mkdtemp(prefix="arkedia_skp_")
    stats = {
        "objects": 0, "components": 0, "instances": 0, "groups": 0, "faces": 0, "faces_skipped": 0,
        "faces_triangulated": 0, "faces_merged": 0, "holes": 0, "materials": 0, "textured_materials": 0,
        "layers": 0, "warnings": [], "objects_skipped": 0, "collection_instances": 0,
    }
    wm = context.window_manager
    total_steps = max(1, len(pool) + len(inst_empties))
    step = [0]

    def tick():
        step[0] += 1
        if step[0] % 25 == 0:
            try:
                wm.progress_update(min(step[0], total_steps))
            except Exception:
                pass

    try:
        wm.progress_begin(0, total_steps)
    except Exception:
        pass

    try:
        builder = create()

        # contenu des collections instanciées (aplati, matrices intégrées)
        inst_parts = {}
        for e in inst_empties:
            coll = e.instance_collection
            if coll.name_full in inst_parts:
                continue
            offset = mathutils.Matrix.Translation(-mathutils.Vector(coll.instance_offset))
            inst_parts[coll.name_full] = (coll, list(_flatten_collection(coll, offset)))

        # 1) matériaux (avant tout le reste : contrainte du format)
        handle_by_mat, textured = {}, set()
        mat_sources = [o for o in pool if o.name not in spaces]
        for _coll, parts in inst_parts.values():
            mat_sources.extend(ob for ob, _m in parts)
        for obj in mat_sources:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None or mat.name in handle_by_mat:
                    continue
                name, rgb, opacity, image_path = _material_info(mat, tmpdir, stats["warnings"] if use_textures else None)
                if image_path and use_textures:
                    try:
                        h = _add_texture(builder, name, image_path, opacity)
                        textured.add(h)
                        stats["textured_materials"] += 1
                    except Exception as exc:
                        stats["warnings"].append(f"matériau « {mat.name} » : texture non écrite ({exc}), couleur unie utilisée")
                        h = builder.add_material(name, rgb, opacity=opacity)
                else:
                    h = builder.add_material(name, rgb, opacity=opacity)
                handle_by_mat[mat.name] = h
        # matières des pièces : translucides, sans texture ; « (volume) » si la même matière sert aussi au bâti
        space_handle, space_default = {}, None
        for obj in pool:
            if obj.name not in spaces:
                continue
            mats = [s.material for s in obj.material_slots if s.material is not None]
            if not mats and space_default is None:
                space_default = builder.add_material("Pièce (volume)", _SPACE_DEFAULT_RGB, opacity=_SPACE_OPACITY)
            for mat in mats:
                if mat.name in space_handle:
                    continue
                name, rgb, opacity, _img = _material_info(mat, tmpdir, None)
                op = opacity if (opacity is not None and opacity < _SPACE_OPACITY) else _SPACE_OPACITY
                if mat.name in handle_by_mat:
                    name = _clean_material_name(name + " (volume)")
                space_handle[mat.name] = builder.add_material(name, rgb, opacity=op)
        stats["materials"] = len(handle_by_mat) + len(space_handle) + (1 if space_default is not None else 0)
        stats["spaces"] = len(spaces)
        stats["spaces_inset"] = 0
        stats["spaces_not_inset"] = []
        stats["space_inset_mm"] = round(inset_bu / uf * 1e3, 3) if spaces else 0.0

        # 2) infos IFC + calques (avant les définitions)
        infos, psets, layer_of = {}, {}, {}
        coll_index = _collection_index() if (store_attributes or layer_mode != "NONE") else {}
        for obj in pool + inst_empties:
            info, dicts = _ifc_info(obj, tool, export_psets and store_attributes) if tool is not None else ({}, [])
            infos[obj.name], psets[obj.name] = info, dicts
            if obj.name in spaces:
                layer_of[obj.name] = _space_layer(layer_mode, info)
            else:
                layer_of[obj.name] = _object_layer(obj, layer_mode, info, coll_index)
        # étiquette qui ne porte que des pièces : couleur à part, masquée à l'ouverture si demandé
        members = {}
        for obj in pool + inst_empties:
            nm = layer_of.get(obj.name)
            if nm:
                members.setdefault(_clean_layer_name(nm), set()).add(obj.name in spaces)
        space_tags = {nm for nm, kinds in members.items() if kinds == {True}}
        layer_handle = {}
        for name in sorted(members):
            if name in space_tags:
                layer_handle[name] = builder.add_layer(name, color=_SPACE_TAG_RGB, hidden=bool(hide_spaces))
            else:
                layer_handle[name] = builder.add_layer(name)
        stats["layers"] = len(layer_handle)
        stats["space_layers"] = sorted(space_tags)
        stats["space_layers_hidden"] = bool(hide_spaces and space_tags)

        def layer_for(obj):
            nm = layer_of.get(obj.name)
            return layer_handle.get(_clean_layer_name(nm)) if nm else None

        # 3) regroupement des maillages partagés (composants)
        share = {}
        if use_components:
            counts = {}
            for obj in pool:
                if obj.type == "MESH" and obj.data is not None and not obj.modifiers and obj.name not in spaces:
                    counts[obj.data.name_full] = counts.get(obj.data.name_full, 0) + 1
            share = {n: c for n, c in counts.items() if c >= 2}

        def object_attrs(obj):
            d = {"blender_object": obj.name}
            d.update(infos.get(obj.name, {}))
            colls = [c.name for c in coll_index.get(obj.name_full, ()) if c.name != "Scene Collection"]
            if colls:
                d["blender_collection"] = colls[0]
            for key in obj.keys():
                if key.startswith(("_", "skp_")) or key in ("cycles",):
                    continue
                v = _attr_value(obj[key]) if not hasattr(obj[key], "to_dict") else None
                if v is not None:
                    d.setdefault(f"custom_{key}", v)
            return _clean_attrs(d)

        def attribute_kwargs(obj):
            if not store_attributes:
                return {}
            attrs = object_attrs(obj)
            if psets.get(obj.name):
                return {"attribute_dicts": [("ARKEDIA", attrs)] + psets[obj.name]}
            return {"attributes": attrs, "attribute_dict_name": "ARKEDIA"}

        def evaluated_mesh(obj):
            """(porteur, maillage temporaire) ; le porteur doit appeler to_mesh_clear()."""
            holder = obj
            if obj.type != "MESH" or (use_modifiers and obj.modifiers):
                try:
                    holder = obj.evaluated_get(depsgraph)
                except Exception:
                    holder = obj
            mesh = holder.to_mesh()
            return holder, mesh

        def handles_of(obj):
            if obj.name in spaces:
                hs = [space_handle.get(s.material.name) if s.material else space_default for s in obj.material_slots]
                return hs or [space_default]
            return [handle_by_mat.get(s.material.name) if s.material else None for s in obj.material_slots]

        def group_name(obj):
            return _space_label(obj, infos.get(obj.name, {})) if obj.name in spaces else obj.name

        def transform_args(obj):
            mw = obj.matrix_world
            t = mw.translation * k
            return (t.x, t.y, t.z), _matrix3_row_major(mw.to_3x3())

        vertex_color_objects = 0

        # 4) définitions de composants : maillages partagés, puis collections instanciées
        definitions = {}
        for obj in pool:
            key = obj.data.name_full if (obj.type == "MESH" and obj.data is not None) else None
            if key in share and key not in definitions and obj.data.polygons:
                holder, mesh = evaluated_mesh(obj)
                try:
                    with builder.add_component_definition(_su(obj.data.name)) as cd:
                        _write_mesh(cd, mesh, k, handles_of(obj), textured, stats, use_textures, merge_planar, soften)
                    definitions[key] = cd
                    stats["components"] += 1
                finally:
                    holder.to_mesh_clear()

        coll_definitions = {}
        for cname, (coll, parts) in inst_parts.items():
            if not parts:
                continue
            try:
                with builder.add_component_definition(_su(coll.name)) as cd:
                    wrote = 0
                    for ob, mtx in parts:
                        holder, mesh = evaluated_mesh(ob)
                        try:
                            if not len(mesh.polygons):
                                continue
                            mesh.transform(mtx)
                            if mtx.determinant() < 0:
                                mesh.flip_normals()
                            _write_mesh(cd, mesh, k, handles_of(ob), textured, stats, use_textures, merge_planar, soften)
                            wrote += 1
                        finally:
                            holder.to_mesh_clear()
                coll_definitions[cname] = cd if wrote else None
                if wrote:
                    stats["components"] += 1
            except Exception as exc:
                stats["warnings"].append(f"collection « {coll.name} » non exportée : {exc}")

        # 5) groupes (objets uniques)
        placed_later = []
        for obj in pool:
            tick()
            key = obj.data.name_full if (obj.type == "MESH" and obj.data is not None) else None
            if key in definitions:
                placed_later.append((obj, definitions[key]))
                continue
            if obj.type == "MESH" and (obj.data is None or not obj.data.polygons) and not (use_modifiers and obj.modifiers):
                stats["objects_skipped"] += 1
                continue
            holder, mesh = evaluated_mesh(obj)
            rebuilt = None
            try:
                if not len(mesh.polygons):
                    stats["objects_skipped"] += 1
                    continue
                if obj.type == "MESH" and obj.data is not None and len(obj.data.color_attributes):
                    vertex_color_objects += 1
                name = group_name(obj)
                out_mesh = mesh
                if obj.name in spaces:
                    # surface exacte dans le nom (avant le retrait), puis faces rentrées contre le moirage
                    if space_area_in_name:
                        area = _ifc_space_area_m2(_ifc_entity(tool, obj), tool)
                        if area is None:
                            area = _mesh_floor_area_m2(mesh, obj.matrix_world, uf)
                        name = _space_label(obj, infos.get(obj.name, {}), area)
                    if inset_bu > 0:
                        how, out = _inset_space(mesh, obj.matrix_world, inset_bu)
                        if how is None:
                            stats["spaces_not_inset"].append(name)
                        else:
                            stats["spaces_inset"] += 1
                            if how == "emprise":
                                rebuilt = out_mesh = out
                                stats["spaces_rebuilt"] = stats.get("spaces_rebuilt", 0) + 1
                trans, m3 = transform_args(obj)
                kw = attribute_kwargs(obj)
                with builder.add_group(_su(name), translation=trans, matrix3x3=m3, layer=layer_for(obj), **kw) as grp:
                    _write_mesh(grp, out_mesh, k, handles_of(obj), textured, stats, use_textures, merge_planar, soften)
                stats["groups"] += 1
                stats["objects"] += 1
            finally:
                holder.to_mesh_clear()
                if rebuilt is not None:
                    bpy.data.meshes.remove(rebuilt)

        # 6) instances : maillages partagés, puis collections instanciées
        for obj, definition in placed_later:
            tick()
            trans, m3 = transform_args(obj)
            builder.add_instance(definition, name=_su(obj.name), translation=trans, matrix3x3=m3,
                                 layer=layer_for(obj), **attribute_kwargs(obj))
            stats["instances"] += 1
            stats["objects"] += 1
        for e in inst_empties:
            tick()
            definition = coll_definitions.get(e.instance_collection.name_full)
            if definition is None:
                stats["objects_skipped"] += 1
                continue
            trans, m3 = transform_args(e)
            builder.add_instance(definition, name=_su(e.name), translation=trans, matrix3x3=m3,
                                 layer=layer_for(e), **attribute_kwargs(e))
            stats["instances"] += 1
            stats["collection_instances"] += 1
            stats["objects"] += 1

        data = bytearray(builder.to_bytes())
        stats["view"] = "openskp"
        if view_mode in ("PERSPECTIVE", "PARALLEL"):
            bounds = _scene_bounds(pool, inst_empties, inst_parts, depsgraph, use_modifiers)
            if bounds is not None and _frame_camera(data, bounds[0] * k, bounds[1] * k, view_mode):
                stats["view"] = view_mode.lower()
            else:
                stats["warnings"].append(
                    "vue enregistrée non recadrée (boîte englobante ou gabarit openskp inattendus) : "
                    "dans SketchUp, utiliser Caméra > Zoom étendu si le modèle semble coupé")
        preset = _units_choice(context, units)
        stats["units"] = "gabarit (pouces)"
        if preset in _UNIT_PRESETS:
            if _set_units(data, preset):
                stats["units"] = preset.lower()
            else:
                stats["warnings"].append(
                    "unités d'affichage non écrites (gabarit openskp inattendu) : le fichier s'ouvre en pouces, "
                    "à régler dans SketchUp (Fenêtre > Infos du modèle > Unités)")
        part = filepath + ".part"
        try:
            with open(part, "wb") as f:
                f.write(data)
            os.replace(part, filepath)
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
        del data
    finally:
        try:
            wm.progress_end()
        except Exception:
            pass
        # nettoyage des textures temporaires
        try:
            for fn in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, fn))
            os.rmdir(tmpdir)
        except OSError:
            pass

    # contrôles avant livraison
    scale_len = context.scene.unit_settings.scale_length
    far = [o.name for o in pool + inst_empties if o.matrix_world.translation.length * scale_len > 20000]
    if far:
        stats["warnings"].append(f"{len(far)} objet(s) à plus de 20 km de l'origine (précision réduite dans SketchUp)")
    if abs(scale_len - 1.0) > 1e-9:
        stats["warnings"].append(f"échelle d'unité de la scène = {scale_len:g} (prise en compte)")
    if stats.get("faces_duplicate"):
        stats["warnings"].append(f"{stats['faces_duplicate']} face(s) en double (mêmes sommets, même matériau) écrite(s) une seule fois")
    if stats.get("faces_degenerate"):
        stats["warnings"].append(f"{stats['faces_degenerate']} face(s) sans surface (points alignés) ignorée(s)")
    if stats["faces_skipped"]:
        stats["warnings"].append(f"{stats['faces_skipped']} face(s) refusée(s) par le format SKP et ignorée(s)")
    for reason, n in sorted(stats.get("skip_reasons", {}).items(), key=lambda kv: -kv[1])[:3]:
        stats["warnings"].append(f"  motif : {reason} (x{n})")
    if vertex_color_objects:
        stats["warnings"].append(
            f"{vertex_color_objects} objet(s) avec couleurs de sommets : SketchUp ne les gère pas, "
            "convertir en texture (cuisson) avant l'export")
    if ignored:
        stats["warnings"].append(f"{len(ignored)} objet(s) de type non géré ignoré(s) (crayon gras, volume, nuage de points, cheveux)")
    if stats.get("spaces_not_inset"):
        noms = ", ".join(stats["spaces_not_inset"][:4]) + ("…" if len(stats["spaces_not_inset"]) > 4 else "")
        stats["warnings"].append(
            f"{len(stats['spaces_not_inset'])} pièce(s) gardée(s) sans retrait (volume non fermé ou trop mince) : "
            f"{noms} ; leurs faces peuvent scintiller avec les sols et les murs dans SketchUp")
    if stats["faces"] > 500_000:
        stats["warnings"].append(
            f"modèle lourd ({stats['faces']} faces) : SketchUp devient lent au-delà de 500 000 faces ; "
            "exporter par zones ou décimer les maillages de scan")
    stats["seconds"] = round(time.time() - t0, 3)
    stats["bytes"] = os.path.getsize(filepath)
    return stats


# --------------------------------------------------------------------------
# Opérateurs et menus
# --------------------------------------------------------------------------


class ARKEDIA_OT_import_skp(bpy.types.Operator, ImportHelper):
    """Importer un fichier SketchUp avec instances, calques, matériaux nommés et scènes"""

    bl_idname = "import_scene.arkedia_skp"
    bl_label = "Importer SketchUp Arkedia (.skp)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".skp"
    filter_glob: StringProperty(default="*.skp", options={"HIDDEN"})

    keep_hierarchy: BoolProperty(name="Conserver la hiérarchie des groupes", default=True)
    import_scenes: BoolProperty(name="Scènes SketchUp en caméras", default=True)
    store_attributes: BoolProperty(name="Conserver GUID et attributs (propriétés personnalisées)", default=True)
    drop_back_faces: BoolProperty(
        name="Ignorer les faces arrière dupliquées",
        description="Évite de doubler la géométrie quand le dos d'une face SketchUp n'a pas la couleur de son recto",
        default=True,
    )
    skip_memory_check: BoolProperty(
        name="Ignorer la vérification de mémoire",
        description="Importer même si la mémoire disponible semble insuffisante pour ce fichier (risque de blocage)",
        default=False,
    )

    def execute(self, context):
        try:
            s = import_skp(self.filepath, context, self.keep_hierarchy, self.import_scenes, self.store_attributes,
                           self.drop_back_faces, memory_check=not self.skip_memory_check)
        except Exception as exc:
            self.report({"ERROR"}, f"Import SKP impossible : {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"SKP importé en {s['seconds']} s : {s['unique_meshes']} maillages uniques, {s['placements']} placements, "
            f"{s['materials']} matériaux, {s['layers']} calques, {s['cameras']} caméras",
        )
        if s.get("back_faces_dropped") or s.get("degenerate_dropped"):
            self.report(
                {"INFO"},
                f"{s.get('back_faces_dropped', 0)} verso(s) dupliqué(s) et {s.get('degenerate_dropped', 0)} "
                "triangle(s) sans surface écartés",
            )
        return {"FINISHED"}


class ARKEDIA_OT_export_skp(bpy.types.Operator, ExportHelper):
    """Exporter vers SketchUp : groupes et composants natifs, calques, matériaux, attributs IFC"""

    bl_idname = "export_scene.arkedia_skp"
    bl_label = "Exporter SketchUp Arkedia (.skp)"
    bl_options = {"REGISTER"}

    filename_ext = ".skp"
    filter_glob: StringProperty(default="*.skp", options={"HIDDEN"})

    only_selected: BoolProperty(name="Sélection uniquement (sinon tout le visible)", default=True)
    use_components: BoolProperty(name="Maillages partagés en composants", default=True)
    use_modifiers: BoolProperty(name="Appliquer les modificateurs", default=True)
    layer_mode: EnumProperty(
        name="Calques SketchUp",
        items=[
            ("COLLECTION", "Collection Blender", "Un calque par collection"),
            ("IFC_STOREY", "Niveau IFC", "Un calque par niveau (IfcBuildingStorey)"),
            ("IFC_CLASS", "Classe IFC", "Un calque par classe (IfcWall, IfcSlab...)"),
            ("NONE", "Aucun", "Calque par défaut"),
        ],
        default="COLLECTION",
    )
    use_textures: BoolProperty(name="Textures image", default=True)
    store_attributes: BoolProperty(name="Attributs (classe, GlobalId, nom IFC)", default=True)
    export_psets: BoolProperty(name="Jeux de propriétés IFC", default=True)
    export_spaces: BoolProperty(
        name="Pièces (IfcSpace)",
        description=(
            "Exporter aussi les volumes de pièces d'un projet Bonsai, même masqués : translucides, nommés « Pièce 01 "
            "Chambre, 5,69 m² », sur une étiquette « Pièces - <niveau> ». Avec « Sélection uniquement », les pièces "
            "sélectionnées et celles des niveaux touchés par la sélection"
        ),
        default=False,
    )
    hide_spaces: BoolProperty(
        name="Étiquette des pièces masquée à l'ouverture",
        description="Les pièces sont dans le fichier ; un clic sur leur étiquette dans SketchUp les affiche",
        default=True,
    )
    space_inset: FloatProperty(
        name="Retrait des pièces (mm)",
        description=(
            "Rentre les faces de chaque pièce de cette distance. Sans retrait, elles tombent sur les sols, plafonds "
            "et murs, et SketchUp les fait scintiller (moirage). Les surfaces et volumes exacts restent dans le nom "
            "de la pièce et dans ses attributs IFC. 0 : volumes exacts"
        ),
        default=_SPACE_INSET_MM, min=0.0, max=50.0, precision=1,
    )
    space_area_in_name: BoolProperty(
        name="Surface dans le nom des pièces",
        description="Ajoute la surface de la pièce (NetFloorArea de l'IFC) à son nom : « Pièce 01 Chambre, 5,69 m² »",
        default=True,
    )
    merge_planar: BoolProperty(
        name="Fusionner les triangles coplanaires",
        description="Une face SketchUp par surface plane (avec ses trous), au lieu d'un triangle par maille",
        default=True,
    )
    soften_dense: BoolProperty(
        name="Adoucir les maillages denses",
        description=(
            "Pour les objets de 2 000 faces et plus (terrain, maillage de scan) : arêtes douces et lisses entre faces "
            "voisines à moins de 35 degrés, comme l'outil Adoucir de SketchUp. Sans cela SketchUp dessine chaque "
            "arête et un grand maillage paraît noir"
        ),
        default=True,
    )
    soften_angle: FloatProperty(
        name="Angle d'adoucissement (degrés)",
        description=(
            "Deux faces voisines dont les normales diffèrent de moins que cet angle partagent une arête douce. "
            "À relever (50 à 60) si un maillage bruité garde des arêtes noires parsemées"
        ),
        default=35.0, min=1.0, max=89.0,
    )
    units: EnumProperty(
        name="Unités dans SketchUp",
        description="Unités d'affichage du fichier. Le gabarit d'openskp s'ouvre en pouces, format architectural",
        items=[
            ("SCENE", "Comme la scène Blender", "Mètres, centimètres ou millimètres selon les unités de la scène"),
            ("METERS", "Mètres", "Longueurs en mètres (2,800 m), surfaces en m²"),
            ("CENTIMETERS", "Centimètres", "Longueurs en centimètres (280,0 cm), surfaces en m²"),
            ("MILLIMETERS", "Millimètres", "Longueurs en millimètres (2800 mm), surfaces en m²"),
            ("INCHES", "Pouces", "Réglage du gabarit : pouces, format architectural"),
        ],
        default="SCENE",
    )
    view_mode: EnumProperty(
        name="Vue enregistrée",
        description="Caméra avec laquelle le fichier s'ouvre dans SketchUp",
        items=[
            ("PERSPECTIVE", "Perspective cadrée", "Vue d'ensemble en perspective, cadrée sur tout le modèle"),
            ("PARALLEL", "Isométrique cadrée", "Vue d'ensemble en projection parallèle, cadrée sur tout le modèle"),
            ("DEFAULT", "Vue d'openskp", "Vue fixe près de l'origine : un grand modèle s'ouvre coupé dans SketchUp web"),
        ],
        default="PERSPECTIVE",
    )

    def execute(self, context):
        try:
            s = export_skp(
                self.filepath, context, only_selected=self.only_selected, use_components=self.use_components,
                use_modifiers=self.use_modifiers, layer_mode=self.layer_mode, use_textures=self.use_textures,
                store_attributes=self.store_attributes, export_psets=self.export_psets,
                merge_planar=self.merge_planar, view_mode=self.view_mode,
                soften_dense=self.soften_dense, soften_angle=self.soften_angle, units=self.units,
                export_spaces=self.export_spaces, hide_spaces=self.hide_spaces,
                space_inset_mm=self.space_inset, space_area_in_name=self.space_area_in_name,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Export SKP impossible : {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"SKP exporté en {s['seconds']} s : {s['groups']} groupes, {s['components']} composants "
            f"({s['instances']} instances), {s['faces']} faces ({s['faces_merged']} polygones fusionnés, "
            f"{s['holes']} trous), {s['materials']} matériaux, {s['layers']} calques",
        )
        if s.get("objects_softened"):
            self.report(
                {"INFO"},
                f"{s['objects_softened']} maillage(s) dense(s) adouci(s) ({s['faces_softened']} faces) : "
                f"arêtes douces entre faces voisines à moins de {self.soften_angle:g} degrés",
            )
        if self.export_spaces:
            if s.get("spaces"):
                where = ", ".join(s.get("space_layers") or []) or "sans étiquette"
                hidden = " (masquées à l'ouverture)" if s.get("space_layers_hidden") else ""
                inset = f", rentrées de {s['space_inset_mm']:g} mm" if s.get("spaces_inset") else ""
                self.report({"INFO"}, f"{s['spaces']} pièce(s) exportée(s) : {where}{hidden}{inset}")
            else:
                self.report({"WARNING"}, "aucune pièce (IfcSpace) trouvée dans la scène")
        for w in s["warnings"]:
            self.report({"WARNING"}, w)
        return {"FINISHED"}


def _menu_import(self, _context):
    self.layout.operator(ARKEDIA_OT_import_skp.bl_idname, text="SketchUp Arkedia (.skp)")


def _menu_export(self, _context):
    self.layout.operator(ARKEDIA_OT_export_skp.bl_idname, text="SketchUp Arkedia (.skp)")


_classes = (ARKEDIA_OT_import_skp, ARKEDIA_OT_export_skp)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
