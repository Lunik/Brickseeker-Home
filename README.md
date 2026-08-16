# BrickSeeker (auto-hébergé)

Scanne des sets LEGO®, gère ta collection Rebrickable et ta liste cadeaux Brickset, et compare
ce que vaut un set entre lego.com, BrickLink, Amazon et Cdiscount — le tout dans **un seul
conteneur Docker**, chez toi.

Portage web de l'app iOS [BrickSeeker](../brickseeker-app) : mêmes fonctionnalités, mêmes règles
métier, mêmes textes — accessible depuis n'importe quel navigateur du réseau local plutôt que
depuis un iPhone.

> Projet personnel, sous licence MIT. Sans affiliation avec le groupe LEGO, Rebrickable,
> BrickLink, Brickset, Amazon ou Cdiscount. « LEGO » est une marque du groupe LEGO.

---

## Démarrage rapide

```bash
docker compose up -d
```

Puis ouvre <http://localhost:8000> et va dans **Réglages** pour saisir ta clé API Rebrickable.
C'est tout : la base SQLite, le cache d'images et les catalogues hors-ligne se créent dans `./data`.

Sans Compose :

```bash
docker run -d --name brickseeker -p 8000:8000 -v "$PWD/data:/data" --shm-size=1g brickseeker:latest
```

`--shm-size=1g` n'est pas décoratif : Chromium plante en cours de page avec les 64 Mo de mémoire
partagée que Docker alloue par défaut.

---

## Fonctionnalités

Toutes celles de l'app iOS, à l'identique sauf mention contraire.

- **Scan de sets** — la caméra du navigateur (`getUserMedia`) filme le numéro sur la boîte, l'OCR
  tourne côté serveur (tesseract), et le set est identifié. Saisie manuelle et import de photo
  disponibles en permanence : un scanner sans porte de sortie est un cul-de-sac.
- **Catalogue hors-ligne** — un instantané des ~28 000 sets Rebrickable téléchargé depuis les
  dumps publics, pour que l'identification marche même quand l'API est injoignable.
- **Collection** — compte Rebrickable lié : savoir si un set est déjà possédé et dans quelle
  liste, l'ajouter/retirer/déplacer, tout parcourir avec recherche, filtres et actions groupées.
- **Liste cadeaux** — compte Brickset lié : les sets marqués « wanted », avec import en masse
  depuis un export CSV de liste Rebrickable.
- **Prix multi-sources** — pour chaque set, côte à côte :
  - le prix officiel **lego.com**,
  - la moyenne **BrickLink** des ventes réalisées sur 6 mois, neuf et occasion, via l'API Price
    Guide officielle (identifiants BrickLink requis),
  - **Amazon** et **Cdiscount** (vraies annonces, accessoires filtrés),
  - avec l'écart en % face au prix lego.com, et un objectif €/pièce configurable qui colore le
    prix en vert ou en rouge.
- **Historique** des scans, avec carte des lieux si tu actives la capture de position.
- **Statistiques** — répartition par thème et par année, valeur totale estimée, superlatifs,
  évolution de la valeur de la collection, export CSV et PDF.
- **Alertes de prix** — « préviens-moi si ce set descend sous X € » ; notification web push et
  centre de notifications intégré.
- **Galerie de minifigs** et **Nouveaux sets** — parcours du catalogue.
- **Thème** — couleur LEGO (rouge/jaune/bleu) et clair/sombre/système, stockés côté serveur donc
  identiques sur tous tes appareils.

---

## Configuration

Tout est optionnel : un fichier `.env` vide est une configuration qui fonctionne.
Voir [`.env.example`](.env.example) pour la liste complète.

| Variable | Défaut | Rôle |
|---|---|---|
| `BRICKSEEKER_PASSWORD` | *(vide)* | Protège l'app par mot de passe. Vide = pas de connexion, ce qui convient sur un réseau privé. |
| `BRICKSEEKER_SECRET_KEY` | *(généré)* | Chiffre les identifiants tiers stockés. Généré dans `/data/secret.key` au premier lancement. **À fixer avant de compter sur tes sauvegardes** : le changer rend les identifiants illisibles. |
| `BRICKSEEKER_DATA_DIR` | `/data` | Base SQLite, cache d'images, catalogues. |
| `BRICKSEEKER_SCRAPING_ENABLED` | `true` | `false` = ne lance jamais Chromium. BrickLink et le reste continuent de fonctionner. |
| `BRICKSEEKER_BACKGROUND_REFRESH_ENABLED` | `true` | Rafraîchissement périodique des sets sous alerte. |
| `BRICKSEEKER_OCR_ENABLED` | `true` | OCR serveur pour le scan. |

