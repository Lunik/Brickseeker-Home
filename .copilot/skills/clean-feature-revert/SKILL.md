---
name: clean-feature-revert
description: Use when the user asks to revert a recently-added feature in this repo. A plain `git revert` of the feature's commit is not enough — feature work is spread over several commits, and this stack keeps unused routes, tables, contract lines and types without ever complaining.
---

# Reverting a feature cleanly

`git revert <commit>` undoes that commit's diff and nothing else. Feature work here lands over
several commits (a service method first, the route and the screen later), so reverting the "main"
commit leaves the plumbing behind — as the iOS app found out when a helper committed earlier
survived the revert and called a constant the revert had deleted.

**Here it is worse, because nothing breaks.** Swift refused to compile that leftover; FastAPI
serves an unused route forever, SQLite keeps a table no model reads, and `docs/contract.md` is
prose. A green build proves only that the *reachable* code is consistent — the sweeps below are
the only thing that finds the rest.

## 1. Revert

```bash
git revert --no-edit <feature-commit>
```

## 2. Sweep for each kind of leftover

**Unused REST route** — every route path, checked against the frontend (all API calls go through
`api.*` with literal paths, so a path absent from `frontend/src` has no caller):

```bash
for f in backend/app/routers/*.py; do
  pre=$(rg -o 'prefix="([^"]*)"' -r '$1' "$f" | head -1)
  rg -o '@router\.[a-z]+\("([^"]*)"' -r '$1' "$f" | sed "s|^|$pre|"
done | sort -u | while read -r p; do
  head=${p%%\{*}; head=${head%/}; tail=${p##*\}}
  [ -z "$head" ] && head="$p"
  if [ -n "$tail" ] && [ "$tail" != "$p" ]
    then rg -q "$head.*$tail" frontend/src || echo "ORPHAN? $p"
    else rg -q -- "$head" frontend/src || echo "ORPHAN? $p"
  fi
done
```

Six routes are already on that list (2026-08: `/auth/logout`, `/catalog/themes`, `/sets/resolve`,
`/sets/search`, `/prices/{set_num}/history`, `/prices/{set_num}/store-refresh`) and predate any
revert — only a **new** name is your leftover.

**Orphaned model, and stale TypeScript type** — declared, referenced nowhere (both silent on a
clean tree):

```bash
rg -o '^class (\w+)\(Base\)' -r '$1' backend/app/models.py | while read -r m; do
  rg -q "\b$m\b" backend/app backend/tests --glob '!models.py' || echo "UNUSED MODEL: $m"
done
rg -o '^export (?:interface|type) (\w+)' -r '$1' frontend/src/api/types.ts | while read -r t; do
  rg -q "\b$t\b" frontend/src --glob '!api/types.ts' || echo "UNUSED TYPE: $t"
done
```

**Dead entry in `docs/contract.md`** — a documented path with no router behind it:

```bash
rg -o '^\| *(?:GET|POST|PUT|PATCH|DELETE) *\| *`([^`]+)`' -r '$1' docs/contract.md |
  sed 's/?.*//' | sort -u | while read -r p; do
  seg=$(echo "$p" | sed 's/{[^}]*}//g' | awk -F/ '{print $NF}')
  [ -z "$seg" ] && seg=$(echo "$p" | awk -F/ '{print $2}')
  rg -q -- "$seg" backend/app/routers || echo "NOT IN ROUTERS: $p"
done
```

Delete the contract line in the *same* commit as the code on both sides — AGENTS.md's rule that
contract and code move together applies to removal too.

**Column with no migration.** There is no Alembic and no `ALTER TABLE` anywhere: `init_db()` runs
`create_all`, which adds missing tables and never alters an existing one. A column the feature
added therefore exists only in databases created after it, and stays there forever:

```bash
diff <(sqlite3 data/brickseeker.db ".tables" | tr -s ' ' '\n' | sed '/^$/d' | sort) \
     <(rg -o '__tablename__ = "([^"]*)"' -r '$1' backend/app/models.py | sort)
sqlite3 data/brickseeker.db "PRAGMA table_info(cached_sets)" | cut -d'|' -f2
```

Only on the DB side is dead weight: leave it (dropping a SQLite column rebuilds the table and risks
live data) but say so in the commit message. Only on the model side is a bug — existing databases
lack it and will raise at query time.

**Stale built asset.** `backend/app/static/` is Vite output, gitignored and minified: `git revert`
never touches it, repo-wide `rg` skips it, and grepping it for source symbols is unreliable. The
reverted feature stays on screen until the bundle is rebuilt (AGENTS.md § Build). Never hand-edit
it.

## 3. Date anything the sweeps find

```bash
git log -S"<symbol>" --oneline --no-show-signature -- backend frontend docs
```

`log.showSignature` is on here — without `--no-show-signature` each line is buried in three lines of
GPG output. If the introducing commit predates the one you reverted, it is a leftover: delete it,
and its pair (the model *and* its Pydantic schema, the route *and* its contract row).

## 4. Verify, then commit the cleanup separately

Run the `web-build-test` skill — necessary, and unlike on iOS not sufficient: none of the leftovers
above can fail it. With no `backend/.venv`, the last built image gives the import check:

```bash
docker run --rm -v "$PWD/backend:/w:ro" -w /w brickseeker:latest python -c "import app.main"
```

Commit the cleanup apart from the revert, saying *why* `git revert` alone was not enough.
