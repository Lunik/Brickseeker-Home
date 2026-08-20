# AGENTS.md — BrickSeeker auto-hébergé

Conventions et contexte durement acquis. À lire avant de modifier ce dépôt.

## Ce que c'est

Portage web de l'app iOS SwiftUI [`brickseeker-app`](../brickseeker-app) : FastAPI + SQLite d'un
côté, React + Tailwind + Vite de l'autre, le tout servi par **un seul conteneur**. Mêmes
fonctionnalités, mêmes règles métier, mêmes textes français.

L'app iOS reste la référence. Son [`AGENTS.md`](../brickseeker-app/AGENTS.md) documente des dizaines
de comportements non évidents avec les preuves qui les justifient (réponses d'API vérifiées en
direct, bugs trouvés uniquement sur appareil réel). **Ce sont des exigences, pas des anecdotes** —
avant de « simplifier » quelque chose ici, cherche si la question a déjà été tranchée là-bas.

## Le contrat

[`docs/contract.md`](docs/contract.md) définit les signatures des services et toute la surface REST.
Backend et frontend ont été écrits en parallèle contre lui. Si le code et le contrat divergent,
c'est le contrat qu'il faut corriger — mais **en même temps** que le code des deux côtés de la
frontière, jamais à la place.

## Build

```bash
docker compose up -d --build          # l'ensemble
cd backend && .venv/bin/uvicorn app.main:app --reload    # API seule
cd frontend && npm run dev            # UI seule (proxy /api vers :8000)
```

Le build Vite écrit dans `backend/app/static/` — c'est ce que `main.py` sert avec un fallback SPA.
Ce dossier est ignoré par git : il est généré.

Vérifie toujours que ça compile avant de considérer un changement terminé :
`cd frontend && npx tsc -b --noEmit && npm run build`, et `python -c "from app.main import app"`
côté backend.

## Le noyau des prix est unique, et doit le rester

`backend/app/services/pricing.py` est **pur** : pas de base, pas de réseau, pas de session. Il
contient les quatre chaînes de résolution et rien d'autre ne calcule un prix. C'est ce qui garantit
que la ligne d'une liste, le total des statistiques, l'export CSV et l'évaluateur d'alertes ne
peuvent pas être en désaccord sur ce que vaut un set — la dérive que l'issue #194 de l'app iOS a dû
corriger.

Les quatre chaînes ne sont **pas** interchangeables :

- `resolve_new_price` (Historique) : lego.com → le **moins cher** d'Amazon/Cdiscount → BrickLink neuf.
- `resolve_collection_price` (ligne Collection **et** total Statistiques) : piloté par la condition
  de la liste, avec repli croisé en dernier recours, et le **plus cher** d'Amazon/Cdiscount — la
  valeur de la collection ne doit pas baisser parce qu'une marketplace était moins chère ce jour-là.
- `resolve_wishlist_price` (Liste cadeaux) : Amazon/Cdiscount **avant** lego.com, volontairement
  inversé par rapport à l'Historique.
- `resolve_minifig_price` : BrickLink uniquement — une minifig n'est jamais vendue au détail.

Une disponibilité `retired` écarte le prix lego.com des chaînes de **valeur** : le site continue de
servir un prix résiduel pour un set qu'il ne vend plus. Elle n'écarte jamais la **référence** de
croissance : mesurer l'écart du marché face au prix catalogue est précisément l'intérêt de ce
pourcentage.

## Ce qui est saisi à la main survit aux caches

`clear_cache()` supprime `CachedSet`, `CachedSetList`, `CachedSetPrice`, `SoldListing`,
`CollectionSyncState`, et efface les positions de scan. Il **conserve** `ScanEvent`,
`SetPurchaseRecord`, `PriceAlert`, `PriceHistoryEntry`, `CollectionValueSnapshot`.

La règle : « vider le cache » purge ce qui se re-télécharge, pas ce qui ne se retrouve nulle part.
Un seuil d'alerte, un prix payé, la valeur qu'avait la collection en mars — rien de tout ça n'est
récupérable auprès d'une API. C'est aussi pourquoi ces données sont des tables séparées plutôt que
des colonnes de `CachedSet`, qui est détruit par deux chemins de routine.

