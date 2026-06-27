# Build cache

The build cache reuses *task outputs* (compiled classes, test results,
artifacts) keyed by their inputs. A local cache speeds up your own repeated
builds; a remote cache shares outputs across CI and every developer, so work
done once is reused everywhere.

## Enable the local cache

In `gradle.properties`:

```
org.gradle.caching=true
```

## Make tasks cacheable

- Prefer built-in cacheable tasks (`JavaCompile`, `Test`, etc. are cacheable).
- For custom tasks, declare precise `@Input`/`@OutputDirectory` annotations and
  add `@CacheableTask`. Tasks without declared outputs are never cached.
- Avoid absolute paths and timestamps in inputs; use
  `@PathSensitive(RELATIVE)` for input files.
- Make outputs reproducible (stable archive ordering, no embedded timestamps).

## Measure cache effectiveness

```
./gradlew build --build-cache --scan   # or inspect the build cache hit rate in --info logs
```

Run a clean build twice; the second should show many `FROM-CACHE` tasks.

## Next step

Add a **remote** cache so the hit rate carries across machines — see the
remote-build-cache runbook (you do not need Develocity for this).

## References

- [Build cache](https://docs.gradle.org/current/userguide/build_cache.html)
