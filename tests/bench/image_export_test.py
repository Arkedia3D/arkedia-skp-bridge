# -*- coding: utf-8 -*-
"""Essai des méthodes d'écriture d'une image Blender en PNG (images générées, modifiées, fichiers, empaquetées).

blender -b --factory-startup --python image_export_test.py -- <dossier_sortie>
"""
import bpy, sys, os, json, zlib, struct
import numpy as np

out = sys.argv[sys.argv.index("--") + 1]
os.makedirs(out, exist_ok=True)
W, H = 16, 12


def decode_png(path):
    """Décodeur PNG minimal (8 bits, RGB ou RGBA, sans entrelacement) -> tableau (H, W, C) uint8."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None, "signature PNG absente (%r)" % data[:4]
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, ctype, _, _, inter = ihdr
    if depth != 8 or ctype not in (2, 6) or inter:
        return None, "format PNG non géré %r" % (ihdr,)
    ch = 3 if ctype == 2 else 4
    raw = zlib.decompress(idat)
    stride = w * ch
    img = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    p = 0
    for y in range(h):
        f = raw[p]
        line = np.frombuffer(raw[p + 1:p + 1 + stride], dtype=np.uint8).astype(np.int32)
        p += 1 + stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            line = (line + prev) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        img[y] = line
        prev = line
    return img.reshape(h, w, ch), None


def make_pixels(alpha=1.0):
    px = np.zeros((H, W, 4), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            px[y, x] = (x / (W - 1), y / (H - 1), 0.25 + 0.5 * ((x + y) % 2), alpha)
    return px


def gen(name, float_buffer=False, alpha=False):
    img = bpy.data.images.new(name, W, H, alpha=alpha, float_buffer=float_buffer)
    img.pixels.foreach_set(make_pixels().ravel())
    img.update()
    return img


# --- méthodes -------------------------------------------------------------------------------------


def m_copy_save(img, path):
    tmp = img.copy()
    try:
        tmp.filepath_raw = path
        tmp.file_format = "PNG"
        tmp.save()
    finally:
        bpy.data.images.remove(tmp)


def m_save_filepath(img, path):
    old = img.file_format
    before = (img.filepath_raw, img.source)
    img.file_format = "PNG"
    try:
        img.save(filepath=path)
    finally:
        img.file_format = old
    return {"filepath_changed": (img.filepath_raw, img.source) != before}


def m_save_render(img, path):
    sc = bpy.data.scenes.new("tmp_skp")
    try:
        sc.view_settings.view_transform = "Standard"
        sc.view_settings.look = "None"
        sc.view_settings.exposure = 0.0
        sc.view_settings.gamma = 1.0
        sc.display_settings.display_device = "sRGB"
        st = sc.render.image_settings
        st.file_format = "PNG"
        st.color_mode = "RGBA"
        st.color_depth = "8"
        st.compression = 15
        img.save_render(path, scene=sc)
    finally:
        bpy.data.scenes.remove(sc)


METHODS = {"copy_save": m_copy_save, "save_filepath": m_save_filepath, "save_render": m_save_render}


def reference(img):
    """Pixels de l'image telle que Blender la lit (flottants 0-1), en uint8 approximatif."""
    n = len(img.pixels)
    a = np.empty(n, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def run_case(label, img):
    info = {"source": img.source, "dirty": bool(img.is_dirty), "packed": bool(img.packed_file), "depth": img.depth,
            "float": bool(img.is_float), "colorspace": img.colorspace_settings.name, "file_format": img.file_format}
    ref = reference(img)
    info["ref_mean_rgb"] = [round(float(v), 4) for v in ref[..., :3].mean(axis=(0, 1))]
    res = {}
    for mname, fn in METHODS.items():
        path = os.path.join(out, "%s__%s.png" % (label, mname))
        r = {}
        try:
            extra = fn(img, path)
            if isinstance(extra, dict):
                r.update(extra)
            dec, err = decode_png(path)
            if dec is None:
                r["erreur_decodage"] = err
            else:
                rgb = dec[..., :3].astype(np.float32) / 255.0
                r["mean_rgb"] = [round(float(v), 4) for v in rgb.mean(axis=(0, 1))]
                r["noir"] = bool(dec[..., :3].max() == 0)
                r["ecart_max_vs_ref"] = round(float(np.abs(rgb - ref[..., :3]).max()), 4)
                r["canaux"] = int(dec.shape[2])
        except Exception as exc:
            r["exception"] = "%s: %s" % (type(exc).__name__, exc)
        res[mname] = r
    return {"info": info, "methodes": res}


results = {}

# 1. image générée RVB (comme le parquet), pixels peints par script
results["generee_rvb"] = run_case("generee_rvb", gen("generee_rvb"))
# 2. image générée avec alpha
results["generee_alpha"] = run_case("generee_alpha", gen("generee_alpha", alpha=True))
# 3. image générée flottante
results["generee_float"] = run_case("generee_float", gen("generee_float", float_buffer=True))

# 4. fichier JPEG, 5. fichier PNG (chargés depuis le disque)
base = gen("base_pour_fichiers")
jpg = os.path.join(out, "source.jpg")
png = os.path.join(out, "source.png")
base.filepath_raw = jpg
base.file_format = "JPEG"
base.save()
base.filepath_raw = png
base.file_format = "PNG"
base.save()
img_jpg = bpy.data.images.load(jpg)
img_png = bpy.data.images.load(png)
results["fichier_jpeg"] = run_case("fichier_jpeg", img_jpg)
results["fichier_png"] = run_case("fichier_png", img_png)

# 6. fichier PNG modifié en mémoire (is_dirty) : les pixels du disque ne sont plus ceux affichés
img_dirty = bpy.data.images.load(png)
img_dirty.name = "dirty"
px = make_pixels()
px[..., 0] = 1.0 - px[..., 0]
img_dirty.pixels.foreach_set(px.ravel())
img_dirty.update()
results["fichier_modifie"] = run_case("fichier_modifie", img_dirty)

# 7. image empaquetée
img_pack = bpy.data.images.load(png)
img_pack.name = "pack"
img_pack.pack()
results["empaquetee"] = run_case("empaquetee", img_pack)

# 8. image générée empaquetée
g2 = gen("generee_pack")
g2.pack()
results["generee_empaquetee"] = run_case("generee_empaquetee", g2)

json.dump(results, open(os.path.join(out, "resultats_images.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("FIN_ESSAI_IMAGES")
