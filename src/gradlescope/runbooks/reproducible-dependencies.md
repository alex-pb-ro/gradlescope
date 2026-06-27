# Reproducible dependencies

Dynamic versions (`1.+`, `latest.release`), `-SNAPSHOT`s, and `mavenLocal()`
make builds non-reproducible: the same source can produce different outputs on
different days or machines. They also defeat the build and configuration caches,
because the cache key cannot be stable.

## Fixes

- **Pin exact versions**, ideally through a version catalog (see the
  version-catalog runbook).
- **Remove `mavenLocal()`** from repositories; rely on a hosted repository
  (e.g. Artifactory/Nexus). `mavenLocal()` injects machine-local state.
- **Replace SNAPSHOTs** with released versions. If you must consume internal
  in-flight artifacts, publish immutable, uniquely-versioned snapshots and pin
  the exact timestamped version.

## Lock what you resolve

Enable dependency locking so transitive versions are pinned and reviewed:

```kotlin
dependencyLocking { lockAllConfigurations() }
```

Generate/refresh locks:

```
./gradlew dependencies --write-locks
```

## Verify reproducibility

```
./gradlew :module:dependencies --configuration runtimeClasspath
```

The resolved graph should be identical across runs and machines.

## References

- [Dependency locking](https://docs.gradle.org/current/userguide/dependency_locking.html)
- [Declaring versions](https://docs.gradle.org/current/userguide/single_versions.html)
