# Journal des modifications

## 0.3.3, 30 octobre 2026 : noms des pièces dessinés dans la pièce

Les noms des pièces de la 0.3.0 étaient des textes SketchUp. Un tel texte se dessine à l'écran : sa taille ne suit
pas le zoom, il part vers la droite de son point d'ancrage et, vu de dessus, il déborde sur les murs des petites
pièces. Sur une planche LayOut au 1/50, il garde aussi sa taille d'écran.

### Export

- Nouvelle option « Noms dessinés dans la pièce », active par défaut. Le nom et la surface de chaque pièce sont
  dessinés en lettres planes (DM Sans Medium), dans un groupe par pièce (« Nom de pièce - Chambre » pour une chambre)
  rangé sur l'étiquette des pièces de son niveau : capitales de 15 cm, soit 3 mm sur un plan au 1/50. Faces
  horizontales tournées vers le haut, même matière bleu nuit des deux côtés, arêtes masquées. Le groupe se voit dans
  la scène « Plan » de son niveau, sous la coupe, comme l'ancien texte.
- Le bloc se pose au cœur de la pièce s'il y tient, sinon au point le plus proche où il tient. Il évite ce qui se voit
  dans la pièce vue de dessus : sanitaires et bacs de douche, mobilier, parois vitrées, cloisons, portes, escaliers,
  poteaux. Faute de place, le nom passe sur deux lignes, le bloc tourne d'un quart de tour (couloirs) ou rapetisse
  jusqu'à 70 % ; s'il ne trouve toujours pas de place libre, il passe par-dessus les équipements, réduit au besoin
  jusqu'à 60 %. Un nom qui déborde encore de sa pièce est signalé.
- Le cœur de la pièce est son centre de gravité quand il est presque aussi loin des murs que le pôle
  d'inaccessibilité : dans un couloir, le nom se pose au milieu et non à un bout. Le texte SketchUp, toujours
  disponible en décochant l'option, en profite aussi.
- Les contours des lettres (glyphes_dmsans.json, 44 Ko) viennent de la police DM Sans, sous licence SIL Open Font
  License 1.1, jointe à l'extension (OFL_DMSans.txt). Un nom dessiné ajoute de 30 à 45 Ko au fichier.

### Import

- Un fichier dont le nombre de définitions est égal au numéro d'objet d'une étiquette ne s'ouvrait pas (« implausible
  definition count ») : openskp lisait l'étiquette active comme une étiquette parente, puis le nombre de définitions
  deux octets trop loin. Le cas d'essai `niveaux` y est tombé avec ses 16 groupes. Le correctif ne joue que le temps de
  l'import.

### Vérifications

- Cas d'essai `niveaux` : un groupe de lettres par pièce, sur l'étiquette des pièces de son niveau, à 1,20 et
  4,40 m, centré dans la pièce, faces tournées vers le haut, aucune arête visible, aucun texte SketchUp. Nouveau cas
  `niveaux_texte` pour l'ancien texte. Les 15 cas passent.
- Un appartement et une villa de trois niveaux réexportés depuis leur IFC, rouverts dans SketchUp 2027 : 7 et 27 noms
  dessinés, chacun dans le sol de sa pièce, sous la coupe, visible dans la seule scène « Plan » de son niveau, aucune
  arête visible, plus aucun texte SketchUp. Dans l'appartement, le hall se lit tourné d'un quart de tour, la salle
  d'eau sur deux lignes et le placard en plus petit ; dans la villa, les noms des salles d'eau passent à côté des
  parois vitrées et des bacs de douche qu'ils coupaient en texte. Bâti, pièces, surfaces et dimensions identiques à
  la 0.3.2. Fichiers de 467 Ko et 2,4 Mo, contre 237 Ko et 1,2 Mo avec les textes.
- Planche LayOut au 1/50 tirée des scènes « Plan » : les noms gardent leur taille et leur place sur le papier.

## 0.3.2, 30 octobre 2026 : ombres du lieu, plans coupés, scènes des anciennes versions

Trois manques relevés en ouvrant nos exports dans SketchUp 2027. Le soleil était celui de Boulder, au Colorado, quel
que soit le lieu du bien. Les scènes « Plan » regardaient le niveau d'en haut sans le couper. Et un fichier rendu par
un client dans une ancienne version de SketchUp revenait sans ses scènes.

### Export

- Nouvelle option « Position et nord de l'IFC », active par défaut. La latitude et la longitude du site (IfcSite),
  le nord (TrueNorth du contexte du modèle) et la ville de l'adresse sont écrits dans le fichier, pour le modèle et
  pour chaque scène : les ombres de SketchUp sont celles du lieu. La ville tient sur 12 caractères et le pays sur 3
  (« Abidjan (CI) », « CIV »), la longueur des textes du gabarit d'openskp, pour que rien d'autre ne bouge dans le
  fichier. Le fuseau horaire est celui du pays pour dix-huit pays (quatorze d'Afrique de l'Ouest et centrale, le
  Maroc, la France, la Belgique et la Suisse) ; ailleurs, il est déduit de la longitude. Sans position dans l'IFC,
  le fichier garde le soleil du gabarit.
