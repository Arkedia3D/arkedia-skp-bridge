# -*- coding: utf-8 -*-
"""Liste les matériaux, styles et calques lus par openskp : blender -b --factory-startup --python dbg_materials.py -- <rapport.json> <fichier.skp>..."""
import sys, os, json, traceback

ARGS = sys.argv[sys.argv.index("--") + 1:]
REPORT, FILES = ARGS[0], ARGS[1:]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import _env  # noqa: E402
_env.setup()
import openskp  # noqa: E402


def main():
    rep = {}
    for p in FILES:
        try:
            m = openskp.SkpFile.open(p).parse()
            rep[os.path.basename(p)] = {
                "version": m.version, "units": m.units,
                "materiaux": [{"nom": x.name, "couleur": list(x.color), "transparence": x.transparency, "id": x.id,
                               "texture": bool(x.texture), "colorise": x.colorized} for x in m.materials],
                "ids": {str(k): v.name for k, v in list(m.materials_by_id.items())[:40]},
                "styles": [{"nom": s.name, "avant": s.front_color, "arriere": s.back_color} for s in m.styles],
                "calques": [{"nom": l.name, "couleur": [l.color_r, l.color_g, l.color_b] if hasattr(l, "color_r") else None}
                            for l in m.layers],
            }
        except BaseException as exc:  # noqa
            rep[os.path.basename(p)] = {"erreur": "%s: %s" % (type(exc).__name__, exc), "trace": traceback.format_exc()[-1200:]}
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sys.stdout.write("FIN\n")
    sys.stdout.flush()
    os._exit(0)


main()
