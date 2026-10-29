# -*- coding: utf-8 -*-
"""Réglage des chemins pour les scripts de test, qui tournent dans Blender en arrière-plan.

Les scripts commencent par :

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _env
    _env.setup()

setup() ajoute à sys.path :

* les bibliothèques compilées (openskp, shapely, mapbox_earcut, defusedxml). Les roues de
  arkedia_skp_bridge/wheels/ sont dépaquetées une fois dans tests/.site-<empreinte>, un dossier par jeu de roues :
  changer une roue (nouvelle version d'openskp) donne un nouveau dossier, jamais un mélange avec l'ancienne. La
  variable ARK_SITE désigne un autre dossier si on préfère en utiliser un existant (par exemple le site-packages
  des extensions de Blender) ;
* la racine du dépôt, qui contient le dossier arkedia_skp_bridge/. La variable ARK_DEV désigne un autre dossier
  (une copie de travail, une version à comparer) contenant lui aussi un dossier arkedia_skp_bridge/.

Les roues fournies sont celles de Windows 64 bits pour Python 3.13, la version embarquée dans Blender 5.1 et 5.2.
"""
import glob
import hashlib
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def site_dir():
    site = os.environ.get("ARK_SITE")
    if site:
        return site
    wheels = os.path.join(REPO, "arkedia_skp_bridge", "wheels")
    names = sorted(n for n in os.listdir(wheels) if n.endswith(".whl")) if os.path.isdir(wheels) else []
    site = os.path.join(HERE, ".site-" + hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:10])
    stamp = os.path.join(site, ".extrait")
    if not os.path.exists(stamp) and os.path.isdir(wheels):
        os.makedirs(site, exist_ok=True)
        for name in sorted(os.listdir(wheels)):
            if name.endswith(".whl"):
                with zipfile.ZipFile(os.path.join(wheels, name)) as z:
                    z.extractall(site)
        with open(stamp, "w", encoding="utf-8") as f:
            f.write("roues dépaquetées\n")
    return site


def dev_dir():
    return os.environ.get("ARK_DEV") or REPO


def setup():
    for p in (site_dir(), dev_dir()):
        if p not in sys.path:
            sys.path.insert(0, p)
    # shapely charge ses DLL Windows depuis son propre dossier
    if hasattr(os, "add_dll_directory"):
        for sub in ("shapely.libs", os.path.join("shapely", "DLLs")):
            d = os.path.join(site_dir(), sub)
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass


# --- côté « lanceur » (Python ordinaire, hors de Blender) -----------------------------------------------------

def blender_exe():
    """Chemin de Blender : variable ARK_BLENDER, sinon la version la plus récente trouvée dans les emplacements usuels."""
    exe = os.environ.get("ARK_BLENDER")
    if exe:
        return exe
    found = shutil.which("blender")
    if found:
        return found
    candidates = []
    for pattern in (r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
                    r"C:\Program Files (x86)\Blender Foundation\Blender *\blender.exe",
                    "/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender", "/snap/bin/blender"):
        candidates += glob.glob(pattern)
    if not candidates:
        raise SystemExit("Blender introuvable : définir la variable d'environnement ARK_BLENDER.")
    return sorted(candidates)[-1]


def sandbox_dir():
    return os.environ.get("ARK_SANDBOX") or os.path.join(HERE, ".sandbox")


def sandbox_env():
    """Environnement qui isole Blender du profil de l'utilisateur.

    Lancé avec --factory-startup sur le profil réel, Blender peut purger les bibliothèques installées pour les
    extensions (dossier extensions/.local). Les essais tournent donc toujours dans un profil jetable."""
    box = sandbox_dir()
    dossiers = {"BLENDER_USER_EXTENSIONS": "extensions", "BLENDER_USER_CONFIG": "config", "BLENDER_USER_SCRIPTS": "scripts"}
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = box
    for variable, sous_dossier in dossiers.items():
        chemin = os.path.join(box, sous_dossier)
        # les dossiers doivent exister : s'ils manquent, Blender lit les préférences du profil réel
        os.makedirs(chemin, exist_ok=True)
        env[variable] = chemin
    env.update(ARK_DEV=dev_dir(), ARK_SITE=site_dir())
    return env
