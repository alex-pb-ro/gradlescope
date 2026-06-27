"""Tests for build-script / settings / properties parsing."""
from gradlescope.scan import parser


class TestPlugins:
    def test_groovy_plugins_block_with_versions(self):
        text = """
        plugins {
            id 'java'
            id 'org.springframework.boot' version '3.2.0'
            id "io.spring.dependency-management" version "1.1.4"
            id 'com.example.internal' version '1.0' apply false
        }
        """
        plugins = parser.parse_plugins(text)
        by_id = {p.id: p for p in plugins}
        assert by_id["java"].version is None
        assert by_id["org.springframework.boot"].version == "3.2.0"
        assert by_id["io.spring.dependency-management"].version == "1.1.4"
        assert by_id["com.example.internal"].applied is False

    def test_kotlin_plugins_block(self):
        text = """
        plugins {
            java
            `java-library`
            id("org.springframework.boot") version "3.2.0"
            kotlin("jvm") version "1.9.22"
            id("com.example.internal") version "1.0" apply false
        }
        """
        plugins = parser.parse_plugins(text)
        by_id = {p.id: p for p in plugins}
        assert "java" in by_id
        assert "java-library" in by_id
        assert by_id["org.springframework.boot"].version == "3.2.0"
        assert by_id["org.jetbrains.kotlin.jvm"].version == "1.9.22"
        assert by_id["com.example.internal"].applied is False

    def test_legacy_apply_plugin(self):
        text = """
        apply plugin: 'java'
        apply plugin: 'org.springframework.boot'
        apply(plugin = "io.spring.dependency-management")
        """
        ids = {p.id for p in parser.parse_plugins(text)}
        assert "java" in ids
        assert "org.springframework.boot" in ids
        assert "io.spring.dependency-management" in ids

    def test_alias_resolution_from_catalog(self):
        text = """
        plugins {
            alias(libs.plugins.spring.boot)
        }
        """
        catalog_plugins = {"spring-boot": "org.springframework.boot"}
        plugins = parser.parse_plugins(text, catalog_plugins=catalog_plugins)
        assert any(p.id == "org.springframework.boot" for p in plugins)

    def test_no_plugins_block(self):
        assert parser.parse_plugins("// nothing here") == []


class TestDependencies:
    def test_external_single_line(self):
        text = """
        dependencies {
            implementation 'com.google.guava:guava:32.0'
            api "org.apache.commons:commons-lang3:3.14.0"
            testImplementation('org.junit.jupiter:junit-jupiter:5.10.0')
        }
        """
        deps = parser.parse_dependencies(text)
        raws = {(d.configuration, d.raw) for d in deps}
        assert ("implementation", "com.google.guava:guava:32.0") in raws
        assert ("api", "org.apache.commons:commons-lang3:3.14.0") in raws
        assert ("testImplementation", "org.junit.jupiter:junit-jupiter:5.10.0") in raws

    def test_project_dependencies(self):
        text = """
        dependencies {
            api project(':core:utils')
            implementation(project(":web:api"))
        }
        """
        deps = parser.parse_dependencies(text)
        projects = {d.project_path for d in deps if d.is_project}
        assert projects == {":core:utils", ":web:api"}

    def test_platform_dependency(self):
        text = """
        dependencies {
            implementation platform('org.springframework.boot:spring-boot-dependencies:3.2.0')
        }
        """
        deps = parser.parse_dependencies(text)
        assert deps[0].raw == "org.springframework.boot:spring-boot-dependencies:3.2.0"
        assert deps[0].configuration == "implementation"

    def test_catalog_reference_ignored_as_external(self):
        # libs.foo references resolve elsewhere; they must not be mistaken for
        # group:name:version notation.
        text = """
        dependencies {
            implementation libs.guava
            implementation(libs.bundles.web)
        }
        """
        deps = parser.parse_dependencies(text)
        # No external coordinate parsed (raw stays empty / catalog ref kept).
        assert all(d.group is None for d in deps)

    def test_ignores_lines_outside_dependencies_block(self):
        text = """
        repositories {
            implementation 'should:not:parse'
        }
        """
        assert parser.parse_dependencies(text) == []

    def test_map_notation_groovy(self):
        text = """
        dependencies {
            implementation group: 'com.foo', name: 'bar', version: '1.2.3'
        }
        """
        deps = parser.parse_dependencies(text)
        assert deps[0].raw == "com.foo:bar:1.2.3"


class TestGradleProperties:
    def test_basic(self):
        text = "org.gradle.caching=true\n# comment\norg.gradle.parallel = true\nempty=\n"
        props = parser.parse_gradle_properties(text)
        assert props["org.gradle.caching"] == "true"
        assert props["org.gradle.parallel"] == "true"
        assert props["empty"] == ""

    def test_ignores_blank_and_comments(self):
        props = parser.parse_gradle_properties("\n\n  # hi\n! also comment\na=b\n")
        assert props == {"a": "b"}


class TestSettings:
    def test_includes_groovy_and_kotlin(self):
        text = """
        rootProject.name = 'my-monorepo'
        include ':app'
        include ':core:utils', ':core:io'
        include(":web:api")
        """
        includes = parser.parse_settings_includes(text)
        assert ":app" in includes
        assert ":core:utils" in includes
        assert ":core:io" in includes
        assert ":web:api" in includes

    def test_root_project_name(self):
        assert parser.parse_root_project_name("rootProject.name = 'foo'") == "foo"
        assert parser.parse_root_project_name('rootProject.name = "bar"') == "bar"
        assert parser.parse_root_project_name("nothing") is None


class TestWrapper:
    def test_version_from_distribution_url(self):
        text = "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.6-bin.zip\n"
        assert parser.parse_wrapper_version(text) == "8.6"

    def test_version_all_distribution(self):
        text = "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.10.2-all.zip"
        assert parser.parse_wrapper_version(text) == "8.10.2"

    def test_no_version(self):
        assert parser.parse_wrapper_version("foo=bar") is None


class TestVersionCatalog:
    def test_parse_toml(self):
        text = """
        [versions]
        guava = "32.0"
        spring-boot = "3.2.0"

        [libraries]
        guava = { module = "com.google.guava:guava", version.ref = "guava" }
        commons = "org.apache.commons:commons-lang3:3.14.0"

        [plugins]
        spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }

        [bundles]
        web = ["guava", "commons"]
        """
        cat = parser.parse_version_catalog(text, name="libs")
        assert cat.versions["guava"] == "32.0"
        assert cat.libraries["guava"] == "com.google.guava:guava"
        assert cat.libraries["commons"] == "org.apache.commons:commons-lang3:3.14.0"
        assert cat.plugins["spring-boot"] == "org.springframework.boot"
        assert cat.bundles["web"] == ["guava", "commons"]
