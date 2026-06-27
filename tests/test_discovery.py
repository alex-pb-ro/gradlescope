"""Tests for module discovery and full-repo scanning."""
import os

from gradlescope.scan import discovery, scan_repo


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_gradle_path_to_dir():
    assert discovery.gradle_path_to_dir("/r", ":core:utils") == os.path.join("/r", "core", "utils")
    assert discovery.gradle_path_to_dir("/r", ":app") == os.path.join("/r", "app")


def _make_repo(root):
    _write(
        os.path.join(root, "settings.gradle"),
        "rootProject.name = 'demo'\ninclude ':app'\ninclude ':core:utils'\n",
    )
    _write(
        os.path.join(root, "gradle.properties"),
        "org.gradle.caching=true\norg.gradle.parallel=true\n",
    )
    _write(
        os.path.join(root, "build.gradle"),
        "plugins { id 'java' }\nallprojects { }\n",
    )
    _write(
        os.path.join(root, "gradle", "wrapper", "gradle-wrapper.properties"),
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.6-bin.zip\n",
    )
    _write(
        os.path.join(root, "gradle", "libs.versions.toml"),
        '[plugins]\nspring-boot = { id = "org.springframework.boot", version.ref = "sb" }\n'
        '[versions]\nsb = "3.2.0"\n',
    )
    _write(
        os.path.join(root, "app", "build.gradle"),
        "plugins {\n alias(libs.plugins.spring.boot)\n}\n"
        "dependencies {\n implementation project(':core:utils')\n"
        " implementation 'com.google.guava:guava:32.0'\n}\n",
    )
    _write(os.path.join(root, "app", "src", "main", "java", "A.java"), "class A {}")
    _write(
        os.path.join(root, "core", "utils", "build.gradle"),
        "plugins { id 'java-library' }\n",
    )
    _write(os.path.join(root, "core", "utils", "src", "main", "kotlin", "B.kt"), "class B")


def test_scan_repo_discovers_modules(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)

    assert repo.gradle_version == "8.6"
    assert repo.gradle_properties["org.gradle.caching"] == "true"
    assert repo.module_count == 2
    paths = {m.path for m in repo.modules}
    assert paths == {":app", ":core:utils"}


def test_scan_repo_resolves_plugin_alias(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)
    app = repo.module_by_path(":app")
    assert app.has_plugin("org.springframework.boot")


def test_scan_repo_parses_project_and_external_deps(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)
    app = repo.module_by_path(":app")
    assert any(d.project_path == ":core:utils" for d in app.dependencies)
    assert any(d.raw == "com.google.guava:guava:32.0" for d in app.dependencies)


def test_scan_repo_detects_languages(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)
    assert repo.module_by_path(":app").languages == {"java"}
    assert repo.module_by_path(":core:utils").languages == {"kotlin"}


def test_scan_repo_reads_version_catalog(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)
    assert repo.version_catalogs
    assert repo.version_catalogs[0].plugins["spring-boot"] == "org.springframework.boot"


def test_scan_repo_root_build_file(tmp_path):
    root = str(tmp_path)
    _make_repo(root)
    repo = scan_repo(root)
    assert repo.root_build_file is not None
    assert "allprojects" in repo.root_build_file.text


def test_kotlin_settings_supported(tmp_path):
    root = str(tmp_path)
    _write(
        os.path.join(root, "settings.gradle.kts"),
        'rootProject.name = "k"\ninclude(":lib")\n',
    )
    _write(os.path.join(root, "lib", "build.gradle.kts"), "plugins { `java-library` }\n")
    repo = scan_repo(root)
    assert repo.module_by_path(":lib") is not None
    assert repo.module_by_path(":lib").build_file.is_kotlin


def test_fallback_discovery_without_settings(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "build.gradle"), "plugins { id 'base' }")
    _write(os.path.join(root, "svc", "build.gradle"), "plugins { id 'java' }")
    repo = scan_repo(root)
    assert repo.module_by_path(":svc") is not None


def test_missing_build_file_module_still_created(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "settings.gradle"), "include ':ghost'\n")
    repo = scan_repo(root)
    ghost = repo.module_by_path(":ghost")
    assert ghost is not None
    assert ghost.build_file is None
