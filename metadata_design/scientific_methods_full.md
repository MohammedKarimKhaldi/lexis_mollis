# Méthodes scientifiques — corpus OCR des traités

Version: `0.1-draft`  
Statut: brouillon méthodologique avant fin du traitement OCR complet.

Ce document est rédigé comme base de section “Méthodes” pour un article
scientifique, un data paper ou un appendice de reproductibilité. Il documente
l’ensemble de la chaîne : corpus, inventaire, OCR, sélection des résultats,
nettoyage, audit, métadonnées, contrôle qualité et limites.

## 1. Objectif de la chaîne de traitement

L’objectif est de produire, à partir d’un corpus de documents PDF diplomatiques,
une transcription textuelle fidèle, auditable et exploitable pour une base de
connaissances. La priorité méthodologique est la fidélité documentaire plutôt
que la correction stylistique. Aucune étape générative ne reformule ni ne
“corrige” le contenu reconnu.

Deux couches textuelles sont distinguées:

1. une couche brute, destinée à l’audit et à la vérification documentaire;
2. une couche nettoyée, destinée à la recherche plein texte et à l’indexation
   sémantique.

Les pages incertaines ne sont pas exclues. Elles restent exportées avec des
drapeaux de révision afin d’éviter un biais de corpus par suppression silencieuse
des pages difficiles.

## 2. Constitution du corpus

Le corpus source est constitué de PDF conservés localement dans `traites/`.
Chaque fichier correspond à un alias documentaire, c’est-à-dire un nom de fichier
ou une entrée documentaire issue des métadonnées sources. Plusieurs alias peuvent
référer au même PDF physique si leur SHA-256 est identique.

Les métadonnées initiales sont stockées dans `metadata/parsed_metadata.json`.
Elles contiennent notamment:

- `filename`: nom de fichier source;
- `url`: URL documentaire source lorsqu’elle existe;
- `treaty_id`: identifiant du traité;
- `treaty_number`: numéro ou sous-référence;
- `title`: titre documentaire;
- `doc_type`: type documentaire normalisé;
- `year`: année extraite;
- `file_exists`: présence locale;
- `file_size`: taille du fichier.

Au moment de ce brouillon, les métadonnées couvrent 4 241 entrées documentaires,
avec des années allant de 1516 à 2025. Les effectifs définitifs du corpus OCR
doivent être figés après la fin du traitement complet dans `outputs_v2/manifest.json`.

## 3. Inventaire et identification des documents

L’inventaire est réalisé avant OCR. Pour chaque PDF, le pipeline calcule:

- le SHA-256 des octets du fichier;
- le nombre de pages PDF;
- le chemin absolu local;
- le nom canonique associé au SHA-256;
- les métadonnées documentaires associées au nom de fichier.

Le SHA-256 constitue l’identifiant physique stable du PDF. Le `document_id`
constitue l’identifiant documentaire lisible, dérivé du nom de fichier. Cette
distinction permet de mutualiser le traitement des doublons exacts tout en
conservant les différents alias documentaires.

## 4. Extraction native et OCR raster

Chaque page est traitée indépendamment. Le pipeline commence par extraire la
couche texte native du PDF avec PyMuPDF. Cette couche native est utilisée
directement uniquement lorsqu’elle est crédible: texte imprimable, faible bruit,
absence de caractères de remplacement, score suffisant et couverture image non
dominante.

Si la page n’est pas considérée comme purement native, elle est rendue en image
à 300 DPI. Le pipeline calcule alors un ratio d’encre approximatif (`ink_ratio`)
sur une version réduite de l’image afin d’identifier les pages non vides et les
extractions anormalement pauvres.

Les moteurs OCR utilisés sont:

- Apple Vision, moteur local macOS, comme moteur principal pour les pages
  rasterisées;
- Tesseract comme moteur secondaire, avec modèles par script et configuration
  spécifique pour le français ancien, le latin et les imprimés historiques;
- PyMuPDF comme extraction native lorsque la couche texte du PDF est exploitable.

Les sorties OCR candidates conservent leur texte, blocs, coordonnées normalisées,
langues, scripts, métriques et scores.

## 5. Prétraitement visuel conservateur

La méthode évite la binarisation agressive. Une variante visuelle améliorée peut
être générée lorsque le résultat initial est insuffisant. Cette variante applique:

- conversion en niveaux de gris;
- autocontraste léger;
- augmentation de contraste limitée;
- estimation conservatrice d’un angle de redressement;
- rotation uniquement si l’angle détecté est faible et plausible.

L’orientation globale peut être corrigée si Tesseract OSD détecte une rotation
de 90, 180 ou 270 degrés avec une confiance minimale.

## 6. Sélection du meilleur candidat OCR

La sélection n’est jamais fondée uniquement sur le nombre de caractères. Chaque
candidat reçoit un score composite qui tient compte:

- de la confiance moteur;
- du ratio de caractères imprimables;
- du ratio alphanumérique;
- de la proportion de mots isolés;
- du bruit typographique;
- d’un minimum d’évidence textuelle;
- des caractères de remplacement ou de zone privée Unicode.

Lorsque Apple Vision et Tesseract produisent tous deux du texte comparable, un
score d’accord inter-moteurs est calculé après normalisation. Un accord élevé
accorde un faible bonus aux deux candidats; un désaccord significatif déclenche
un drapeau de révision si les longueurs sont comparables ou si le score global
est faible.

