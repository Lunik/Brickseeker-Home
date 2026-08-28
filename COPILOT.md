# Copilot Configuration

## Structure

Ce dépôt utilise **`.copilot/`** pour centraliser toutes les instructions et compétences reconnues par les clients Copilot :

- **Copilot CLI** (ligne de commande)
- **GitHub Copilot** (Web, chat)
- **Copilot in VS Code**
- **Claude Code** (VS Code)

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| [`.copilot/instructions.md`](.copilot/instructions.md) | Instructions centralisées (chargé automatiquement par tous les clients Copilot) |
| [`.copilot/skills/`](.copilot/skills/) | Compétences du dépôt : `web-build-test`, `check-bricklink-endpoint`, etc. |
| [`.copilot/README.md`](.copilot/README.md) | Guide pour ajouter nouvelles compétences |
| [AGENTS.md](AGENTS.md) | Source de vérité : conventions, architecture, règles métier (8200+ lignes) |
| [docs/contract.md](docs/contract.md) | Contrat API : signatures des services, surface REST |
| [CLAUDE.md](CLAUDE.md) | Point d'entrée pour Claude Code (réfère aux sources) |

## Utilisation

### Lancets une compétence

Dans une conversation avec Copilot :

```
skill: "web-build-test"
skill: "check-bricklink-endpoint"
skill: "ui-parity-check"
```

Les 7 compétences disponibles :
1. **web-build-test** — TypeScript, Vite, ruff, pytest
2. **check-bricklink-endpoint** — Sonde signée d'une API BrickLink
3. **check-rebrickable-endpoint** — Sonde d'une API Rebrickable v3
4. **ui-parity-check** — Compare web vs iOS (Playwright + baselines)
5. **scanner-sheet-checklist** — Checklist pour ajouter une surface au scanner
6. **clean-feature-revert** — Revert une feature récente (pas juste git revert)
7. **flaticon-icons** — Télécharge et installe des SVG Flaticon

### Ajouter une compétence

Crée un dossier dans `.copilot/skills/mon-skill/` avec `SKILL.md` :

```yaml
---
name: mon-skill
description: Fait quelque chose d'utile
---

# Ma compétence

Documentation et étapes...
```

Vois [`.copilot/README.md`](.copilot/README.md) pour plus de détails.

## Points clés du dépôt

Lis **absolument** `AGENTS.md` avant de modifier ce dépôt — c'est l'archive de décisions payées par des bugs résolus :

- ✅ Le noyau des prix (`pricing.py`) est pur et unique
- ✅ Ce qui est saisi à la main survit aux caches
- ✅ La surveillance de fond ne couvre que les sets avec alertes activées
- ✅ L'écran de liste est partagé par 4 vues différentes
- ✅ L'OCR compte les apparitions, pas le premier candidat
- ✅ L'ordre de déclaration des routes est une règle, pas un détail

## Vérification avant de terminer

**Toujours** lancer avant d'appeler un changement "fini" :

```bash
skill: "web-build-test"
```

Ou manuellement :
```bash
cd frontend && npx tsc -b --noEmit && npm run build
python -c "from app.main import app"
cd backend && python -m pytest
cd backend && ruff check app
```

## Migration de `.claude/` → `.copilot/`

`.claude/` (ancien) contenait les skills pour Claude Code seul. Depuis, on centralise tout dans `.copilot/` — c'est le standard reconnu par **tous** les clients Copilot.

La structure `.copilot/` est :
- 🌍 **Universelle** — fonctionne partout
- 📦 **Versionnée** — tout est dans git
- 📖 **Self-documenting** — chaque skill a sa doc
