# .copilot/ — Configuration Copilot du dépôt

Ce répertoire contient les instructions et compétences partagées par **tous les clients Copilot** :
GitHub Copilot (Web, CLI, VS Code), Claude Code, etc.

## Structure

```
.copilot/
├── instructions.md       # Instructions centralisées (reconnu par tous les clients)
├── skills/               # Compétences du dépôt
│   ├── web-build-test/
│   ├── check-bricklink-endpoint/
│   ├── check-rebrickable-endpoint/
│   ├── ui-parity-check/
│   ├── scanner-sheet-checklist/
│   ├── clean-feature-revert/
│   └── flaticon-icons/
└── README.md            # Ce fichier
```

## Comment ça marche

### Instructions (`instructions.md`)

Chargé **automatiquement** par tous les clients Copilot. Contient :
- Les règles et conventions du dépôt
- Références aux sources de vérité (`AGENTS.md`, `docs/contract.md`)
- Checklist de vérification avant de terminer
- Skills disponibles et quand les invoquer

### Skills (`.copilot/skills/*/`)

Chaque compétence a sa propre structure :

```
skill-name/
├── SKILL.md              # Frontmatter YAML + doc
├── script.py|.js|.sh     # Optionnel : code d'exécution
└── autres fichiers       # Optionnel : assets, templates
```

Exemple de frontmatter `SKILL.md` :
```yaml
---
name: web-build-test
description: Run the verification loop for the self-hosted web port
---

# Web build & test

Documentation et étapes...
```

Les skills sont invoqués avec `skill: "nom-du-skill"` dans les conversations Copilot.

## Ajouter une nouvelle compétence

1. Crée `skills/mon-skill/SKILL.md`
2. Ajoute le frontmatter YAML avec `name` et `description`
3. Documente les étapes et commandes
4. Ajoute des scripts si nécessaire (Python, JavaScript, Shell)
5. La compétence sera automatiquement découverte

Exemple minimal :

```markdown
---
name: ma-competence
description: Fait quelque chose d'utile dans ce projet
---

# Ma compétence

Explique ce qu'elle fait et comment l'utiliser.

## Étapes

1. Fais ça
2. Puis ça
3. Vérifie avec ça
```

## Différence avec `.claude/` (ancien)

`.claude/` était spécifique à Claude Code (VS Code). `.copilot/` est le standard **reconnu par tous les clients Copilot** et GitHub. Progressivement, tout migre vers `.copilot/`.

## Localisation du contenu

- **Instructions générales du dépôt** : `.copilot/instructions.md` (partagé partout)
- **Conventions métier** : `AGENTS.md` (source de vérité, référencé depuis instructions.md)
- **Contrat API** : `docs/contract.md` (source de vérité)
- **Autres docs** : `CLAUDE.md`, `README.md` (points d'entrée, référencent les sources)

## Notes

- Ne modifie pas `.copilot/skills/` sans raison — chaque skill encode une leçon apprise
- Les skills ne doivent jamais être dupliqués (pas de `web-build-test` dans `.claude/` ET `.copilot/`)
- Quand tu apprends quelque chose de nouveau, mets-le dans `AGENTS.md`, pas dans un skill