La couche native conserve une priorité lorsqu’elle est crédible, y compris dans
certains PDF contenant aussi une image de page.

## 7. Détection linguistique et scripturaire

Les scripts sont détectés par plages Unicode. Les scripts reconnus incluent
notamment latin, arabe, cyrillique, grec, hébreu, han, japonais, hangul,
devanagari, thaï et lao. Les langues sont estimées avec un détecteur
probabiliste sur un échantillon textuel normalisé.

Ces étiquettes sont descriptives et non définitives. Elles servent à l’audit, à
la recherche, à la sélection des modèles Tesseract et à la priorisation de la
révision.

## 8. Nettoyage déterministe pour la couche KB

La couche nettoyée n’est pas une correction éditoriale. Elle applique uniquement
des transformations déterministes:

- normalisation Unicode NFC;
- normalisation des espaces;
- suppression de caractères de contrôle ou de césure invisible;
- fusion conservatrice de lignes en paragraphes;
- suppression de lignes marginales récurrentes lorsque des en-têtes ou pieds de
  page se répètent géométriquement en début ou fin de page.

La couche brute reste disponible. Les lignes supprimées de la couche nettoyée
sont conservées dans l’audit.

## 9. Qualité, seuils et file de révision

Chaque page reçoit un `quality_score` entre 0 et 1. Les seuils de décision sont:

| Score | Statut | Interprétation |
|---:|---|---|
| `>= 0.85` | accepté | utilisable sans révision prioritaire |
| `0.65–0.85` | révision normale | inclus mais à contrôler |
| `< 0.65` | révision prioritaire | inclus avec révision urgente |

Les drapeaux de révision actuellement définis sont:

- `low_confidence`;
- `engine_disagreement`;
- `no_text_on_nonblank_page`;
- `sparse_extraction`;
- `high_noise`;
- `mixed_scripts`;
- `possible_handwriting_or_historical_print`.

La file `review_queue.csv` agrège ces pages avec leur priorité, score, méthode,
langues, scripts, raisons et image de révision lorsque disponible.

## 10. Exports et traçabilité

Les livrables principaux sont:

- `raw/*.md`: transcription brute page par page;
- `clean/*.md`: texte normalisé pour recherche;
- `kb/pages.jsonl`: un enregistrement par page pour ingestion KB;
- `audit/pages.jsonl`: audit détaillé avec candidats OCR, blocs, coordonnées et
  transformations;
- `review_queue.csv`: file de révision;
- `manifest.json`: compte des documents, pages et erreurs;
- `comparison_report.*`: comparaison avec les anciennes sorties lorsque
  disponible.

Pendant le traitement en cours, des snapshots légers peuvent être exportés vers
`outputs_live/` avec `--light`. Ces snapshots excluent l’audit détaillé lourd
mais conservent les sorties utiles pour revue et versioning.

## 11. Versioning et audit externe

Les snapshots publiables sont placés dans `kb_repository/`, un dépôt Git séparé
du dossier de traitement. Chaque snapshot peut être committé avec le nombre de
documents et de pages exportés. Cette séparation permet:

- de conserver l’historique des changements;
- d’inspecter les diffs Markdown et JSONL;
- de publier ultérieurement vers Forgejo;
- de préserver le pipeline OCR actif.

Forgejo est prévu comme interface web locale pour visualiser les commits, les
diffs et les fichiers Markdown, mais le dépôt Git local reste suffisant pour
l’audit de base.

## 12. Reproductibilité

Une reproduction minimale exige:

1. les PDF sources ou leurs URLs;
2. `metadata/parsed_metadata.json`;
3. le code `pdfkb` et sa version;
4. l’environnement Python et les moteurs OCR locaux;
5. la commande d’exécution;
6. `metadata/pipeline.sqlite3` ou les exports JSONL/Markdown;
7. le manifeste final;
8. le benchmark de validation.

Commande canonique:

```bash
python -m pdfkb run \
  --source traites \
  --metadata metadata/parsed_metadata.json \
  --output outputs_v2 \
  --state metadata/pipeline.sqlite3 \
  --workers 4 \
  --dpi 300 \
  --resume
```

## 13. Validation

La validation combine:

- tests unitaires de scoring, nettoyage et état SQLite;
- banc stratifié incluant couche native, imprimé moderne, cyrillique, chinois,
  page presque vide et manuscrit historique;
- contrôle des comptes finaux;
- inspection de la file de révision;
- comparaison avant/après avec les anciennes sorties `extracted/`.

Les objectifs de référence doivent être figés après OCR complet, notamment:

- nombre final de documents;
- nombre final de pages logiques;
- absence de pages manquantes;
- taux de pages à réviser;
- distribution des méthodes OCR;
- distribution des langues et scripts;
- exemples visuels de pages acceptées, incertaines et prioritaires.

## 14. Limites méthodologiques

Le score OCR n’est pas une vérité documentaire. Les manuscrits, pages dégradées,
pages multilingues et imprimés anciens peuvent rester incertains malgré une
transcription partielle. Les langues détectées sur textes courts peuvent être
instables. Les droits de publication ne sont pas déduits automatiquement des
métadonnées OCR.

La méthode privilégie donc l’inclusion signalée plutôt que l’exclusion: les pages
faibles restent dans la base avec leurs drapeaux de révision.

