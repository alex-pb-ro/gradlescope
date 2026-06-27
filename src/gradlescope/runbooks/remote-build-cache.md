# Remote build cache without Develocity

You do **not** need Develocity (Gradle Enterprise) for a remote build cache.
Gradle ships a built-in `HttpBuildCache` that talks to any HTTP backend that
supports `GET`/`PUT` of opaque blobs. Several backends work well:

## Option A — Artifactory (or Nexus) generic repository

Create a **generic** repository (e.g. `gradle-build-cache`) and point Gradle at
it. In `settings.gradle.kts`:

```kotlin
buildCache {
    local { isEnabled = true }
    remote<HttpBuildCache> {
        url = uri("https://artifactory.example.com/artifactory/gradle-build-cache/")
        isPush = providers.environmentVariable("CI").isPresent   // only CI writes
        credentials {
            username = providers.environmentVariable("ARTIFACTORY_USER").orNull
            password = providers.environmentVariable("ARTIFACTORY_TOKEN").orNull
        }
    }
}
```

Guidelines:

- **Only CI pushes** (`isPush = true` on CI), developers pull read-only. This
  keeps the cache trustworthy and avoids poisoning from local environments.
- Use a token, not a password. Scope it to the cache repo.
- Set a retention/cleanup policy on the repo (e.g. evict blobs older than N
  days) so it does not grow unbounded.

## Option B — S3 / GCS

Use a community cache plugin (e.g. an S3/GCS build-cache plugin) or run a small
HTTP gateway in front of the bucket and use `HttpBuildCache` as above. Buckets
give cheap, durable storage with lifecycle-based eviction.

## Option C — Self-hosted cache node

Run the open-source `gradle/build-cache-node` container (the same node Gradle
distributes for Enterprise, usable standalone) or any compatible HTTP cache
server, and point `HttpBuildCache.url` at it.

## Verify

```
./gradlew clean build --build-cache --info | grep -i 'FROM-CACHE\|Stored'
```

Run on CI once to populate, then on a clean checkout — most tasks should resolve
`FROM-CACHE`.

## References

- [HttpBuildCache](https://docs.gradle.org/current/userguide/build_cache.html#sec:build_cache_configure_remote)
