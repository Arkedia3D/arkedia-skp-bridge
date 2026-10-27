# Journal des modifications

## 0.2.0, 27 octobre 2026 : première version publique

Cette version est la première diffusée hors d'ARKEDIA 3D. Elle a été validée par une série d'essais de charge
(de 7 Ko à 85 Mo, jusqu'à 100 000 composants) décrite dans le README, et par l'ouverture de la maison d'essai exportée dans
SketchUp pour le web.

### Import

- Un composant placé 1 000 fois coûte un seul maillage : les copies sont de vrais objets Blender qui partagent
  ce maillage. On peut les convertir en IFC, les exporter ou les éditer sans « rendre les instances réelles ».
- Les étiquettes (calques) SketchUp deviennent des collections, les groupes gardent leur hiérarchie, les scènes
  deviennent des caméras, les arêtes isolées (lignes, courbes) deviennent des objets d'arêtes.
- Matériaux nommés comme dans SketchUp, couleurs converties de sRGB en linéaire, transparence, textures.
- GUID, attributs et propriétés SketchUp conservés en propriétés personnalisées (`skp_*`).
- Fonctionne dans un Blender dont l'interface n'est pas en anglais : les nœuds de shader sont cherchés par type,
  jamais par nom.
- Lecture des deux générations de fichiers SketchUp (2013 à 2020 et 2021 et suivants) grâce à openskp.
- Les doubles faces dupliquées et les triangles sans surface sont écartés.
- Contrôle de mémoire avant l'import : un fichier trop lourd pour la mémoire disponible est refusé avec un message
  clair, au lieu de figer la machine. L'option « Ignorer la vérification de mémoire » force l'import.
- Barre de progression pendant l'import.

### Export

- Groupes et composants natifs. Les maillages partagés deviennent des définitions de composants.
- Une face SketchUp par surface plane, trous compris, au lieu d'un triangle par maille : les murs et les toits
  unis s'ouvrent sans diagonales dans SketchUp.
- Calques au choix : collections Blender, niveaux IFC, classes IFC, ou aucun.
- Matériaux : couleur, transparence, textures image.
- Bonsai (IFC) : classe, GlobalId, nom et type prédéfini écrits dans le dictionnaire d'attributs « ARKEDIA »,
  jeux de propriétés dans des dictionnaires `IFC_<jeu>`. Propriétés personnalisées Blender exportées en `custom_*`.
- Modificateurs appliqués, échelles négatives (miroirs) et unités de la scène (mètres, millimètres) respectés.
- Vue enregistrée dans le fichier : perspective ou isométrique cadrée sur tout le modèle, ou vue d'openskp.
- Avertissements en clair pour les cas limites : objets très éloignés de l'origine, faces refusées par le format,
  types d'objets non gérés.

### Corrections apportées pendant les essais

- Textures exportées en noir ou perdues pour certaines images (générées, modifiées, empaquetées).
- Vue par défaut des fichiers exportés : un grand modèle s'ouvrait coupé dans SketchUp pour le web.
- Export de 100 000 objets : plus de 38 minutes au départ, 10,7 secondes maintenant.
- Import de 100 000 copies d'un composant : 129 secondes au départ, 14 secondes maintenant. Import de 20 000 groupes
  uniques : de 48 à 30 secondes. Blender garde ses listes triées par nom et place chaque nouvel élément en
  remontant depuis la fin : l'import crée désormais les maillages et les objets dans l'ordre alphabétique de leurs
  noms.
- La bibliothèque openskp lisait chaque fichier deux fois : une seule lecture suffit maintenant (environ 35 % de
  temps et 25 % de mémoire en moins sur les gros fichiers).
- Chaînes trop longues (noms de 255 caractères, textes de propriétés IFC) : elles sont raccourcies au lieu de
  faire échouer tout l'export.
