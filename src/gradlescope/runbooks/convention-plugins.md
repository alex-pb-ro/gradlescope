# Convention plugins (replacing allprojects/subprojects)

Cross-project configuration (`allprojects { }`, `subprojects { }`, root-level
`ext`, and `apply from:` script plugins) is convenient but it:

- breaks the configuration cache and Isolated Projects,
- couples every module to the root build,
- makes the dependency graph and ownership impossible to reason about.

Replace it with **convention plugins**: ordinary plugins that encapsulate a
shared setup and are applied explicitly by the modules that want them.

## Where to put them

- `build-logic/` (a separate included build) — preferred for large repos.
- `buildSrc/` — simplest, but it invalidates more often and is shared globally.

Example `build-logic/settings.gradle.kts` is included from the root
`settings.gradle.kts`:

```kotlin
pluginManagement { includeBuild("build-logic") }
```

## Write a convention plugin

`build-logic/src/main/kotlin/myorg.java-conventions.gradle.kts`:

```kotlin
plugins { `java-library` }

java {
    toolchain { languageVersion = JavaLanguageVersion.of(21) }
}

tasks.withType<Test>().configureEach { useJUnitPlatform() }
```

## Apply it from a module

```kotlin
plugins { id("myorg.java-conventions") }
```

## Migration recipe

1. Identify each concern currently set in `subprojects { }` (Java version,
   repositories, common deps, test config).
2. Create one convention plugin per concern (or one combined per archetype:
   `java-conventions`, `spring-boot-conventions`, `library-conventions`).
3. Apply the convention plugins in each module; delete the cross-project block.
4. Verify with `./gradlew help --configuration-cache`.

## References

- [Sharing build logic with convention plugins](https://docs.gradle.org/current/userguide/sharing_build_logic_between_subprojects.html)
