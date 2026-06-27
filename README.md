# gradlescope

**Analyze, score, and improve Gradle builds in large multi-module monorepos —
build-tool-agnostic, AI-friendly, dashboard-driven.**

gradlescope scans a Gradle repository (hundreds or thousands of modules), builds
its inter-module dependency graph, detects build-health anti-patterns, scores
the build across nine categories, and renders a rich, self-contained HTML
dashboard. It also produces AI/LLM-ready reports and prompts, and computes the
set of modules **affected** by a change so you can stop building everything.

It is designed for messy enterprise repos — mixed Java/Spring Boot (multiple
JDK and Spring Boot versions), Kotlin, Python, and shell — but works on small
repos too.

- **No runtime dependencies.** The core is pure Python standard library, so it
  is safe to run in locked-down CI and trivial to vendor.
- **Self-contained dashboard.** CSS, JS, and charts (inline SVG) are embedded —
  it works from `file://` or behind the built-in server. No CDN, no Develocity.
- **AI-native.** Generates a condensed context pack plus ready-to-paste prompts
  for an LLM or coding agent.

---

## Install

```bash
pip install -e .            # from a checkout
# or, for development:
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Quickstart

```bash
# One-line health summary
gradlescope scan --root /path/to/monorepo

# Scorecard (great for CI gating)
gradlescope score --root /path/to/monorepo --fail-under 80

# Rich multi-page HTML dashboard
gradlescope dashboard --root /path/to/monorepo --out .gradlescope/site --open

# Live dashboard with in-browser "Re-scan" and "Run Gradle" controls
gradlescope serve --root /path/to/monorepo
#  → http://127.0.0.1:8765

# Which modules are affected by a change?
git diff --name-only origin/main... | gradlescope affected --root . --from-stdin

