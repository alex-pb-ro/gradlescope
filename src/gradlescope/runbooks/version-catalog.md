# Version catalogs

A version catalog centralizes dependency and plugin coordinates in one TOML
file, eliminating version drift across hundreds of modules and giving you
type-safe accessors.

## Create `gradle/libs.versions.toml`

```toml
[versions]
spring-boot = "3.2.5"
guava = "33.0.0-jre"

[libraries]
guava = { module = "com.google.guava:guava", version.ref = "guava" }
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }

[bundles]
web = ["guava", "spring-boot-starter-web"]
```

## Use it in a module

```kotlin
plugins { alias(libs.plugins.spring.boot) }

dependencies {
    implementation(libs.guava)
    implementation(libs.bundles.web)
}
```

## Migration tips

- Migrate incrementally: introduce the catalog, then move modules over in
  batches. Both styles can coexist during the transition.
- Use `bundles` for groups always used together.
- Combine with a platform/BOM (e.g. `spring-boot-dependencies`) so transitive
  versions stay aligned.

## References

- [Version catalogs](https://docs.gradle.org/current/userguide/platforms.html)
