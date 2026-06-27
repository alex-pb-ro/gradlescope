# Configuration cache

The configuration cache caches the result of the *configuration phase* (the
task graph) and reuses it on subsequent builds with the same inputs. On a large
monorepo this can cut multi-second (or multi-minute) configuration times to
near-zero.

## Enable it

In `gradle.properties`:

```
org.gradle.configuration-cache=true
org.gradle.configuration-cache.problems=warn
```

Start with `problems=warn` so the build does not fail while you fix
incompatibilities, then switch to `fail` once clean.

## Common incompatibilities to fix

- Reading `System.getProperty`, environment variables, or files at
  configuration time. Use providers (`providers.systemProperty(...)`,
  `providers.environmentVariable(...)`) which are tracked correctly.
- Tasks referencing `Project` at execution time. Capture only the values you
  need (as `@Input`/`@InputFiles`) instead of the whole project.
- `buildSrc` or convention code that mutates other projects (see
  the convention-plugins runbook).
- Plugins that are not configuration-cache compatible. Identify them by running
  with `--configuration-cache` and reading the reported problems; upgrade the
  plugin, or isolate/replace it.

## Validate

```
./gradlew help --configuration-cache
./gradlew <your-task> --configuration-cache   # run twice; second run should say "Reusing configuration cache"
```

## Order of adoption

1. Remove cross-project configuration (`allprojects`/`subprojects`).
2. Pin dependency versions (no dynamic/SNAPSHOT).
3. Turn on the configuration cache with `problems=warn`.
4. Fix reported problems module by module.
5. Switch to `problems=fail` and adopt Isolated Projects.

## References

- [Configuration cache](https://docs.gradle.org/current/userguide/configuration_cache.html)
