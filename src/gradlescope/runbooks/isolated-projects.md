# Isolated Projects

Isolated Projects builds on the configuration cache by isolating each project's
model so projects can be configured in parallel and in isolation. It is the
strategic end-state for fast configuration in large monorepos.

## Prerequisite: remove cross-project configuration

Isolated Projects forbids one project from reaching into another at
configuration time. Before enabling it you must:

1. Remove `allprojects { }` / `subprojects { }` blocks (convert to convention
   plugins — see the convention-plugins runbook).
2. Stop accessing `project(":other").someProperty` during configuration.
3. Replace `rootProject.ext` / cross-project `ext` reads with version catalogs
   and convention plugins.

## Enable (preview)

In `gradle.properties` (use the flag matching your Gradle version):

```
org.gradle.unsafe.isolated-projects=true
```

Then run a build and address each reported violation. The configuration cache
problem report lists exactly which cross-project accesses remain.

## Payoff

- Parallel configuration of all projects.
- Much faster IDE sync and `./gradlew help` on huge repos.
- A cleaner model that is easier to migrate to Bazel later.

## References

- [Isolated Projects](https://docs.gradle.org/current/userguide/isolated_projects.html)