# Generate a ready-to-paste AI prompt to fix one finding
gradlescope prompt --root . --rule dependency-cycles
gradlescope prompt --root . --list      # list finding keys
```

Try it on the bundled example:

```bash
gradlescope dashboard --root examples/sample-monorepo --out /tmp/site --open
```

## What it checks

Findings are grouped into weighted scoring categories:

| Category | Example rules |
| --- | --- |
| configuration-cache | configuration cache disabled, Isolated Projects disabled |
| build-cache | build cache disabled, no remote cache (without Develocity) |
| parallelism | parallel execution disabled |
| dependency-hygiene | dynamic / SNAPSHOT versions, `mavenLocal()`, no version catalog |
| dependency-graph | module cycles, excessive depth, high-fan-in hubs, SDP violations |
| modularity | cross-project config (`allprojects`/`subprojects`), high fan-out |
| toolchains | JVM modules without a Java toolchain |
| portability | legacy `apply from:` script plugins |
| maintainability | outdated/unknown Gradle version |

Each finding links to a **runbook** (bundled, rendered into the dashboard) with
concrete, copy-pasteable fixes — including how to set up a **remote build cache
without Develocity** (Artifactory / S3 / GCS / self-hosted cache node).

Thresholds (graph depth, fan-in/out, minimum Gradle version, …) are tunable via
`--config thresholds.json`.

## Scoring

Every category starts at 100 and loses `weight × severity` per finding; the
overall score is the category-weighted average, so one weak area can't zero out
a healthy build. Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, else F. Best practices
score well precisely because they produce no findings. Per-module scores are
also computed.

## Affected-only builds

`gradlescope affected` maps changed files to modules and returns the changed
modules **plus everything that transitively depends on them**. Build-wide files
(root build, `settings.gradle`, `gradle.properties`, `gradle/`, `buildSrc/`,
`build-logic/`) correctly mark the whole repo as affected. See the
`affected-builds` runbook for wiring it into CI. (Affected analysis requires an
acyclic graph — gradlescope reports cycles that would make it unsound.)

## AI / LLM integration

```bash
gradlescope report --root . --format ai --out ai-handoff.md
```

produces a Markdown bundle containing a JSON **context pack** and one
**actionable prompt per category** (plus a remediation-roadmap prompt). The
dashboard's **AI** page exposes the same with one-click copy buttons. Nothing is
sent anywhere — you paste it into the model of your choice.

## Build-tool-agnostic (optional Bazel migration)

The same disciplines that make Gradle fast also make the build portable: an
explicit acyclic graph, reproducible inputs, pinned toolchains, and no
cross-project configuration. gradlescope scores exactly these, so improving your
score directly de-risks a future Bazel (or other) migration. See the
`bazel-migration` runbook.

## Dashboard pages

- **Overview** — overall gauge + grade, severity donut, category & language
  charts, dependency-graph stats, score trend, top findings.
- **Findings** — full, filterable findings table; each row has a **Prompt**
  button that copies a ready-to-paste AI prompt for that finding.
- **Modules** — per-module scores plus Clean Architecture metrics
  (Ca, Ce, Instability, Abstractness, Distance, zone).
- **Graph** — an interactive Canvas graph (pan/zoom/hover, focus a module's
  upstream/downstream, server-computed layered layout) that scales to thousands
  of nodes with labels drawn on demand so they never overlap.
- **Architecture** — the A/I main-sequence scatter (after Robert C. Martin),
  zone breakdown, and Stable Dependencies Principle violations.
- **Plugins** — every applied plugin classified as core / convention / internal
  / external, with usage counts and version-conflict detection.
- **Processes** — live Gradle jobs (streamed output, persists across refreshes)
  and the running Gradle daemons/processes.
- **Runbooks** — full remediation guides, rendered inline.
- **AI** — context pack and copy-ready prompts.

The **Graph** page offers a flow layout and a numbered **abstraction-layers**
layout, pattern **highlights** (cycles, deep chains, hubs, isolated,
single-consumer, SDP), Ctrl/⌘+scroll zoom, and overlay zoom/fit/reset controls.
A global **status bar** on every page shows score/modules/findings and live
process state (click for running jobs + a Stop control).

When served with `gradlescope serve`, the toolbar can re-scan the repo and
launch a Gradle task in-browser as a tracked background **job** whose output
streams to the Processes page (with per-log search, "open log on disk", and
cancel; a system-performance header shows CPU/load/memory). Tasks are validated
against a strict flag allowlist; the server binds to localhost and never uses a
shell.

## Output location

gradlescope never writes into the analyzed repository. By default the dashboard,
score history, and job logs are written under a per-repo workspace at
`~/.gradlescope/repos/<repo>-<hash>/` (override the base with the
`GRADLESCOPE_HOME` env var, or pick an explicit `--out` directory).

## Clean Architecture metrics

For every module gradlescope computes the component metrics from *Clean
Architecture*: afferent/efferent coupling (Ca/Ce), **Instability** `I = Ce/(Ca+Ce)`,
**Abstractness** `A` (abstract types / total types, from a source scan), and
**Distance from the main sequence** `D = |A + I - 1|`. It flags Stable
Dependencies Principle violations (depending on less-stable modules) and the
"zone of pain" / "zone of uselessness".

## Architecture

```
src/gradlescope/
  model.py            # dataclasses: Module, Dependency, Plugin, Repo, Finding…
  scan/               # heuristic parsing + module discovery
  graph/              # dependency graph, metrics, cycles, affected analysis
  analysis/           # rule framework, rules, scoring
  report/             # JSON / Markdown / AI reports
  dashboard/          # SVG charts, HTML, runbook renderer, multi-page site
  server/             # localhost server: serve + re-scan + run
  runbooks/           # bundled Markdown runbooks
  cli.py              # the `gradlescope` command
```

## Development

```bash
pip install -e ".[dev]"
pytest                                   # run the suite
pytest --cov=gradlescope --cov-report=term-missing   # with coverage (>90%)
```

The project is built test-first; every module has unit tests and coverage is
kept above 90%.

## License

Apache-2.0. See [LICENSE](LICENSE).
