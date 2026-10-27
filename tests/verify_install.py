# -*- coding: utf-8 -*-
"""Vérifie qu'une extension INSTALLÉE fonctionne : activation, opérateurs, import puis export d'un fichier.

Installer d'abord le zip (ou l'extension depuis un dépôt distant) dans un profil Blender jetable, puis lancer
Blender avec le même profil. Voir « Vérifier l'installation du zip » dans tests/README.md. Exemple :

    blender -b --factory-startup --python tests\\verify_install.py -- exemples\\maison_test.skp sortie.skp

Pour une extension installée depuis un dépôt distant, retirer --factory-startup : ce réglage ignore les
préférences, donc aussi le dépôt ajouté.

Le script n'utilise pas le dossier tests/.site : les bibliothèques viennent de l'installation de l'extension, comme
chez un utilisateur. Il affiche OK_VERIF à la fin si tout est passé.
"""
import os
import sys

import addon_utils
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = args[0], args[1]

name = None
for m in addon_utils.modules(refresh=True):
    if m.__name__.endswith(".arkedia_skp_bridge"):
        name = m.__name__
if name is None:
    sys.stdout.write("ECHEC : extension arkedia_skp_bridge introuvable (installée ?)\n")
    sys.stdout.flush()
    os._exit(2)
sys.stdout.write("module trouvé : %s\n" % name)

addon_utils.enable(name, default_set=False, persistent=False)
mod = sys.modules[name]
import openskp  # noqa: E402  (installée avec l'extension)
sys.stdout.write("openskp %s depuis %s\n" % (getattr(openskp, "__version__", "?"), os.path.dirname(openskp.__file__)))

assert hasattr(bpy.ops.import_scene, "arkedia_skp"), "opérateur d'import absent"
assert hasattr(bpy.ops.export_scene, "arkedia_skp"), "opérateur d'export absent"

# scène vide, sans recharger les préférences (qui contiennent le dépôt d'extensions)
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
r = bpy.ops.import_scene.arkedia_skp(filepath=SRC)
assert r == {"FINISHED"}, "import : %r" % (r,)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
sys.stdout.write("import : %d objets maillés\n" % len(meshes))
assert meshes, "aucun maillage importé"

bpy.ops.object.select_all(action="DESELECT")
r = bpy.ops.export_scene.arkedia_skp(filepath=OUT, only_selected=False)
assert r == {"FINISHED"}, "export : %r" % (r,)
size = os.path.getsize(OUT)
sys.stdout.write("export : %d octets\n" % size)
assert size > 1000

stats = mod.import_skp(OUT, bpy.context)
sys.stdout.write("réimport : %s objets, %s s\n" % (stats["objects"], stats["seconds"]))
sys.stdout.write("OK_VERIF\n")
sys.stdout.flush()
os._exit(0)
