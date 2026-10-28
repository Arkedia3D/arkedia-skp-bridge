# Journal des modifications

## 0.2.3, 28 octobre 2026 : pièces sans moirage, surface dans leur nom

Les faces des pièces tombaient exactement sur les sols, les plafonds et les murs. SketchUp ne sait pas laquelle
dessiner devant et les fait scintiller en rayures (moirage) dès qu'on affiche les pièces.

### Export

- Les faces de chaque pièce sont rentrées de 5 mm (option « Retrait des pièces (mm) », 0 pour garder les volumes
  exacts). Chaque face recule le long de sa normale : murs obliques, angles rentrants et sols en pente gardent leur
  forme. Une pièce qui contourne une trémie collée à un mur, avec un étranglement plus mince que 1 cm, est
  reconstruite depuis son emprise décalée. Une pièce qui n'est pas un volume fermé part sans retrait, avec un
  avertissement.
- Nouvelle option « Surface dans le nom des pièces », active par défaut : « Pièce 01 Chambre, 28,38 m² ». La
  surface est celle de l'IFC (NetFloorArea), sinon celle du sol du volume, mesurée avant le retrait. Une face mesurée
  à la main dans SketchUp donne un peu moins, à cause des 5 mm ; le volume affiché perd moins de 1 %.

### Vérifications

- Dans SketchUp 2027, sur la villa de trois niveaux, les rayures de la terrasse du 2e étage disparaissent dès 1 mm
  de retrait. Les 5 mm retenus gardent de la marge pour un bâtiment plus grand ou une vue plus lointaine.
- Appartement et villa : 5 pièces sur 5 et 27 sur 27 rentrées de 5,0 mm sur chaque axe, dont une reconstruite depuis
  son emprise. Surface du bâti inchangée, maillages de Blender intacts. Dans SketchUp 2027, toutes les pièces restent
  des solides, nommées avec leur surface, sur leurs étiquettes masquées à l'ouverture.
- Nouveau cas `pieces` dans la série d'essais, sans Bonsai : trois pièces rectangulaires, une en L et une à
  étranglement, collées au sol, au plafond et aux murs. Série complète (12 cas) : surface et boîte englobante du bâti
  identiques à l'original après l'aller-retour, volume à 1e-5 près, et les cinq pièces rentrées de 5,0 mm.

## 0.2.2, 27 octobre 2026 : pièces IFC et étiquettes de niveau

Cette version vient de l'export de deux relevés modélisés dans Bonsai, un appartement d'un niveau et une villa sur
trois niveaux, ouverts ensuite dans SketchUp 2027.

### Export

- Nouvelle option « Pièces (IfcSpace) », inactive par défaut. Bonsai masque les volumes de pièces et l'export ne
  prend que les objets visibles : jusqu'ici, les pièces restaient dans Blender. Avec l'option, elles partent même
  masquées, chacune dans un groupe nommé d'après son numéro et son nom IFC (« Pièce 01 Chambre »), avec ses jeux de
  propriétés et une matière translucide (opacité de 20 % au plus). Si cette matière habille aussi le bâtiment, la
  pièce en reçoit une copie translucide suffixée « (volume) » et le bâtiment garde l'original. Avec « Sélection
  uniquement », l'export prend les pièces sélectionnées et celles des niveaux touchés par la sélection.
- Les pièces sont rangées sur une étiquette par niveau, « Pièces - Rez-de-chaussée » par exemple. L'option
  « Étiquette des pièces masquée à l'ouverture », active par défaut, décoche ces étiquettes dans le fichier :
  SketchUp ouvre le bâtiment seul, et un clic sur l'étiquette affiche les pièces.
