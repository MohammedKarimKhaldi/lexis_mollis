# Protocole OCR détaillé

Version: `0.1-draft`

Ce document décrit la méthode OCR effective du pipeline `pdfkb` de manière
opérationnelle et reproductible.

## 1. Unité de traitement

L’unité de traitement est la page PDF physique, identifiée par:

- `source_sha256`: SHA-256 du PDF;
- `page_number`: numéro de page à partir de 1;
- `pipeline_version`: version du pipeline.

Le traitement est indépendant page par page. L’état est stocké dans SQLite et
une page réussie ne peut pas être écrasée par un échec ultérieur.

## 2. Extraction native

Pour chaque page, PyMuPDF extrait:

- texte natif trié;
- blocs natifs;
- dimensions de page;
- rotation PDF;
- couverture estimée des images.

La couche native est considérée crédible si:

- au moins 3 caractères sont présents;
- aucun caractère de remplacement `�`;
- aucun caractère de zone privée Unicode;
- ratio imprimable `>= 0.98`;
- ratio de bruit `<= 0.01`;
- score candidat `>= 0.82`.

Si la couche native est crédible et que la couverture image est inférieure à
0,50, la page est considérée comme purement native et le raster OCR est évité.

## 3. Rendu image

Les pages nécessitant OCR sont rendues à 300 DPI en RGB. Le pipeline calcule:

- `ink_ratio`: proportion de pixels sombres après réduction;
- orientation/script via Tesseract OSD;
- rotation conservatrice si OSD détecte 90, 180 ou 270 degrés avec confiance
  suffisante.

## 4. Candidats Apple Vision

Apple Vision produit un candidat OCR local. Le candidat contient:

- texte reconnu;
- blocs et coordonnées normalisées;
- confiance;
- variante (`original` ou `enhanced`);
- langues et scripts détectés après scoring.

Apple Vision est généralement le moteur principal pour les scans.

## 5. Candidats Tesseract

Tesseract est utilisé comme moteur secondaire. Le choix du modèle suit:

1. script détecté dans le texte Apple Vision si OSD est faible ou contradictoire;
2. sinon script OSD;
3. sinon latin par défaut.

Mapping principal:

| Script | Modèle Tesseract |
|---|---|
| Latin | `script/Latin` |
| Cyrillic | `script/Cyrillic` |
| Arabic | `script/Arabic` |
| Han | `script/HanS` |
| Japanese | `script/Japanese` |
| Hangul | `script/Hangul` |
| Greek | `script/Greek` |
| Hebrew | `script/Hebrew` |
| Devanagari | `script/Devanagari` |
| Thai | `script/Thai` |
| Fraktur | `script/Fraktur` |

Pour les pages latines antérieures à 1950, le pipeline ajoute
`fra+frm+lat+eng` afin de mieux couvrir français moderne, français ancien,
latin et anglais.

Tesseract est lancé avec:

- OEM 3;
- PSM 3 par défaut;
- PSM 6 en repli lorsque PSM 3 ne produit pas de texte;
- préservation des espaces inter-mots.

## 6. Variante améliorée

Une variante améliorée est testée si le meilleur score initial est inférieur à
0,88 ou si aucun texte Tesseract n’a été produit.

La variante applique:

- autocontraste léger;
- contraste 1,08;
- estimation d’un angle par composantes sombres;
- rotation seulement si l’angle est entre 0,35 et 3 degrés en valeur absolue.

L’objectif est d’améliorer les scans inclinés sans détruire la forme documentaire.

## 7. Score candidat

Chaque candidat reçoit un score composite:

```text
score =
  0.36 * confidence
+ 0.20 * printable_ratio
+ 0.14 * alnum_score
+ 0.14 * token_score
+ 0.10 * noise_score
+ 0.06 * evidence
- penalty(replacement_count, private_use_count)
```

Définitions:

- `printable_ratio`: proportion de caractères imprimables;
- `alnum_score`: proximité du ratio alphanumérique à une valeur documentaire
  attendue;
- `token_score`: pénalité liée aux mots isolés;
- `noise_score`: pénalité liée aux caractères de bruit;
- `evidence`: saturation logarithmique de la longueur textuelle;
- `penalty`: pénalité pour caractères de remplacement et caractères Unicode de
  zone privée.

Le score est borné entre 0 et 1.

## 8. Accord inter-moteurs

Lorsque Apple Vision et Tesseract produisent des textes suffisants, un accord
est calculé:

1. normalisation Unicode NFKC;
2. passage en casse repliée;
3. conservation des seuls caractères alphanumériques;
4. comparaison par `SequenceMatcher`.

Pour les textes très longs, le début et la fin sont échantillonnés afin de
limiter le coût de comparaison tout en couvrant l’étendue de la page.

Si l’accord est supérieur à 0,55, un faible bonus peut être ajouté aux scores des
deux moteurs.

## 9. Sélection finale

La sélection suit ces règles:

1. ignorer les candidats vides si au moins un candidat non vide existe;
2. recalculer le score de chaque candidat;
3. prioriser la couche native si elle est crédible et si sa couverture image est
   compatible;
4. comparer Apple Vision et Tesseract avec bonus d’accord si possible;
5. sélectionner le candidat au score le plus élevé.

Le nombre de caractères seul ne décide jamais du choix final.

## 10. Raisons de révision

Une page est ajoutée à la file de révision si au moins une condition est vraie:

| Raison | Condition |
|---|---|
| `low_confidence` | score `< 0.85` |
| `engine_disagreement` | accord Apple/Tesseract faible dans une comparaison pertinente |
| `no_text_on_nonblank_page` | page visuellement non vide mais texte quasi absent |
| `sparse_extraction` | page encrée mais extraction courte et incertaine |
| `high_noise` | ratio de bruit supérieur au seuil |
| `mixed_scripts` | au moins trois scripts détectés |
| `possible_handwriting_or_historical_print` | document ancien avec désaccord moteur |

Priorité:

- `high` si score `< 0.65` ou page non vide sans texte;
- `normal` si autre raison de révision;
- `none` sinon.

## 11. Données conservées

Pour l’audit complet, chaque page conserve:

- candidat sélectionné;
- tous les candidats OCR;
- texte brut;
- texte nettoyé;
- blocs et coordonnées;
- langues/scripts;
- score qualité;
- accord inter-moteurs;
- transformations de nettoyage;
- lignes supprimées;
- raisons de révision.

## 12. Exclusions méthodologiques

Le pipeline exclut explicitement:

- correction générative;
- reformulation LLM;
- suppression des pages faibles;
- sélection par longueur seule;
- binarisation agressive systématique.

