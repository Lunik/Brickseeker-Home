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
- **Vision → tesseract**, côté serveur. Le navigateur envoie une image par seconde environ ; la
  boucle de capture reste bridée comme sur iOS, où c'était déjà du gâchis de traiter chaque image.
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

## Portée d'un changement

Si tu repères un problème adjacent en travaillant sur autre chose : signale-le, ne le corrige pas
au passage. Un changement doit faire la seule chose qu'il annonce.
