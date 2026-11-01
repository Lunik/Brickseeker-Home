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

La surface REST, c'est le schéma OpenAPI généré par le backend (`/api/openapi.json`, consultable sur
`/api/docs`). `frontend/src/api/types.ts` en est la copie écrite à la main et rien ne vérifie leur
accord : tout changement de forme se fait **en même temps** des deux côtés de la frontière.

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

Écart assumé avec l'app iOS : pour un set `retired`, les chaînes de **valeur** passent BrickLink neuf
**avant** les marchands. Il ne reste alors que des revendeurs : sur une vraie collection de 506 sets,
les 77 sets valorisés par un marchand l'étaient à une médiane de 2,1 fois BrickLink neuf.

## Un prix n'est cru qu'après examen

Les sites sont interrogés sur le seul numéro : un prix peut être la boîte de toute la série, un
porte-clés ou l'annonce d'un revendeur. `services/quote_assessment.py`, pur comme `pricing.py`, donne
à chaque prix un verdict et une raison, à la lecture du cache. Rien n'est supprimé.

- `rejected`, jamais lu : marchand sur une variante (`71049-5`, jamais le suffixe `-0`, vrai sachet),
  ou sous 35 % du marché (Cultura à 0,99 € pour un set à 160 €).
- `suspect`, lu seulement si aucun prix `trusted` de même état n'existe, et la valeur est alors
  signalée comme incertaine : marchand à plus de 3 fois le marché, BrickLink adossé à moins de 3 lots
  et à plus de 3 fois les autres prix, saut de prix du simple au double contre son propre historique,
  jusqu'à ce qu'un second relevé confirme.
- Le marché est la médiane des ventes BrickLink neuves si au moins 3 existent, sinon la moyenne si
  au moins 3 lots la soutiennent, sinon la médiane d'au moins 3 marchands, sinon le prix occasion,
  qui ne sert alors que de plancher.

`cached_prices` et `all_cached_prices` ne rendent que ce que les chaînes peuvent lire. `amount` n'est
jamais modifié (#213). Un prix d'occasion ne remplace pas un prix neuf douteux : il
sous-évaluerait un set scellé sans le dire. Les variantes n'interrogent plus du tout les marchands.

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

Un troisième mécanisme, distinct de celui-ci et du lot manuel, existe : ouvrir la fiche d'un set ou
d'une minifig planifie une actualisation en tâche de fond si `prices_fetched_at` a plus de 7 jours
(`routers/sets.py`, `services/prices.is_price_stale`). Contrairement à la passe de fond ci-dessus,
elle **pose** `prices_fetched_at` — c'est un vrai `refresh_set_prices`, toutes sources pour un set,
BrickLink seul pour une minifig — et son périmètre est « ce que l'utilisateur a réellement ouvert »,
pas une liste entière : aucun risque de boucle Chromium sur toute une collection.

## Le scraping est lent exprès

`price_updater` traite les sets **strictement en série**, avec un délai entre chacun. Ce n'est pas
une limite technique à optimiser : lancer des dizaines de navigateurs headless en parallèle sur les
mêmes sites est ce qui fait passer pour du trafic abusif. Si quelqu'un demande « pourquoi c'est si
lent », la réponse est celle-là, pas un bug.

## CAPTCHA : la page et le cookie restent côté serveur

Un CAPTCHA de retailer ne devient interactif que lors d'un rafraîchissement explicitement lancé
depuis la fiche d'un set. `InteractivePriceManager` ouvre la page concernée dans le BrowserContext
Playwright partagé ; le frontend ne reçoit qu'un viewer same-origin (captures JPEG et événements
souris/clavier), jamais l'URL CDP ni les cookies. Après validation, seule la source bloquée est
rejouée et les cookies du domaine sont conservés chiffrés via `Credential`.

