"""Tests for JSON, Markdown, and AI report generation."""
import json

from gradlescope.model import BuildFile, Dependency, Module, Plugin, Repo
from gradlescope.report import ai, json_report, markdown_report
from gradlescope.result import build_result


def _result():
    a = Module(
        path=":app",
        directory="/r/app",
        plugins=[Plugin(id="java")],
        languages={"java"},
        dependencies=[Dependency("implementation", raw="g:a:1.+")],
        build_file=BuildFile(path="/r/app/build.gradle", text="plugins { id 'java' }"),
    )
    repo = Repo(root="/r", modules=[a], gradle_version="7.0")
    return build_result(repo, generated_at="2026-01-01T00:00:00")


class TestJsonReport:
    def test_valid_json(self):
        text = json_report.to_json(_result())
        parsed = json.loads(text)
        assert parsed["tool"] == "gradlescope"
        assert parsed["score"]["overall"] <= 100


class TestMarkdownReport:
    def test_contains_key_sections(self):
        md = markdown_report.to_markdown(_result())
        assert "# gradlescope report" in md
        assert "Overall score" in md
        assert "Findings" in md
        assert "configuration-cache" in md

    def test_lists_findings(self):
        md = markdown_report.to_markdown(_result())
        assert "dynamic-versions" in md or "Dynamic dependency versions" in md


class TestAiReport:
    def test_context_is_condensed_and_serializable(self):
        ctx = ai.ai_context(_result())
        json.dumps(ctx)  # must be serializable
        assert ctx["overall_score"] <= 100
        assert "top_findings" in ctx
        assert "category_scores" in ctx

    def test_prompts_target_categories_and_roadmap(self):
        prompts = ai.ai_prompts(_result())
        categories = {p["category"] for p in prompts}
        assert "configuration-cache" in categories
        assert any(p["category"] == "roadmap" for p in prompts)
        # Each prompt has actionable text and references modules where relevant.
        cc = next(p for p in prompts if p["category"] == "configuration-cache")
        assert len(cc["prompt"]) > 50

    def test_ai_markdown_bundles_context_and_prompts(self):
        md = ai.ai_markdown(_result())
        assert "```json" in md
        assert "Prompt" in md
        assert "roadmap" in md.lower()

    def test_prompts_reference_affected_modules(self):
        prompts = ai.ai_prompts(_result())
        dyn = next((p for p in prompts if p["category"] == "dependency-hygiene"), None)
        assert dyn is not None
        assert ":app" in dyn["modules"]

    def test_finding_prompt_has_sections(self):
        result = _result()
        finding = next(f for f in result.findings if f.module_path == ":app")
        prompt = ai.finding_prompt(result, finding)
        for section in ["# Goal", "# Context", "# Problem", "# Locations", "# References", "# Deliverable"]:
            assert section in prompt
        assert ":app" in prompt
        assert finding.rule_id in prompt

    def test_prompts_by_key_covers_all_findings(self):
        result = _result()
        mapping = ai.prompts_by_key(result)
        assert set(mapping) == {f.key for f in result.findings}
        for text in mapping.values():
            assert "# Deliverable" in text
