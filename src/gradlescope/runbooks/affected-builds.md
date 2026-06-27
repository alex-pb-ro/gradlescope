# Affected-only builds

Today the monorepo runs `gradle build` over everything. The goal is to build and
test only the modules **affected** by a change: the changed modules plus every
module that (transitively) depends on them.

## The model

1. Compute the set of changed files (e.g. `git diff --name-only origin/main...`).
2. Map each file to its owning module.
3. A change to a *build-wide* file (root build, `settings.gradle`,
   `gradle.properties`, `gradle/`, `buildSrc/`, `build-logic/`) affects
   **everything** — rebuild all.
4. Otherwise, affected = changed modules ∪ their transitive dependents.

gradlescope computes exactly this — see `gradlescope affected --changed-from`.

## Wire it into CI

```bash
# Example: get changed files vs the merge base, then the affected module list.
CHANGED=$(git diff --name-only "$(git merge-base origin/main HEAD)" HEAD)
AFFECTED=$(gradlescope affected --root . $(for f in $CHANGED; do echo --file "$f"; done) --format lines)

# Turn module paths into Gradle tasks and run just those.
TASKS=$(for m in $AFFECTED; do echo "${m}:build"; done)
./gradlew $TASKS --parallel --build-cache
```

## Prerequisites for correctness

- **No cycles** in the module graph (cycles make "affected" ill-defined).
- Accurate `project(...)` dependencies — affected analysis is only as good as
  the declared graph.
- A remote build cache so unaffected-but-rebuilt-on-another-branch outputs are
  still reused.

## Caveats

- Non-code inputs (shared test fixtures, generated code, resources) must be
  modeled as module dependencies or they will be missed.
- Treat configuration/build-tool changes as global until proven otherwise.

## References

- [Command-line interface: task selection](https://docs.gradle.org/current/userguide/command_line_interface.html)