Un lot manuel, une actualisation automatique de fiche et la passe de surveillance n'ouvrent jamais
de fenêtre : ils marquent la source `captchaRequired`, conservent son ancien prix éventuel et
continuent. Ne transforme pas un job sans utilisateur en session interactive, et ne tente pas de
lire les cookies d'un onglet retailer ouvert directement dans le navigateur : la politique
same-origin l'interdit et contournerait précisément l'isolation recherchée.

Le Browserless distant doit rester **headful avec son fingerprint natif** sur l'affichage virtuel :
pas de plugin stealth ni d'UA Windows forgé. DataDome sait afficher le slider en headless mais
rejette ensuite le fingerprint quand l'utilisateur le termine — le symptôme est exactement le
passage à « You have been blocked » après un slider réussi. Le fallback Playwright local reste
headless faute de display garanti ; ne généralise pas ce fallback au sidecar. Une page DataDome sans
slider, audio ni Retry est terminale pour cette session : ne la présente jamais comme résolvable.

## Différences assumées avec l'app iOS

Elles sont peu nombreuses et chacune a une raison :

- **Keychain → chiffrement Fernet en base.** L'app iOS gérait trois états de lecture
  (présent/absent/indéterminé) parce qu'iOS peut refuser une lecture appareil verrouillé. Côté
  serveur ce cas n'existe pas : « ligne absente » signifie vraiment « non configuré », donc le
  message « non configuré » est sûr ici.
- **Vision → saisie au clavier.** Le scan caméra/OCR et l'import de photo ont été retirés : ils
  marchaient mal en conditions réelles. Le numéro du set se tape à la main depuis l'accueil.
- **WKWebView → Playwright/Chromium.** Même mécanique : charger la page, attendre que le défi JS
  soit passé, extraire du DOM. Les sélecteurs et regex sont portés quasi tels quels — chacun encode
  un bug trouvé uniquement en testant contre les vrais sites.
- **`UNUserNotificationCenter` → Web Push + centre de notifications intégré.** La ligne en base est
  écrite d'abord, le push ensuite en best-effort : la fonctionnalité doit marcher pour quelqu'un qui
  n'a jamais accordé la permission push.
- **Pas de pagination `SetDetailPagerView` par `TabView`** : la version web utilise une route et un
  swipe horizontal, avec des boutons précédent/suivant qui ne sont pas décoratifs — un geste seul
  n'est pas une affordance, et les lecteurs d'écran mangent les swipes horizontaux.

## Navigation : onglets, pas un hub

Écart assumé avec l'app iOS : barre d'onglets en bas sur téléphone, barre latérale sur ordinateur
(`components/AppNav.tsx`). Les racines d'onglet (`ROOT_PATHS`) n'ont pas de bouton retour ; la fiche
d'un set masque la barre. Tout contrôle `fixed` en bas d'écran doit dégager la barre
(`bottom-24 lg:bottom-8`) ; la barre de sélection passe au-dessus (`z-[35]`).

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

- `NavBar` (`components/ui.tsx`) porte le bouton retour (sauf sur une racine d'onglet) et les `actions` de `SetListScreen`, donc
  Collection, Historique, Liste cadeaux, Nouveaux sets, Alertes et Paramètres en héritent. `sticky`
  seul ne suffit pas : voir la note sur `env(safe-area-inset-top)` juste au-dessus.
- L'en-tête du pager de `SetDetailPage` (chevrons + « Fermer ») reprend le même traitement.
- La barre de sélection multiple (`components/SelectionBar.tsx`) : `fixed inset-x-0 bottom-0`.
- Le bouton flottant « Sélectionner » (`SetListScreen.tsx`) : `fixed bottom-24 right-5 lg:bottom-8`.
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
et la comparer aux captures iOS de `docs/ui-parity/`, dossier non versionné à régénérer d'abord. Le volet Browser intégré suffit pour regarder,
mais ses captures peuvent rester en retard sur le DOM après une mise à jour sans navigation : lis le
DOM pour affirmer, prends les images avec Playwright.

## Portée d'un changement

Si tu repères un problème adjacent en travaillant sur autre chose : signale-le, ne le corrige pas
au passage. Un changement doit faire la seule chose qu'il annonce.
