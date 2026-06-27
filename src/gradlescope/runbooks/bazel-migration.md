# Keeping the build portable (optional Bazel migration)

You may never migrate to Bazel — but the same disciplines that make a Gradle
build fast also make it *portable*, so the option stays open and cheap.

## What a future migration needs

Bazel (and similar tools) require an explicit, fine-grained, acyclic dependency
graph with hermetic, reproducible actions. The work below pays off immediately
in Gradle and de-risks any future migration:

1. **Explicit dependencies, no cycles.** Every `project(...)` edge is declared;
   the graph is a DAG. (See untangle-dependency-graph.)
2. **Reproducible inputs.** No dynamic versions, no SNAPSHOTs, no
   `mavenLocal()`; pinned, locked dependencies. (See reproducible-dependencies.)
3. **Pinned toolchains.** Each module declares its JDK via a Java toolchain.
   (See java-toolchains.)
4. **No cross-project configuration.** Logic lives in convention plugins, not
   `allprojects`/`subprojects`. This mirrors Bazel's per-package model.
5. **Cacheable, well-declared tasks.** Inputs/outputs are explicit — the same
   property Bazel needs for remote execution.

## A pragmatic path

- Keep Gradle as the build tool; treat "Bazel-readiness" as a *scorecard*, not a
  rewrite.
- If/when you migrate, do it leaf-first: convert low-level library modules
  (which have no internal dependencies) to `BUILD` files, verify parity, then
  move up the graph.
- Consider keeping Gradle for app packaging/Spring Boot while Bazel handles
  library compilation, if a full cutover is not justified.

## Self-check

The higher your gradlescope scores in **dependency-graph**,
**dependency-hygiene**, **toolchains**, and **portability**, the easier any
migration becomes. Aim for a clean DAG and reproducible inputs first.

## References

- [Bazel migration overview](https://bazel.build/migrate)