## `was_scanned` dit pourquoi la ligne existe

`True` = l'utilisateur a scanné ce set (alimente l'Historique) ; `False` = la ligne ne vient que
d'une synchronisation de collection (alimente la Collection). Un set peut être les deux. Scanner un
set possédé ne l'efface pas, et `sync_collection` ne le repasse jamais à `False` sur une ligne
existante.

Corollaire : supprimer un set de l'Historique ne le supprime pas de la Collection s'il y est encore
— il perd seulement `was_scanned`.

## Ce que le rafraîchissement de fond a le droit de faire

Le périmètre surveillé, c'est **uniquement les sets portant une alerte activée**. Pas la collection,
pas la liste cadeaux. Cette restriction est toute la réponse à l'objection « ça ne passe pas à
l'échelle » ; l'élargir rouvre la décision.

La passe de fond n'interroge **que BrickLink** : les prix lego.com/Amazon/Cdiscount viennent d'un
navigateur headless, et faire tourner Chromium en boucle sur toute une collection est exactement ce
qui fait blacklister une IP. Conséquence à assumer et à dire dans l'UI plutôt que de la laisser
paraître capricieuse : une alerte « occasion » est entièrement servie par la passe de fond, une
alerte « neuf » seulement jusqu'à BrickLink neuf.

Elle ne pose **pas** `prices_fetched_at` : elle n'a interrogé qu'une source, et estampiller
« tout a été essayé » ferait sortir le set de « Compléter les prix manquants » sans que lego.com ou
Amazon aient jamais été interrogés.

## Le scraping est lent exprès

`price_updater` traite les sets **strictement en série**, avec un délai entre chacun. Ce n'est pas
une limite technique à optimiser : lancer des dizaines de navigateurs headless en parallèle sur les
mêmes sites est ce qui fait passer pour du trafic abusif. Si quelqu'un demande « pourquoi c'est si
lent », la réponse est celle-là, pas un bug.

## Différences assumées avec l'app iOS

Elles sont peu nombreuses et chacune a une raison :

- **Keychain → chiffrement Fernet en base.** L'app iOS gérait trois états de lecture
  (présent/absent/indéterminé) parce qu'iOS peut refuser une lecture appareil verrouillé. Côté
  serveur ce cas n'existe pas : « ligne absente » signifie vraiment « non configuré », donc le
  message « non configuré » est sûr ici.
- **Vision → tesseract.js, sur l'appareil.** Une première version de ce port faisait tourner
  tesseract côté serveur (un aller-retour réseau par image) ; la reconnaissance tourne maintenant
  entièrement dans le navigateur, comme sur iOS — seul le moteur diffère (WASM plutôt que le
  framework système), pas l'endroit où il s'exécute. Conséquence directe : scanner ne demande
  aucune connexion au backend, pas même pour identifier un numéro. La boucle de capture reste
  bridée à ~800 ms comme sur iOS, où traiter chaque trame était déjà du gâchis.
- **WKWebView → Playwright/Chromium.** Même mécanique : charger la page, attendre que le défi JS
  soit passé, extraire du DOM. Les sélecteurs et regex sont portés quasi tels quels — chacun encode
  un bug trouvé uniquement en testant contre les vrais sites.
- **`UNUserNotificationCenter` → Web Push + centre de notifications intégré.** La ligne en base est
  écrite d'abord, le push ensuite en best-effort : la fonctionnalité doit marcher pour quelqu'un qui
  n'a jamais accordé la permission push.
- **Pas de pagination `SetDetailPagerView` par `TabView`** : la version web utilise une route et un
  swipe horizontal, avec des boutons précédent/suivant qui ne sont pas décoratifs — un geste seul
  n'est pas une affordance, et les lecteurs d'écran mangent les swipes horizontaux.

## L'écran de liste est unique

Collection, Historique, Liste cadeaux et Nouveaux sets sont **le même écran** avec des données
différentes ; la galerie de minifigs est le même écran avec une grille à la place de la liste.
`components/SetListScreen.tsx` est cet écran. Avant d'en construire un nouveau, pars de celui-là :
recherche, filtres, tri, sélection multiple, menu contextuel et états vides y sont déjà, chacun pour
une raison payée une fois.

