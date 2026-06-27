"""Tests for the analysis pipeline / result assembly."""
from gradlescope.model import BuildFile, Dependency, Module, Plugin, Repo
from gradlescope.result import AnalysisResult, build_result


def _repo():
    a = Module(
        path=":a",
        directory="/r/a",
        plugins=[Plugin(id="java"), Plugin(id="org.springframework.boot")],
        languages={"java"},
        dependencies=[Dependency("implementation", project_path=":b"), Dependency("implementation", raw="g:a:1.+")],
        build_file=BuildFile(path="/r/a/build.gradle", text="plugins { id 'java' }"),
    )
    b = Module(path=":b", directory="/r/b", plugins=[Plugin(id="java-library")], languages={"kotlin"})
    return Repo(root="/r", modules=[a, b], gradle_version="8.6")


def test_build_result_assembles_everything():
    result = build_result(_repo(), generated_at="2026-01-01T00:00:00", version="9.9.9")
    assert isinstance(result, AnalysisResult)
    assert result.summary["module_count"] == 2
    assert result.summary["gradle_version"] == "8.6"
    assert result.summary["languages"]["java"] == 1
    assert result.summary["languages"]["kotlin"] == 1
    assert result.graph["module_count"] == 2
    assert result.scorecard.total_findings > 0
    assert any(f.rule_id == "dynamic-versions" for f in result.findings)


def test_to_dict_is_json_serializable():
    import json

    result = build_result(_repo(), generated_at="2026-01-01T00:00:00")
    blob = json.dumps(result.to_dict())
    parsed = json.loads(blob)
    assert parsed["tool"] == "gradlescope"
    assert parsed["generated_at"] == "2026-01-01T00:00:00"
    assert parsed["score"]["grade"] in {"A", "B", "C", "D", "F"}
    assert isinstance(parsed["findings"], list)
    assert parsed["summary"]["plugin_usage"]["java"] == 1


def test_plugin_usage_counts_modules():
    result = build_result(_repo(), generated_at="t")
    # java appears in module :a only (b has java-library)
    assert result.summary["plugin_usage"]["java"] == 1
    assert result.summary["plugin_usage"]["java-library"] == 1


def test_has_version_catalog_flag():
    result = build_result(_repo(), generated_at="t")
    assert result.summary["has_version_catalog"] is False