- Calques par niveau IFC : l'étiquette porte le nom du niveau, « Rez-de-chaussée » au lieu de « IfcBuildingStorey -
  Rez-de-chaussée ». Le niveau est lu dans la structure IFC (élément contenu dans le niveau, ou partie d'un ensemble
  qui l'est), puis dans les collections de Blender si l'IFC n'est pas chargé. Sur les deux modèles d'essai, les
  éléments se répartissent comme en 0.2.1, et les pièces, agrégées à leur niveau, rejoignent l'étiquette de ce niveau.
- Dictionnaire d'attributs « ARKEDIA » : deux clés de plus quand l'IFC les renseigne, `ifc_storey` (le niveau) et
  `ifc_long_name` (le nom long, « Chambre » pour la pièce 01).

### Vérifications

- Appartement : 48 éléments sur l'étiquette « Rez-de-chaussée », 5 pièces sur « Pièces - Rez-de-chaussée ». Villa :
  270 éléments sur trois étiquettes de niveau (102, 101 et 67, la même répartition qu'en 0.2.1) et 27 pièces sur
  trois étiquettes de pièces. Relus dans Blender, les fichiers gardent la surface du modèle Bonsai à 0,002 % près et
  ses dimensions.
- Dans SketchUp 2027, les étiquettes de pièces sont décochées à l'ouverture, chaque pièce est un solide, et tous les
  objets portent leur dictionnaire « ARKEDIA » (53 sur 53, 297 sur 297).
- Série de non-régression sur les modèles d'essai sans IFC (11 cas, dont un terrain, des textures et 2 000 copies
  d'un composant) : après l'aller-retour, surface et boîte englobante identiques à l'original, volume à 1e-5 près.

## 0.2.1, 27 octobre 2026 : essais dans SketchUp 2027 et corrections

La 0.2.0 n'avait été ouverte que dans SketchUp pour le web. Cette version suit une série d'essais dans SketchUp 2027
(version de bureau) : ouverture des fichiers exportés, enregistrement de copies en versions 2013, 2017, 2020, 2021
et 2027, puis relecture de ces copies dans Blender.

### Correction à l'import

- Les fichiers enregistrés par SketchUp 2021 ou plus récent arrivaient dans Blender avec des faces retournées. Sur la
  maison d'essai réenregistrée par SketchUp 2027, la 0.2.0 retournait 290 faces sur 1 284 (22 %), 14 objets sur 20
  changeaient de volume et la somme des volumes passait de 70 m³ à -238 m³. Ces fichiers contiennent une matière
  « Layer_<étiquette> » par étiquette : l'import la prenait pour une matière de l'utilisateur et écartait alors au
  hasard le recto ou le verso des faces doublées. Elle est maintenant ignorée. Les copies réenregistrées par
  SketchUp 2027 donnent la même surface, le même nombre de triangles et la même boîte englobante que l'original, et
  un volume identique (à 4e-5 près sur le terrain de 500 000 triangles), du plus petit modèle (85 Ko) au plus gros
  (89 Mo). Les trois petits modèles ont aussi été réenregistrés en versions 2013, 2017, 2020 et 2021, avec le même
  résultat.

### Export

- Les surfaces texturées sont fusionnées quand leurs coordonnées de texture suivent une même projection plane (un
  sol carrelé, un mur déroulé d'un seul tenant) : une face au lieu d'un triangle par maille, texture inchangée. La
  diagonale de la terrasse de la maison d'essai disparaît. Une surface dont le dépliage est coupé en îlots ou
  retourné en miroir garde ses triangles.
- Nouvelle option « Adoucir les maillages denses », active par défaut, avec son angle (35 degrés). Les objets de
  2 000 faces et plus (terrain, maillage issu d'un scan) reçoivent des arêtes douces entre faces voisines, comme
  l'outil Adoucir de SketchUp. Sans cela, SketchUp trace chaque arête et un grand maillage s'affiche presque noir.
  L'option ne ralentit pas l'export : en comparant la 0.2.0 et la 0.2.1 côte à côte sur trois cas (terrain de 180 000
  triangles, sphère de 327 680, terrain de 500 000), les temps sont les mêmes à 3 % près.
- Nouvelle option « Unités dans SketchUp » : mètres, centimètres ou millimètres (par défaut, ceux de la scène
  Blender), ou pouces. Le gabarit d'openskp ouvrait tout en pouces et en pieds : 2,80 m s'affichait « 9' 2 1/4" ».
  Surfaces et volumes sortent en m² et m³.
- Vue enregistrée : le cadrage s'appuie sur les huit coins de la boîte englobante et garde 8 % de marge (15 %
  avant). Le modèle remplit mieux la fenêtre à l'ouverture.
- Si le gabarit d'openskp n'a pas la forme attendue, un avertissement dit que les unités ou la vue n'ont pas pu être
  écrites, au lieu de les ignorer en silence.

### Vérifications dans SketchUp 2027

- Six modèles exportés ont été ouverts, parcourus et réenregistrés : la maison d'essai, deux projets Bonsai (calques
  par niveau IFC et par classe IFC), un terrain de 500 000 triangles, 100 000 chaises et 20 000 groupes. Aucune
  erreur. L'ouverture prend de 11 secondes (100 000 chaises) à 75 secondes au plus (terrain de 500 000 triangles),
  démarrage de SketchUp compris. Le cadrage enregistré place les huit coins de la boîte englobante dans la fenêtre.
- SketchUp 2027 affiche à l'ouverture un message d'information, « Version de ce fichier : 17.0.1 » (les fichiers
  écrits sont au format SketchUp 2017), puis marque le modèle comme modifié. À l'enregistrement, il le passe au
  format récent.
- Série de charge relancée sur le code final : 21 cas relus dans Blender, surface égale à l'originale à 1e-7 près.
  Le 22e, le terrain de 500 000 triangles, a été exporté sans erreur, mais sa relecture a été refusée ce jour-là par
  le contrôle de mémoire (4,2 Go libres sur la machine d'essai).

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
