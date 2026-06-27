# Java toolchains

Java toolchains let each module declare the exact JDK it compiles and runs with,
independent of the JDK that launched Gradle. This is essential when a monorepo
mixes Java versions (e.g. some modules on 17, others on 21) and multiple Spring
Boot versions.

## Declare a toolchain

Per module (or, better, via a convention plugin):

```kotlin
java {
    toolchain { languageVersion = JavaLanguageVersion.of(21) }
}
```

For Kotlin:

```kotlin
kotlin { jvmToolchain(21) }
```

## Why not `sourceCompatibility`?

`sourceCompatibility`/`targetCompatibility` only set bytecode levels; they still
compile with whatever JDK runs Gradle. Toolchains pin the *actual* JDK and let
Gradle provision it (auto-download or via configured installations), making
builds reproducible across machines and CI.

## Provisioning

Configure toolchain resolution (e.g. the Foojay resolver) in
`settings.gradle.kts` so missing JDKs are downloaded automatically:

```kotlin
plugins { id("org.gradle.toolchains.foojay-resolver-convention") version "0.8.0" }
```

## Mixed versions, cleanly

Define one convention plugin per Java baseline
(`java17-conventions`, `java21-conventions`) and apply the right one per module.
This makes "which modules are on which Java version" explicit and auditable.

## References

- [Toolchains for JVM projects](https://docs.gradle.org/current/userguide/toolchains.html)
