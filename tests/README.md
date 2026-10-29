# Essais de l'add-on

Ces scripts servent à vérifier que l'export et l'import tiennent sur des modèles légers comme lourds, et à
mesurer le temps et la mémoire. Ils tournent dans Blender en arrière-plan, sans interface, et n'ont besoin que
de Blender 5.1 ou 5.2 sous Windows 64 bits (les roues compilées jointes à l'add-on sont celles de ce système).

## Précaution : un profil Blender jetable

Lancé avec `--factory-startup` sur le profil réel, Blender peut purger les bibliothèques installées pour les
extensions (dossier `extensions/.local/lib/python3.13/site-packages`), et l'add-on cesse alors de fonctionner
jusqu'à sa réinstallation. Les lanceurs de ce dossier (`driver.py` et `run_blender.py`) isolent donc Blender dans
un profil temporaire (`tests/.sandbox`, variable `ARK_SANDBOX` pour le déplacer). Si vous lancez Blender vous-même
avec `--factory-startup`, faites de même avec les variables `BLENDER_USER_RESOURCES`, `BLENDER_USER_EXTENSIONS`,
`BLENDER_USER_CONFIG` et `BLENDER_USER_SCRIPTS`, vers des dossiers qui existent déjà (sinon Blender lit les
préférences du profil réel).

## Mise en route

Il faut un Python ordinaire pour les lanceurs (n'importe quelle version 3.9 ou plus récente) et le chemin de
Blender, trouvé tout seul s'il est installé à l'endroit habituel, sinon à donner par la variable `ARK_BLENDER`.

```
set ARK_BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
python tests\driver.py resultats 4 degenerate transforms mm modifiers unicode collinst boxes:2000+ inst:30000+ sphere:6+
python tests\summarize.py resultats
```

Au premier lancement, les roues de `arkedia_skp_bridge/wheels/` sont dépaquetées dans `tests/.site-<empreinte>`,
un dossier par jeu de roues : une nouvelle version d'openskp donne un nouveau dossier. Pour tester une autre copie
de l'add-on, pointer `ARK_DEV` vers le dossier qui contient son sous-dossier `arkedia_skp_bridge/`.

## Le banc de charge (`driver.py`, `harness.py`)

`driver.py <dossier> <plafond_Go> <cas>...` lance, pour chaque cas, un premier processus Blender qui construit
la scène, la mesure et l'exporte en `.skp`, puis un second qui réimporte le fichier, mesure de nouveau et compare
la surface totale, le volume, la boîte englobante et le nombre de triangles. Avec un `+` derrière le cas
(`boxes:2000+`), le second processus va plus loin : il réexporte le modèle réimporté, le réimporte encore et
compare avec la scène d'origine. Un `!` garde les fichiers `.skp`. Le plafond de mémoire (en Go) coupe le
processus qui le dépasse et le consigne dans le résultat.

| Cas | Ce que le cas construit |
|---|---|
| `boxes:N` | N murs de tailles et de matériaux variés (deux matériaux par maillage), répartis sur 10 niveaux |
| `inst:N` | N copies d'une même chaise (72 triangles) qui partagent un seul maillage : N instances d'un composant |
| `sphere:S` | une icosphère de subdivision S (S = 8 donne 327 680 triangles) |
| `gridflat:K` | une grille plane de K × K cases, entièrement coplanaire (elle doit se fusionner en une seule face) |
| `gridholes:K` | la même grille percée de trous réguliers |
| `terrain:K` | la même grille avec un relief bruité, sans aucune face coplanaire |
| `degenerate` | faces dégénérées : surface nulle, sommets confondus, quadrilatère gauchi, trois faces sur une arête, micro-triangle, polygone concave, arêtes libres |
| `transforms` | échelles négatives (miroirs), rotation avec échelle non uniforme, enfant cisaillé d'un parent tourné, objet à 6 700 km de l'origine, objet minuscule, décalages delta |
| `mm` | scène réglée en millimètres (échelle d'unité 0,001) |
| `modifiers` | un réseau de 50 copies, un miroir, une solidification, un biseau, et une sphère lissée subdivisée : tout est évalué à l'export |
| `mod:<nom>` | un seul modificateur à la fois : `array`, `mirror`, `solid`, `bevel` ou `sub` |
| `texture:N` | N plans texturés (images aléatoires de 1 024 × 1 024 et 2 048 × 2 048 pixels) |
| `unicode` | noms accentués, japonais, emoji, noms de 300 caractères, noms en double ou à caractères spéciaux, propriétés personnalisées très longues, un objet masqué |
| `collinst` | collections instanciées : décalage d'instance, imbrication, miroir, échelle négative |
| `pieces` | pièces façon Bonsai (volumes « IfcSpace/… » masqués, collés au sol, au plafond et aux murs) : trois rectangulaires, une en L, une qui contourne une trémie collée au mur. Export avec l'option pièces ; à la relecture, chacune doit être rentrée de 5 mm, nommée avec sa surface et rangée sur une étiquette masquée |
| `niveaux` | deux niveaux façon Bonsai (collections « IfcBuildingStorey/… », sans IFC chargé), chacun avec dalle, murs, vitre translucide et pièce masquée. Export par niveau avec les pièces ; relu par openskp, le fichier doit avoir cinq scènes qui masquent les bonnes étiquettes, quatre étiquettes, le nom et la surface de chaque pièce en texte, et le verso de chaque face peint de la matière du recto |

Les mesures de mémoire sont celles de la mémoire engagée par le processus Blender, relevée toutes les 50 ms.

## Les autres scripts

| Script | Rôle |
|---|---|
| `run_blender.py <script> [args]` | lance un script de ce dossier dans Blender, avec le profil jetable |
| `feature_model.py <dossier>` | construit la « maison d'essai » (murs à fenêtres et porte, dalle, terrasse texturée, toiture, annexe, chaises dont une en miroir, vitrages en composant partagé, collection instanciée, matériaux dont un transparent) et l'exporte |
| `check_roundtrip.py <origine.blend> <export.skp> <rapport.json>` | compare, unité par unité, la scène d'origine avec sa réimportation : centre de surface, aire, volume, boîte englobante. Un miroir mal rendu apparaît ici alors qu'un contrôle global ne le voit pas |
| `mem_import.py <fichier.skp> <plafond_Go> <journal>` | mémoire d'un import par phase : lecture, scène instanciée, construction dans Blender |
| `guard_test.py <journal> <fichier.skp>...` | décision du garde-fou mémoire de l'import, avec la mémoire réelle puis des mémoires simulées de 4, 8 et 16 Go |
| `render_readme.py <source.blend\|.skp> <image.png>` | rendu Workbench d'une scène, utilisé pour les images du README |
| `check_desktop_saved.py <rapport.json> <référence.skp> <copie.skp>...` | relit le fichier d'origine et ses copies réenregistrées par SketchUp (formats 2013, 2017, 2020, 2021, 2027) et compare objets, triangles, aire, volume, boîte englobante, matériaux. Les rapports valent 1 quand SketchUp n'a rien déformé |
| `diff_objects.py <rapport.json> <référence.skp> <autre.skp> [nodrop]` | compare deux fichiers objet par objet : aire, volume signé, faces dont la normale est inversée d'un fichier à l'autre. À réserver aux fichiers de quelques milliers d'objets : sur 100 000 objets il demande plus de 5 Go de mémoire |
| `terrain_demo.py <dossier> [côté] [bruit] [angle]` | exporte le même relief bruité avec et sans adoucissement des arêtes, pour comparer les deux rendus dans SketchUp |
| `summarize.py <dossier>...` | tableau des résultats d'un ou plusieurs dossiers du banc de charge (le dernier l'emporte) |
| `verify_install.py <fichier.skp> <sortie.skp>` | contrôle d'une extension installée (voir plus bas) |

Le dossier `bench/` contient les outils qui ont servi à comprendre et à corriger les lenteurs : micro-mesure
des appels `bpy` à l'import (`bench_bpy.py`), parcours de la liste des objets de Blender selon l'ordre des noms
(`bench_walk.py`), profils de l'import, de l'export et de la lecture par openskp (`prof_*.py`), et essai des
méthodes d'écriture d'une image en PNG (`image_export_test.py`). Deux outils de diagnostic complètent la série
pour les surfaces : `dump_faces.py` compare le sens des contours que lit openskp avec la normale enregistrée dans le fichier,
et `dbg_backdrop.py` liste, pour chaque définition, les primitives et les triangles écartés comme versos dupliqués.
`dbg_materials.py` affiche les matériaux, les styles et les calques que lit openskp : c'est lui qui a montré les matériaux
synthétiques `Layer_<calque>` des fichiers de SketchUp 2021 et suivants, à l'origine des faces retournées de la 0.2.0.

## Vérifier l'installation du zip

Pour contrôler l'archive telle qu'un utilisateur la reçoit, dans un profil Blender vierge :

```
set BLENDER_USER_RESOURCES=%CD%\tests\.sandbox_install
set BLENDER_USER_EXTENSIONS=%BLENDER_USER_RESOURCES%\extensions
set BLENDER_USER_CONFIG=%BLENDER_USER_RESOURCES%\config
set BLENDER_USER_SCRIPTS=%BLENDER_USER_RESOURCES%\scripts
mkdir "%BLENDER_USER_CONFIG%" "%BLENDER_USER_EXTENSIONS%" "%BLENDER_USER_SCRIPTS%"
blender --command extension build --source-dir arkedia_skp_bridge --output-dir dist
blender --command extension install-file -r user_default -e dist\arkedia_skp_bridge-0.2.1.zip
blender -b --factory-startup --python tests\verify_install.py -- exemples\maison_test.skp sortie.skp
```

La dernière commande doit afficher `OK_VERIF`.

Pour essayer le dépôt d'extensions avant de le publier, servir le dossier `docs/` en local, ajouter le dépôt dans
le même profil jetable, installer l'extension depuis lui, puis relancer le contrôle sans `--factory-startup` (ce
réglage ignore les préférences, donc le dépôt ajouté) :

```
python -m http.server 8765 --directory docs --bind 127.0.0.1
blender --command extension repo-add --name "Arkedia test" --url http://127.0.0.1:8765/extensions/index.json arkedia_test
blender --command extension install -s -e arkedia_skp_bridge
blender -b --python tests\verify_install.py -- exemples\maison_test.skp sortie.skp
```
