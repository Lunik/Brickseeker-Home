# Comparaison visuelle iOS ↔ web

Captures de référence des deux applications, écran par écran, à la même taille logique
(402 × 874, l'iPhone 17 Pro). Elles servent de **base de comparaison** : une capture refaite
écrase la précédente, donc après une nouvelle passe `git status` *est* le diff visuel.

```
docs/ui-parity/
├── ios/            captures du simulateur
├── web/            captures de l'app web
├── _contact-ios.png  planche-contact (générée)
└── _contact-web.png
```

## Refaire les captures

**Web** — automatique, l'app doit tourner :

```bash
python3 scripts/capture_ui.py --out docs/ui-parity/web --base http://localhost:8099
```

**iOS** — la navigation reste manuelle. L'app n'a pas de liens profonds pour la plupart des
écrans, et une chaîne de taps à coordonnées figées casse dès qu'une hauteur de ligne change
(c'est arrivé : trois captures se sont retrouvées sur le mauvais écran). Naviguez à la main, puis :

```bash
scripts/capture_ios.sh 03-collection
```

`xcrun simctl` écrit directement sur le disque, donc une capture ne coûte rien à relire ensuite.

**Planche-contact** — pour vérifier d'un coup d'œil que chaque fichier est bien l'écran attendu :

```bash
python3 - <<'EOF'
from PIL import Image, ImageDraw
from pathlib import Path
for side in ("ios", "web"):
    files = sorted(Path(f"docs/ui-parity/{side}").glob("*.png"))
    if not files: continue
    W, H, cols = 190, 410, 5
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols*W, rows*(H+22)), (24,24,26)); draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(files):
        with Image.open(p) as im:
            im.thumbnail((W-8, H-8)); x, y = (i%cols)*W+4, (i//cols)*(H+22)+4
            sheet.paste(im, (x,y)); draw.text((x, y+H-4), p.stem[:26], fill=(200,200,205))
    sheet.save(f"docs/ui-parity/_contact-{side}.png")
EOF
```

## Écrans

| # | Écran | iOS | Web |
|---|---|:--:|:--:|
| 01 | Accueil | ✅ | ✅ |
| 02 | Scanner | ✅ | ✅ |
| 03 | Ma collection | ✅ | ✅ |
| 04 | Historique | ✅ | ✅ |
| 05 | Carte des scans | ❌ | ✅ |
| 06 | Liste cadeaux | ✅ | ✅ |
| 07 | Statistiques | ✅ | ✅ |
| 08 | Mes minifigs | ✅ | ✅ |
| 09 | Nouveaux sets | ✅ | ✅ |
| 10 | Alertes de prix | ❌ | ✅ |
| 11 | Paramètres | ✅ | ✅ |
| 12 | Onboarding | ❌ | ✅ |
| 13 | Fiche set | ✅ | ✅ |

## Ce que les captures ne prouvent pas

À lire avant de conclure qu'un écran « diverge » :

- **Les données diffèrent entre les deux installations.** L'app iOS n'a pas téléchargé les
  catalogues (minifigs, sets) ni la plupart des prix ; l'app web si. Un écran vide d'un côté et
  rempli de l'autre est une différence de *données*, pas de conception. Les trois écrans concernés
  sont marqués dans la liste des tâches.
- **Trois captures iOS manquent** et pour de bonnes raisons : la carte des scans demande un scan
  géolocalisé, les alertes se rejoignent depuis Paramètres, et l'onboarding ne s'affiche qu'à la
  première installation.
- **Le scanner ne peut pas être vérifié ici.** Le simulateur n'a pas de caméra et le panneau
  navigateur bloque l'accès à la caméra : les deux captures montrent la chrome de l'écran, pas le
  flux vidéo. Cet écran se vérifie sur un appareil réel.
- **Les métriques d'une police diffèrent.** SF Pro est plus étroite que la police système du
  navigateur : à taille égale, un libellé qui tient sur une ligne sur iOS peut passer à deux sur le
  web. Ce n'est pas un écart de mise en page à « corriger » en rétrécissant le texte.
