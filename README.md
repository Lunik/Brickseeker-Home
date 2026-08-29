# BrickSeeker (auto-hébergé)

Scanne des sets LEGO®, gère ta collection Rebrickable et ta liste cadeaux Brickset, et compare
ce que vaut un set entre lego.com, BrickLink et plusieurs sites marchands — avec Docker Compose,
chez toi.

Portage web de l'app iOS [BrickSeeker](../brickseeker-app) : mêmes fonctionnalités, mêmes règles
métier, mêmes textes — accessible depuis n'importe quel navigateur du réseau local plutôt que
depuis un iPhone.

> Projet personnel, sous licence MIT. Sans affiliation avec le groupe LEGO, Rebrickable,
> BrickLink, Brickset ou des sites marchands tiers. « LEGO » est une marque du groupe LEGO.

---

## Démarrage rapide

```bash
docker compose up -d
```

Puis ouvre <http://localhost:8000> et va dans **Réglages** pour saisir ta clé API Rebrickable.
C'est tout : la base SQLite, le cache d'images et les catalogues hors-ligne se créent dans `./data`.

Sans Compose : possible, mais les prix lego.com/sites marchands ont besoin d'un Chromium
joignable en CDP (voir [Chromium tourne à part](#chromium-tourne-à-part)) — sans lui, BrickLink,
la collection, l'historique et les statistiques continuent de fonctionner, le reste non.
Pour tout avoir sans Compose :

```bash
docker network create brickseeker
docker run -d --name brickseeker-chromium --network brickseeker --shm-size=1g -e TIMEOUT=86400000 \
  ghcr.io/browserless/chromium:v2.55.4
docker run -d --name brickseeker -p 8000:8000 -v "$PWD/data:/data" --network brickseeker \
  -e BRICKSEEKER_BROWSER_WS_ENDPOINT=ws://brickseeker-chromium:3000 brickseeker:latest
```

---

## Fonctionnalités

Toutes celles de l'app iOS, à l'identique sauf mention contraire.

- **Scan de sets** — la caméra du navigateur (`getUserMedia`) filme le numéro sur la boîte, l'OCR
  tourne entièrement sur l'appareil (tesseract.js), et le set est identifié — aucune connexion au
  backend nécessaire pour cette étape. Saisie manuelle et import de photo disponibles en
  permanence : un scanner sans porte de sortie est un cul-de-sac.
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
  - des sites marchands (**Amazon**, **Cdiscount**, **Cultura**, **Fnac**, **King Jouet**,
    **La Grande Récré**, **JouéClub**, **Carrefour**, **Intermarché**) avec accessoires filtrés,
  - avec l'écart en % face au prix lego.com, et un objectif €/pièce configurable qui colore le
    prix en vert ou en rouge.

Les sites marchands gardent le contrôle de leur accès : Fnac et King Jouet peuvent imposer un
CAPTCHA DataDome, et Intermarché ne publie pas de prix national sans magasin sélectionné. Un blocage
est détecté puis mis en pause quinze minutes ; il n'immobilise plus chaque set du lot. Les autres
sources continuent et leurs résultats sont enregistrés dès qu'ils arrivent.

Un rafraîchissement lancé explicitement depuis la fiche d'un set ouvre une petite fenêtre d'attente.
Si un retailer demande un CAPTCHA, cette fenêtre affiche la page Chromium exacte sous forme de
viewer interactif : l'utilisateur valide le défi, puis BrickSeeker reprend uniquement cette source.
Le cookie obtenu ne transite jamais par le navigateur utilisateur ; il reste côté serveur et est
persisté chiffré avec la même clé que les identifiants API. Autorisez donc les fenêtres surgissantes
pour BrickSeeker. Un lot ou une passe automatique n'ouvre jamais cette fenêtre : il signale
« CAPTCHA requis », conserve l'ancien prix éventuel et continue avec les autres sources.
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
│       ├── services/       clients externes, dépôt local, prix, catalogue, planificateur
│       │   └── pricing.py  le noyau de résolution des prix — pur, sans I/O
│       ├── routers/        surface REST sous /api
│       └── static/         bundle Vite compilé (généré)
├── frontend/           React + TypeScript + Tailwind + Vite
│   └── src/{api,components,hooks,lib,pages}   OCR (tesseract.js) dans lib/offline-ocr.ts
├── docs/contract.md    le contrat partagé backend ↔ frontend
├── Dockerfile          image applicative (API + UI, sans Chromium)
└── docker-compose.yml  service applicatif + sidecar Chromium
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
.venv/bin/playwright install chromium          # uniquement pour les prix lego.com/sites marchands
BRICKSEEKER_DATA_DIR=./.data .venv/bin/uvicorn app.main:app --reload

# UI (proxy vers http://localhost:8000)
cd frontend
npm install && npm run dev
```

---

## Chromium tourne à part

lego.com est derrière un Cloudflare Managed Challenge, et les sites marchands derrière leurs
propres protections anti-bot.
protections anti-bot. Aucun client HTTP simple ne passe, quels que soient les en-têtes : le défi
exige d'exécuter du vrai JavaScript, donc un vrai moteur de navigateur. `BRICKSEEKER_SCRAPING_ENABLED=false`
permet de s'en passer entièrement — les prix BrickLink, la collection, l'historique et les
statistiques continuent de fonctionner.

Ce moteur ne vit plus dans l'image applicative : `docker-compose.yml` définit un second service,
`chromium` ([browserless](https://github.com/browserless/browserless)), que `brickseeker` pilote
à distance via CDP (`BRICKSEEKER_BROWSER_WS_ENDPOINT`). Ça garde l'image principale légère — un
changement de code ne re-télécharge plus Chromium et ses dépendances système — et isole un
processus notoirement gourmand en mémoire dans son propre conteneur, avec son propre `shm_size`.
Rien ne change côté fonctionnalités ni côté anti-bot : mêmes drapeaux de lancement Chromium,
juste atteint autrement. Le délai Browserless d'un jour est volontaire : le backend conserve un
contexte CDP pour réutiliser les cookies de défi entre deux sets, sait le reconnecter à son
expiration, et borne chaque source et chaque set avec des délais bien plus courts de son côté. Il
ne rend jamais plus de deux pages marchandes à la fois : au-delà, les sites lourds s'affament
mutuellement et peuvent tous échouer alors que chacun répond correctement seul.

Browserless OSS ne fournit pas de lien interactif vers une page existante. Le viewer CAPTCHA est
donc servi par l'API authentifiée de BrickSeeker (captures JPEG et événements souris/clavier) :
le port CDP reste privé au réseau Compose et aucun jeton de contrôle Chromium n'est exposé au LAN.

---

## Licence

[MIT](LICENSE) © Lunik

---

> ⚗️ **Projet expérimental, 100 % vibecodé.** Écrit presque entièrement en
> pair-programming avec un assistant IA, pour le plaisir et l'exploration —
> sans garantie de qualité, de maintenance ni de bonnes pratiques. À prendre
> tel quel.
