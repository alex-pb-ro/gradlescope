"""Tests for JVM/language version detection and compatibility mode."""
from gradlescope.model import Module
from gradlescope.scan import parser


class TestParseJvm:
    def test_java_toolchain(self):
        v = parser.parse_jvm_versions("java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }")
        assert v["jvm_toolchain"] == "21"

    def test_source_target_compat_version_enum(self):
        text = "java {\n sourceCompatibility = JavaVersion.VERSION_17\n targetCompatibility = JavaVersion.VERSION_11\n}"
        v = parser.parse_jvm_versions(text)
        assert v["source_compat"] == "17"
        assert v["target_compat"] == "11"

    def test_compat_1_8_normalized(self):
        v = parser.parse_jvm_versions("sourceCompatibility = JavaVersion.VERSION_1_8")
        assert v["source_compat"] == "8"

    def test_compat_string_form(self):
        v = parser.parse_jvm_versions("sourceCompatibility = '17'")
        assert v["source_compat"] == "17"

    def test_kotlin_jvm_toolchain(self):
        v = parser.parse_jvm_versions("kotlin { jvmToolchain(17) }")
        assert v["kotlin_jvm"] == "17"

    def test_kotlin_jvmtarget(self):
        v = parser.parse_jvm_versions('kotlinOptions { jvmTarget = "1.8" }')
        assert v["kotlin_jvm"] == "8"

    def test_kotlin_jvmtarget_enum_legacy(self):
        v = parser.parse_jvm_versions("compilerOptions { jvmTarget.set(JvmTarget.JVM_1_8) }")
        assert v["kotlin_jvm"] == "8"

    def test_kotlin_jvmtarget_enum_modern(self):
        v = parser.parse_jvm_versions("compilerOptions { jvmTarget = JvmTarget.JVM_17 }")
        assert v["kotlin_jvm"] == "17"

    def test_version_with_minor_normalized_to_major(self):
        assert parser.parse_jvm_versions("sourceCompatibility = '11.0'")["source_compat"] == "11"
        assert parser.parse_jvm_versions("sourceCompatibility = JavaVersion.VERSION_11")["source_compat"] == "11"

    def test_none_when_absent(self):
        v = parser.parse_jvm_versions("plugins { id 'java' }")
        assert all(val is None for val in v.values())

    def test_ignores_commented(self):
        v = parser.parse_jvm_versions("// sourceCompatibility = JavaVersion.VERSION_8")
        assert v["source_compat"] is None


class TestModuleVersionProps:
    def test_jvm_version_prefers_toolchain(self):
        m = Module(path=":a", directory="/r/a", jvm_toolchain="21", source_compat="17")
        assert m.jvm_version == "21"

    def test_runs_compat_when_target_older_than_toolchain(self):
        m = Module(path=":a", directory="/r/a", jvm_toolchain="21", target_compat="11")
        assert m.runs_compat is True

    def test_runs_compat_when_compat_without_toolchain(self):
        m = Module(path=":a", directory="/r/a", source_compat="8")
        assert m.runs_compat is True

    def test_no_compat_when_aligned(self):
        m = Module(path=":a", directory="/r/a", jvm_toolchain="17", target_compat="17")
        assert m.runs_compat is False