- Nouvelle option « Plan coupé dans les scènes « Plan » », active par défaut, avec sa hauteur (1,30 m). Chaque niveau
  reçoit un plan de section horizontal à cette hauteur au-dessus de son sol fini, actif dans sa seule scène « Plan » :
  murs, baies et équipements y sont tranchés comme sur un plan d'architecte, et les vues 3D restent entières. Le sol
  fini est la position du niveau dans l'IFC (IfcBuildingStorey) ; sans IFC, le bas médian des objets du niveau.
- Les plans de section sont rangés sur une étiquette « Plans de coupe » masquée dans toutes les scènes : leur cadre
  ne se dessine dans aucune vue, la coupe reste active. Un plan simplement masqué ne convenait pas, SketchUp le
  réaffiche au clic sur la scène.
- Les traits de coupe passent du rouge du gabarit au noir, dans les options de rendu comme dans les styles que les
  scènes appliquent.
- Les noms des pièces sont posés 10 cm sous la coupe : SketchUp cache les textes situés au-dessus d'un plan de
  section actif.
- Les statistiques du dernier export restent lisibles par un script (`_LAST_EXPORT_STATS`), pour les contrôles.

### Import

- Les scènes d'un fichier enregistré dans un format de 2013 à 2020 par SketchUp 2021 ou plus récent (« Enregistrer
  sous » une ancienne version) sont lues. openskp s'y arrêtait sur de petits écarts de format : identifiants absents,
  un octet de moins devant les options de rendu et les ombres jusqu'au format 2016, drapeaux de capture récents,
  vignette en fin de scène. Le correctif ne s'applique que le temps de l'import, comme ceux de l'export.

### Vérifications

- Cas d'essai `niveaux` complété : deux plans de section à 1,30 et 4,50 m, chacun actif dans la seule scène « Plan »
  de son niveau, étiquette « Plans de coupe » masquée dans les cinq scènes, noms des pièces à 1,20 et 4,40 m. Les 14
  cas passent.
- Un appartement et une villa de trois niveaux réexportés depuis leur IFC, rouverts dans SketchUp 2027 et chaque
  scène activée par script : position, fuseau et nord relus dans le modèle et dans chaque scène (286,2° et 281,5°),
  un plan de section par niveau (1,30 m ; 1,30, 4,88 et 8,40 m pour la villa), actif dans la seule scène « Plan » de
  son niveau, aucune coupe à l'ouverture ni dans les vues 3D, 7 et 27 noms de pièces sous la coupe, traits de coupe
  noirs. Surfaces et dimensions identiques à celles de la 0.3.1, aucune arête parasite.
- Un fichier modifié dans SketchUp 2027 puis enregistré dans chaque version proposée : les fichiers 2013 à 2020
  rendent désormais leurs quatre scènes, comme ceux de 2021 et plus. Les versions 4 à 8 (SketchUp 4 à 8) se lisent
  sans leurs scènes et la version 3 reste refusée, comme avant.

## 0.3.1, 30 octobre 2026 : murs sans traits parasites

Ouvert dans SketchUp, le modèle d'un appartement montrait 33 traits en trop sur quatre murs, celui d'un autre 7 sur
un mur. Deux faces voisines presque dans le même plan, à moins d'un degré l'une de l'autre, ne peuvent pas devenir
une seule face plane : elles restaient séparées par une arête visible. L'adoucissement de la 0.2.1 ne traitait que
les maillages d'au moins 2 000 faces.

### Export

- Nouvelle option « Adoucir les arêtes presque coplanaires », active par défaut : l'arête entre deux faces voisines
  de même matériau dont les normales diffèrent de moins de 1 degré est écrite douce et lisse, quel que soit le nombre
  de faces de l'objet. Les arêtes réelles restent visibles : angle plus franc, changement de matériau, bord libre.
- Le voisinage se lit sur la position des sommets, comme dans SketchUp : des sommets en double dans un maillage IFC
  ne laissent plus passer une arête.
- Deux faces côte à côte dans le même plan mais d'orientation contraire sont traitées de même. Deux faces repliées
  l'une sur l'autre gardent leur arête, qui signale un recouvrement réel.
- Un polygone gauchi, découpé en triangles à l'écriture, n'affiche plus ses diagonales.
- openskp donne à chaque arête les réglages de la première face qui la crée. Le temps de l'export, l'extension lui
  indique une à une les arêtes à adoucir, comme elle le fait déjà pour la tolérance de planéité ; tout est remis en
  place à la fin.

### Vérifications

- Nouveau cas d'essai `presqueplan` : quatre murs dont la face avant est coupée en deux (pli de 0,3°, pli de 5°,
  deux matériaux dans un même plan, pli de 0,3° avec une moitié à l'envers). Relues par openskp, les deux arêtes à
  0,3° sont douces ; celle du pli de 5°, celle du changement de matériau et les angles droits restent visibles. Les
  14 cas d'essai passent.