L'état de filtre survit à la navigation (magasin module-level, pas du `useState`) et ne se
réinitialise qu'au rechargement complet — un filtre qui se perd chaque fois qu'on ferme un set est
insupportable à l'usage.

## Les boutons de commande d'un écran restent flottants au scroll

Filtre, actualiser, fermer, retour : ces contrôles ne doivent jamais disparaître pendant que le
contenu défile. Rien ne l'impose par construction — il n'existe pas de composant « barre de
commandes » unique — donc chaque écran reprend `sticky`/`fixed` à la main, et tout nouvel écran doit
faire pareil plutôt que redécouvrir la règle au cas par cas :

- `NavBar` (`components/ui.tsx`) porte le bouton retour et les `actions` de `SetListScreen`, donc
  Collection, Historique, Liste cadeaux, Nouveaux sets, Alertes et Paramètres en héritent. `sticky`
  seul ne suffit pas : voir la note sur `env(safe-area-inset-top)` juste au-dessus.
- L'en-tête du pager de `SetDetailPage` (chevrons + « Fermer ») reprend le même traitement.
- La barre de sélection multiple (`components/SelectionBar.tsx`) : `fixed inset-x-0 bottom-0`.
- Le bouton flottant « Sélectionner » (`SetListScreen.tsx`) : `fixed bottom-8 right-5`.
- L'en-tête « Fermer » d'un `Sheet` : placé hors de la zone `overflow-y-auto` qui scrolle, donc
  visible par construction, sans classe de positionnement à part.
- Sur le scanner, « Fermer le scanner » est en `absolute inset-x-0 top-0` — correct seulement parce
  que cet écran plein cadre n'a aucune zone qui défile sous ce bandeau.

`sticky` combiné à un fond flouté (`backdrop-blur`) et une marge négative (`-mx-4`, pour que la
barre morde jusqu'au bord de l'écran) est un déclencheur connu de bug moteur sur WebKit — l'élément
peut se dé-« sticky » ou clignoter pendant l'inertie du scroll, un comportement qui ne se reproduit
pas forcément dans les devtools en mode responsive. C'est pour ça que ces en-têtes n'ont plus de
fond flouté du tout, pas seulement un fond opaque : à vérifier sur un vrai iPhone avant de
réintroduire l'un ou l'autre.

## L'ordre de déclaration des routes est une règle, pas un détail

Starlette teste les routes **dans l'ordre de déclaration**, sans préférence pour les chemins
littéraux. `POST /collection/bulk` déclaré après `POST /collection/{set_num}` part donc dans
`add_to_collection(set_num="bulk")` : 200, aucune erreur levée, et chaque action groupée fait
silencieusement autre chose que ce qu'elle annonce. Ni l'UI, ni les types, ni le build ne peuvent
attraper ça.

Toute route littérale se déclare **avant** les routes paramétrées de son préfixe.
`backend/tests/test_routes.py` le vérifie sur toute la surface, lue depuis le schéma OpenAPI — et
non depuis `app.routes` : FastAPI enveloppe les routeurs inclus dans un objet dont les enfants ne
sont pas exposés et dont les chemins n'ont pas le préfixe `/api`.

## Caméra et pipeline de scan

Tout ce qui recouvre la caméra doit l'arrêter. `isCovered`, dans `pages/ScannerPage.tsx`, est la
seule source de vérité et alimente `useCamera`. Une feuille de plus, un champ de saisie de plus :
ajoute son état à `isCovered`, pas un `useEffect` de plus.

La boucle OCR traite une image toutes les ~800 ms, entièrement sur l'appareil, et **compte les
apparitions de chaque numéro**.
Elle ne se fie jamais au premier candidat d'une image : l'OCR en renvoie un différent à chaque prise
(un nombre de pièces, un âge, le vrai numéro), si bien qu'exiger deux fois de suite le même premier
candidat ne déclenchait jamais rien — la caméra détectait et il ne se passait rien. Gagne celui qui
accumule deux apparitions ; un candidat non revu depuis 6 s est oublié ; un numéro résolu est
verrouillé 30 s, faute de quoi garder une boîte dans le cadre réécrit un `ScanEvent` toutes les deux
secondes.

