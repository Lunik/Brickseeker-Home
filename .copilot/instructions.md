# BrickSeeker auto-hébergé — Instructions pour Copilot

## Sources de vérité

Les conventions, l'architecture et les règles métier de ce dépôt vivent dans :

1. **[AGENTS.md](../AGENTS.md)** — Conventions et contexte durement acquis
2. **[docs/contract.md](../docs/contract.md)** — Signatures des services et surface REST

Avant de modifier ce dépôt, lis `AGENTS.md` — ce sont des exigences payées par des bugs résolus et des choix tranchés, pas des suggestions.

## Ce que c'est

Portage web de l'app iOS SwiftUI `brickseeker-app` : FastAPI + SQLite d'un côté, React + Tailwind + Vite de l'autre, le tout servi par **un seul conteneur**. Mêmes fonctionnalités, mêmes règles métier, mêmes textes français.

L'app iOS reste la référence — son `AGENTS.md` documente des dizaines de comportements non évidents avec les preuves qui les justifient. Cherche là-bas avant de « simplifier » quelque chose ici.

## Build & vérification

Compile toujours avant de considérer un changement terminé :

```bash
# Frontend
cd frontend && npx tsc -b --noEmit && npm run build

# Backend
python -c "from app.main import app"

# Ou utilise la skill web-build-test qui fait tout
skill: "web-build-test"
```

## Skills disponibles

Les compétences du dépôt sont dans [`.copilot/skills/`](./skills) :

- **web-build-test** — TypeScript, Vite, ruff, pytest
- **check-bricklink-endpoint** — Sonde signée d'une API BrickLink avant d'implémenter
- **check-rebrickable-endpoint** — Sonde d'une API Rebrickable v3 avant de décoder
- **ui-parity-check** — Capture l'app en Playwright et compare aux baselines iOS
- **scanner-sheet-checklist** — Checklist pour ajouter une surface au scanner
- **clean-feature-revert** — Revert une feature récente (pas juste un git revert)
- **flaticon-icons** — Télécharge et installe des SVG Flaticon

Invoque-les avec `skill: "nom-du-skill"` pendant ton travail.

## Règles clés du dépôt

### Le noyau des prix est unique et doit le rester

`backend/app/services/pricing.py` est **pur** — pas de base, pas de réseau. Il contient quatre chaînes de résolution et rien d'autre ne calcule un prix. Chacune a un rôle distinct :

- `resolve_new_price` (Historique) : lego.com → moins cher d'Amazon/Cdiscount → BrickLink neuf
- `resolve_collection_price` (Collection + Statistiques) : condition de liste, plus cher d'Amazon/Cdiscount
- `resolve_wishlist_price` (Liste cadeaux) : Amazon/Cdiscount **avant** lego.com
- `resolve_minifig_price` : BrickLink seul

### Ce qui est saisi à la main survit aux caches

`clear_cache()` purge `CachedSet`, `CachedSetList`, etc., mais **conserve** `ScanEvent`, `SetPurchaseRecord`, `PriceAlert`, `PriceHistoryEntry`, `CollectionValueSnapshot`. Un seuil d'alerte, un prix payé, la valeur d'une collection — ce qui n'existe nulle part ailleurs doit survivre.

### `was_scanned` dit pourquoi la ligne existe

`True` = utilisateur a scanné le set (Historique) ; `False` = synchronisation de collection. Un set peut être les deux. Scanner un set possédé ne l'efface pas de la Collection.

### Ce que le rafraîchissement de fond surveille

**Uniquement les sets avec une alerte activée**. Pas la collection entière. La passe de fond n'interroge que BrickLink — les prix lego.com/Amazon viennent d'un navigateur headless, lancer Chromium en parallèle sur toute une collection fait blacklister l'IP.

Elle ne pose **pas** `prices_fetched_at` : elle n'a interrogé qu'une source.

### L'écran de liste est unique

Collection, Historique, Liste cadeaux et Nouveaux sets = **le même écran** avec des données différentes. La galerie de minifigs utilise la même base avec une grille.

L'état de filtre survive à la navigation (magasin module-level, pas `useState`) et ne se réinitialise qu'au rechargement complet.

### Les boutons de commande restent flottants au scroll

Filtre, actualiser, fermer, retour : jamais en-dessous du contenu qui défile. Chaque écran reprend `sticky`/`fixed` à la main.

### L'ordre de déclaration des routes est une règle, pas un détail

Starlette teste les routes **dans l'ordre de déclaration**. `POST /collection/bulk` après `POST /collection/{set_num}` part dans `add_to_collection(set_num="bulk")` silencieusement. 

Toute route littérale se déclare **avant** les routes paramétrées de son préfixe. `backend/tests/test_routes.py` le vérifie.

### Caméra et pipeline de scan

`isCovered` dans `pages/ScannerPage.tsx` est la seule source de vérité — elle arrête la caméra et le polling OCR. Ajoute chaque nouveau surface à cette ligne, pas un `useEffect` de plus.

La boucle OCR traite une image toutes les ~800 ms et **compte les apparitions**. Elle ne se fie jamais au premier candidat (l'OCR en renvoie un différent à chaque prise). Gagne celui qui accumule deux apparitions.

Le retour sonore/haptique n'appartient qu'au chemin caméra — pas de feedback lors d'une saisie manuelle ou relecture.

### Ce qui vit en mémoire doit savoir se relire au démarrage

`price_updater` garde l'état du lot en mémoire. `PriceUpdater.restore()` le relit au démarrage depuis la base — sinon la persistance n'est qu'une écriture.

### Vérifie la forme d'une réponse avant d'écrire le code

Rebrickable et BrickLink ne correspondent pas toujours à leur documentation. Les skills `check-rebrickable-endpoint` et `check-bricklink-endpoint` donnent les sondes avant d'implémenter.

### Un écran ne prétend jamais montrer plus qu'il n'a reçu

Quand une réponse est paginée, affiche le `count` total (avant découpe) et dis combien de lignes sont affichées. `results.length` n'est pas un total, c'est la taille d'une page.

### Ce qui n'est volontairement pas construit

- Pas de conformité App Store (pas de magasin, pas de règles Apple)
- Pas de compte multi-utilisateur (mot de passe facultatif pour le LAN seul)
- Pas de réconciliation des champs catalogue sur cache chaud
- Pas de reprise d'un lot de prix interrompu (ouvert)

## Workflow

1. **Comprendre** : Lis `AGENTS.md` si tu touches à l'une des zones clés ci-dessus
2. **Implémenter** : Fais le changement
3. **Valider** : Lance `skill: "web-build-test"` avant de terminer
4. **Commit** : Inclus une trace traçable du changement

## Différences avec l'app iOS

Peu nombreuses, chacune a une raison :

- Keychain → chiffrement Fernet en base
- Vision → tesseract.js sur l'appareil (reconnaissance OCR côté client)
- WKWebView → Playwright/Chromium
- `UNUserNotificationCenter` → Web Push + centre de notifications intégré
- Pas de `TabView` : route + swipe + boutons explicites (accessibilité)

## Important

Si tu repères un problème adjacent : signale-le, ne le corrige pas au passage. Un changement doit faire une seule chose.