- Trois modèles réexportés depuis leur IFC, rouverts dans SketchUp 2027, arêtes comptées par script : premier
  appartement, de 33 traits en trop à aucun ; second appartement, de 7 à aucun ; villa de trois niveaux, aucun avant
  comme après. Surfaces, dimensions, scènes et noms des pièces sont identiques à ceux de la 0.3.0. Sur le premier
  appartement, une ligne reste au tableau de la porte d'entrée : dans l'IFC, la face de l'ouverture y recouvre celle
  du mur sur 2 mm, et ce recouvrement réel garde son arête.

## 0.3.0, 29 octobre 2026 : scènes par niveau, noms des pièces, fin des taches bleues

Ouverte dans SketchUp, la villa de trois niveaux montrait des taches bleu-violet derrière les vitrages et sur les
pièces translucides. Le verso des faces n'avait pas de matière : SketchUp le peint alors de la couleur « face
arrière » de son style, que l'on voit au travers de tout ce qui est translucide.

### Export

- Nouvelle option « Matière au verso des faces », active par défaut : le verso de chaque face reçoit la matière de
  son recto (sauf matière texturée). Les vitrages restent clairs et laissent voir l'intérieur.
- Nouvelle option « Scènes par niveau », active par défaut avec « Niveau IFC ». Le fichier s'ouvre avec des onglets
  de scènes : « Vue d'ensemble », puis pour chaque niveau une vue 3D en maison de poupée, niveaux supérieurs,
  plafonds et toiture masqués (« 3D - 1er étage »), et une vue de dessus en projection parallèle, le niveau seul avec
  ses pièces et leurs noms (« Plan - 1er étage »). Plafonds (IfcCovering CEILING) et toitures (IfcRoof, dalles ROOF)
  passent sur leurs propres étiquettes, « Plafonds - 1er étage » ou « Toiture - 2e étage » par exemple, pour que les
  scènes puissent les masquer.
- Nouvelle option « Noms des pièces en texte », active par défaut avec les pièces : un texte SketchUp dans chaque
  pièce, son nom puis sa surface (« Chambre », « 28,38 m² »), posé au point le plus éloigné des murs, même dans une
  pièce en L, au-dessus de ce que porte le niveau pour ne pas passer sous un mur. Il suit l'étiquette de la pièce :
  on le lit dans les scènes « Plan ».
- Éclairage des scènes : une scène retient les réglages d'ombre, et SketchUp y active « Utiliser le soleil pour
  l'ombrage ». Avec le soleil de 13 h 30 du gabarit, au sud-ouest, un clic sur un onglet passait les façades est et
  sud en gris foncé. Le soleil est maintenant à 10 h (haut, à l'est-sud-est, du côté de la caméra des vues 3D) et le
  curseur « Sombre » à 45 %, la valeur par défaut de SketchUp.
- Sans IFC chargé, un objet rangé dans une collection Bonsai « IfcBuildingStorey/1er étage » prend ce niveau pour
  étiquette, ses pièces comprises (« Pièces - 1er étage »).
- Bibliothèque openskp 1.4.0 (scènes, textes dans un groupe) au lieu de la 1.3.0.

### Vérifications

- La cause des taches, vérifiée dans SketchUp 2027 sur le fichier de la 0.2.3 : avec la couleur des faces arrière
  passée en magenta, chaque vitrage de la vue d'ouverture devient magenta. Avec la 0.3.0, l'image de la vue
  d'ouverture reste identique au pixel près après ce changement : aucun verso visible.
- Villa de trois niveaux et appartement exportés depuis leur IFC, rouverts dans SketchUp 2027, chaque scène activée
  par script : 7 et 3 scènes, étiquettes masquées comme prévu, aucune face visible au verso sans matière, noms des
  pièces visibles dans les seules scènes « Plan » (11, 10 et 6 pour les trois niveaux de la villa, 5 pour
  l'appartement). Après un clic sur une scène, les façades restent claires (gris foncé avant le réglage de l'éclairage).
- Trois écarts trouvés pendant ces essais, corrigés avant la sortie. SketchUp lit la position d'étiquette qu'écrit
  openskp comme le vecteur de la ligne de rappel : les noms partaient loin de leur pièce, ils sont maintenant posés
  sur leur point. Une scène sans les réglages d'ombre rend le fichier illisible (« Format de fichier inattendu ») :
  d'où le réglage de l'heure et du curseur « Sombre ». Un nom posé près du sol passait sous les murs voisins : il est
  posé au-dessus de ce que porte le niveau.
- Avec l'extension installée, par `ifc_vers_skp.py` : bâti identique (villa +0,002 %, appartement 0,000 %, mêmes
  dimensions), pièces à −0,62 % et −0,64 % (retrait de 5 mm), et les scènes relues comme caméras dans Blender.
- Série d'essais, 13 cas dont le nouveau `niveaux` (deux niveaux sans IFC chargé, relus par openskp : scènes,
  étiquettes masquées, textes, verso des faces) : surface et boîte englobante identiques à l'original après
  l'aller-retour, volume à 1e-5 près, chaîne complète fidèle.

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
