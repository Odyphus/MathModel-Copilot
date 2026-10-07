# Repository instructions

This repository contains the `mathmodel-skill` product. When working inside this repository, act as a maintainer: do not start the ten-stage contest workflow merely because modeling-related files are present.

## Sources of truth

- `SKILL.md` defines runtime behavior and trigger boundaries.
- `references/stage_00_kickoff.md` through `references/stage_09_review.md` contain stage details and must be loaded lazily at runtime.
- `competitions/<competition>/` contains competition-specific rules, heuristics, overlays, and paper structures.
- `templates/shared/decision_log.json` is the canonical persistent-state template.
- `docs/PRODUCT_LANGUAGE.md` is the canonical user-facing terminology guide. Use 建模工作台, 建模意见, 项目进展简报 and 使用反馈 for their distinct purposes; preserve internal identifiers and the evidence boundaries of each status.
- `.codex-plugin/plugin.json`, `agents/openai.yaml`, and `skills/mathmodel-copilot/SKILL.md` are packaging metadata or thin discovery shims. Do not duplicate the workflow into them.

## Maintenance rules

- Preserve the trigger boundary: this skill is for CUMCM, MCM/ICM, and Diangong Cup contest work, not generic data analysis or ordinary paper review.
- Treat official contest rules as time-sensitive. Keep a verification date and primary source in `competitions/<competition>/current_rules.md`; official current-year material always overrides repository guidance.
- Treat empirical distributions and `winning_patterns.md` as observations or maintainer heuristics, never official thresholds or award predictors.
- Keep user artifacts relative to the user's working directory (`state/`, `results/`, `figures/`, `paper_workspace/`, `paper_output/`). Resolve repository resources relative to the installed skill root.
- Keep `SKILL.md` concise and dispatch stage-specific detail into `references/`.
- Do not add runtime claims about awards, token savings, or elapsed time without a reproducible benchmark.
- When changing behavior, update the README, tests, plugin version, state schema, and relevant competition docs together.
- README visuals in `assets/` are original SVGs. Keep their version, stage names, and example data consistent with `SKILL.md` and `scripts/status.py` when those change.
- Do not vendor or reintroduce templates, examples, papers, or binary assets without a clear redistribution license. Keep runtime dependencies and external-source boundaries accurate in `THIRD_PARTY_NOTICES.md`.

## Verification

Run the checks proportionate to the change. Before a release, run all of them:

```bash
python -m compileall -q scripts templates/shared/code_starter
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/doctor.py --competition cumcm --skip-tools
python scripts/doctor.py --competition mcm --skip-tools
python scripts/doctor.py --competition diangong --skip-tools
git diff --check
```

Maintainers with the Codex skill/plugin creator tooling installed should also run its current `quick_validate.py` and `validate_plugin.py` entrypoints. Do not hard-code a machine-specific installation path into contributor commands.

Runtime evaluation prompts should explicitly invoke `$mathmodel-copilot`. Negative-trigger tests should confirm that generic model-selection and non-competition writing requests do not invoke it. The old name is available only through the explicit compatibility installer.

## Copilot v0.1 canonical state

The sole authority is project/state/decision_log.json, schema 4.0, copilot 0.1. All mutations use Store transactions; do not call a legacy .cumcm writer or directly rewrite JSON. Domain objects and journal history are immutable; new versions cause dependent invalidation. Follow references/copilot_runtime.md for all inherited Stage write examples. Stage/score/compliance booleans never establish execution or readiness. Run all tests and the three inherited doctor checks, and preserve explicit unexecuted external-tool limits.

v0.1.2 source/display/document contracts and validation-observation boundaries are documented in docs/DECISIONS_V012.md. Object-check reuse must never survive a public observation or become a revision-based file cache; same-revision disk drift must still be rechecked on the next call.

RC4 adds optional copilot.feedback through the same Store. User text and request provenance are immutable; only permitted receipt lifecycle transitions may update replies. Feedback, AI completion, adopted decisions and mathematical verification are distinct. Context must derive reply freshness from its recorded revision observation. Dashboard remains read-only by default; opt-in interactions never run arbitrary browser-supplied commands or silently replay interrupted AI work. Preserve a single discoverable SKILL.md in the runtime distribution.

Preview adds versioned Ambiguity, Assumption and downstream AssumptionValidation objects within the same Store. Interpretation review is a recorded choice, not authenticated human approval or scientific validation. A validated assumption requires current real results and the predeclared checks; stale sources invalidate dependent contracts and results. Legacy Stage text cannot substitute for these records. Preserve the root schema 4.0 compatibility and test both Runtime entry points and Store-level invariants.

Completion reports must be live projections of the authority and its checked files. Never ingest an external report's PASS, revision, claimed user choice or numbers as verified state. Dashboard labels and units come from explicit model output declarations, not guessed metric names. A source binding is not a semantic or units proof. RunRecord.git_commit is an observed repository HEAD (or empty), while code_manifest_id/hash identify the actual registered code; recorded installed library versions do not prove environment lock compliance or deterministic results.
