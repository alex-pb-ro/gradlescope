# Untangling the dependency graph

A clean, acyclic, shallow module graph is the foundation for parallel builds,
affected-only builds, and a future Bazel migration. Cycles, deep chains, and
giant hub modules undermine all three.

## Cycles

Module cycles (`:a -> :b -> :a`) prevent correct incremental builds and block
affected-only computation.

Break them by:

- Extracting the shared types/interfaces both modules need into a new
  lower-level module that each depends on.
- Inverting a dependency (depend on an abstraction, inject the implementation).
- Moving the offending code to the side that already owns the contract.

## Hub modules (very high fan-in)

A module that hundreds of others depend on means *any* change there marks a huge
fraction of the repo as affected. Split a hub into narrow API modules so
consumers depend only on what they use (e.g. `:core-api` vs `:core-impl`).

## Deep chains (high graph depth)

Deep `A -> B -> C -> D -> ...` chains serialize the build. Flatten by depending
directly on what you use and removing pass-through `api` dependencies that leak
transitive types.

## Right-size visibility

- Prefer `implementation` over `api`. `api` leaks a dependency onto every
  consumer and widens the affected set.
- Use `compileOnly` for compile-time-only deps.

## See it

```
./gradlew :app:dependencies --configuration runtimeClasspath
./gradlew projects
```

gradlescope's Graph page reports cycles, max depth, and hub modules directly.

## References

- [Understanding dependency resolution](https://docs.gradle.org/current/userguide/dependency_resolution.html)