Le retour sonore et haptique (`lib/feedback.ts`) n'appartient qu'au chemin caméra. Une saisie
manuelle ou une relecture depuis l'Historique passent par le même `resolve()` et ne doivent rien
émettre : l'utilisateur a déjà les yeux sur l'écran. C'est la règle `playsFeedbackSounds` de l'app
iOS, portée telle quelle.

La session du mode lot vit **hors du composant** (`lib/batch-session.ts` : magasin de module doublé
de `sessionStorage`). Le scanner est une route, donc ouvrir un set scanné le démonte : tant que la
session était un `useState`, regarder la liste qu'on venait de scanner était précisément ce qui la
détruisait.

## Ce qui vit en mémoire doit savoir se relire au démarrage

`price_updater` garde l'état du lot en mémoire et n'écrit en base que la date de fin. Rien ne la
relisait au démarrage : chaque redémarrage du conteneur affirmait donc que les prix n'avaient jamais
été actualisés, alors que la base le savait. `PriceUpdater.restore()` est appelé dans le `lifespan`
de `main.py` et `backend/tests/test_price_updater_state.py` le garde.

Règle générale : un singleton en mémoire qui persiste quelque chose doit aussi savoir le relire,
sinon la persistance n'est qu'une écriture.

## Vérifie la forme d'une réponse avant d'écrire le code qui la lit

Rebrickable et BrickLink renvoient des formes qui ne correspondent pas toujours à leur
documentation, et un champ absent se lit `None` sans bruit jusqu'à l'écran. Les compétences
`check-rebrickable-endpoint` et `check-bricklink-endpoint` donnent la sonde à lancer avant
d'ajouter un décodage. Une seule requête suffit — ce sont des API tierces, pas un banc d'essai.

## Un écran ne prétend jamais montrer plus qu'il n'a reçu

La galerie de minifigs demandait 200 lignes à un endpoint plafonné à 200, puis affichait
« 200 minifigs » : elle en montrait un tiers en prétendant les montrer toutes, pendant que l'accueil
— qui lit le `count` du même endpoint — en annonçait 601.

Quand une réponse est paginée, l'écran affiche le total (`count`, calculé **avant** la découpe) et
dit explicitement combien de lignes sont affichées. `results.length` n'est pas un total, c'est la
taille d'une page.

## Ce qui n'est volontairement pas construit

- **Pas de conformité App Store.** L'app iOS a une compétence entière là-dessus (revue Apple, log de
  rejets, divulgation de confidentialité) ; ici il n'y a pas de magasin, et le scraping headless —
  qu'Apple interdit — est précisément ce qui fait marcher les prix. Ne porte pas ces règles.
- **Pas de compte, pas de multi-utilisateur.** Un mot de passe facultatif garde le LAN, rien de plus.
- **Pas de reconciliation des champs catalogue sur un cache chaud** : seul le statut de collection
  est re-vérifié en direct. Un nom ou un nombre de pièces ne bouge plus après la sortie du set.
- **Pas de reprise d'un lot de prix interrompu** : l'app iOS sait reprendre une file mise en pause,
  la version web relance. Le sujet est ouvert, pas tranché.

## Vérifier avant de dire que c'est fini

La compétence `web-build-test` donne la boucle exacte (TypeScript, build Vite, ruff, pytest) et
rappelle le piège du conteneur : l'image embarque le bundle, donc un changement de frontend reste
invisible sur `:8000` tant que l'image n'est pas reconstruite.

Pour un changement visible à l'écran, `ui-parity-check` explique comment piloter l'app en Playwright
et la comparer aux captures iOS de `docs/ui-parity/`. Le volet Browser intégré suffit pour regarder,
mais ses captures peuvent rester en retard sur le DOM après une mise à jour sans navigation : lis le
DOM pour affirmer, prends les images avec Playwright.

## Portée d'un changement

Si tu repères un problème adjacent en travaillant sur autre chose : signale-le, ne le corrige pas
au passage. Un changement doit faire la seule chose qu'il annonce.
