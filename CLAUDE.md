# CLAUDE.md

Les conventions de ce dépôt vivent dans [`AGENTS.md`](AGENTS.md), lu aussi par les autres agents.
Une seule source, importée ici pour que Claude Code la charge automatiquement — n'y recopie rien,
corrige `AGENTS.md`.

@AGENTS.md

## Copilot (tous les clients)

Les instructions centralisées pour tous les clients Copilot (GitHub Copilot, CLI, VS Code) vivent
dans [`.copilot/instructions.md`](.copilot/instructions.md) — c'est le standard reconnu partout.

Les compétences du dépôt sont dans [`.copilot/skills/`](.copilot/skills) : vérification avant de
dire qu'un changement est fini, sondes d'API, parité d'écran avec l'app iOS, checklist du scanner.