### Identifiants tiers

Aucun n'est obligatoire pour démarrer, et chacun débloque une partie de l'app. Ils se saisissent
dans **Réglages**, jamais dans un fichier de configuration.

| Service | Ce que ça débloque | Où l'obtenir |
|---|---|---|
| Clé API Rebrickable | Identification des sets, catalogue | [rebrickable.com/profile](https://rebrickable.com/profile) |
| Compte Rebrickable | Synchronisation de la collection | ton compte — le mot de passe sert **une fois** à obtenir un jeton, puis est oublié |
| Clé + compte Brickset | Liste cadeaux | [brickset.com](https://brickset.com) |
| Identifiants BrickLink (4 valeurs OAuth) | Prix neuf/occasion BrickLink | [bricklink.com/v3/api.page](https://www.bricklink.com/v3/api.page) |

---

## Confidentialité

- Les identifiants tiers sont **chiffrés au repos** (Fernet, clé dérivée de `BRICKSEEKER_SECRET_KEY`) :
  le fichier SQLite seul ne suffit pas à les lire.
- Les mots de passe Rebrickable et Brickset ne sont **jamais stockés** — ils servent une seule fois
  à obtenir un jeton de session, exactement comme dans l'app iOS.
- Aucune analytique, aucun appel sortant en dehors des services que tu as configurés et des dumps
  publics Rebrickable.
- La position des scans est **désactivée par défaut**, ne concerne que les sets absents de la
  collection, et est effacée dès que le set y entre : son seul intérêt est « dans quel magasin
  ai-je vu cette affaire », question sans objet une fois le set acheté.

---

## Architecture

```
brickseeker-home/
├── backend/            FastAPI + SQLite
│   └── app/
│       ├── models.py       schéma SQLite (port des @Model SwiftData)
│       ├── services/       clients externes, dépôt local, prix, catalogue, OCR, planificateur
│       │   └── pricing.py  le noyau de résolution des prix — pur, sans I/O
│       ├── routers/        surface REST sous /api
│       └── static/         bundle Vite compilé (généré)
├── frontend/           React + TypeScript + Tailwind + Vite
│   └── src/{api,components,hooks,lib,pages}
├── docs/contract.md    le contrat partagé backend ↔ frontend
├── Dockerfile          image unique (Chromium + tesseract + API + UI)
└── docker-compose.yml
```

Deux principes portés tels quels depuis l'app iOS, parce que tout le reste en dépend :

**Une seule fonction décide de ce que vaut un set.** `services/pricing.py` contient les chaînes de
résolution (`resolve_new_price`, `resolve_collection_price`, `resolve_wishlist_price`,
`resolve_minifig_price`) et rien d'autre ne calcule un prix. C'est la raison pour laquelle la ligne
d'une liste, le total des statistiques et l'export CSV ne peuvent pas être en désaccord.

**Ce qui est saisi à la main survit aux caches.** « Vider le cache » supprime les sets en cache,
les listes, les prix courants et les ventes BrickLink. Il conserve les scans, les prix payés, les
alertes, l'historique des prix et la valeur quotidienne de la collection : ces données ne se
re-téléchargent nulle part.

---

## Développement

```bash
# API
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium          # uniquement pour les prix lego.com/Amazon/Cdiscount
BRICKSEEKER_DATA_DIR=./.data .venv/bin/uvicorn app.main:app --reload

# UI (proxy vers http://localhost:8000)
cd frontend
npm install && npm run dev
```

L'OCR a besoin de tesseract en local (`brew install tesseract tesseract-lang` sur macOS,
`apt install tesseract-ocr tesseract-ocr-fra` sur Debian).

---

## Pourquoi l'image fait ~1,6 Go

lego.com est derrière un Cloudflare Managed Challenge, Amazon et Cdiscount derrière leurs propres
protections anti-bot. Aucun client HTTP simple ne passe, quels que soient les en-têtes : le défi
exige d'exécuter du vrai JavaScript. Chromium est donc embarqué. `BRICKSEEKER_SCRAPING_ENABLED=false`
permet de s'en passer — les prix BrickLink, la collection, l'historique et les statistiques
continuent de fonctionner.

---

## Licence

[MIT](LICENSE) © Lunik
