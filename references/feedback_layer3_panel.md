> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。

# Feedback Layer 3 — independent final-review panel

> Run once in Stage 9, after the official-rule compliance gate passes. The panel finds independent failure modes; it does not predict awards.

## Why use a panel

A single reviewer can become anchored to its own earlier scores. L3 asks several isolated reviewers to inspect different evidence, then maps every concern back to a specific section. The objective is a safer final submission, not a simulated ranking.

The active personas come from `competitions/<competition>/rubric_overlay.json["panel_personas"]`. Their labels and weights are competition-specific, while the output schema and aggregation rules below stay the same.

## Preconditions

Do not start the panel until all of the following are true:

- the current official rules have been reopened and recorded;
- page/font/file/anonymity checks pass;
- the intended PDF and supporting-material manifest exist;
- the AI ledger is explicitly resolved and the required disclosure artifact exists;
- no known high-severity consistency defect is being hidden from reviewers.

Compliance failures are handled by Stage 9 and remain `block`; a high panel score cannot override them.

## Reviewer isolation

Prefer one fresh context per persona and run independent reviews in parallel when the harness supports it. Each reviewer receives only:

1. its persona `id`, `focus`, and competition context;
2. the final PDF or the sections needed for that focus;
3. the current official constraints relevant to its review;
4. the JSON schema below.

Do not show a reviewer other panel outputs, previous scores, claimed award levels, or the team's preferred verdict. If isolated contexts are unavailable, run the reviews serially but clear the reviewer-specific conversation state between them.

## Shared output schema

Every reviewer returns exactly one JSON object:

```json
{
  "panelist": "math_rigor",
  "scores": {
    "1_focus_dimension": {"score": 8, "evidence": "§5.2 equation (12)"},
    "2_focus_dimension": {"score": 7, "evidence": "Figure 6 caption"},
    "3_focus_dimension": {"score": 9, "evidence": "Appendix A test"},
    "4_focus_dimension": {"score": 8, "evidence": "§6 Table 4"},
    "5_focus_dimension": {"score": 8, "evidence": "Notation table"}
  },
  "issues": [
    {
      "severity": "high",
      "where": "§5.2 equation (12)",
      "evidence": "The stated unit is kW but the expression returns kWh.",
      "fix": "Insert the time-step multiplier and recompute Table 4."
    }
  ],
  "verdict": "ready"
}
```

Rules:

- exactly five scored dimensions, each from 1 to 10;
- evidence points to the PDF, result file, code, or rule being checked;
- at most three issues, each with `high`, `medium`, or `low` severity;
- verdict is only `ready`, `refine`, or `block`;
- `block` means an unresolved defect could invalidate correctness, reproducibility, anonymity, or submission compliance;
- no award tier, percentile, or acceptance prediction.

The orchestrator recomputes each verdict from scores and issues. A model-provided optimistic verdict is never trusted as-is.

## Persona guidance

### Mathematical rigor

Inspect formulation, units, boundary conditions, derivation steps, identifiability, solver assumptions, and agreement between notation and equations. Do not penalize a simple model merely for being simple; penalize an unjustified or incorrectly solved model.

### Modeling contribution

Ask whether each design choice is necessary, supported, and compared with a credible alternative or baseline. A renamed textbook method is not a contribution, while a well-justified standard method may be entirely appropriate. Do not reward gratuitous hybrids.

### Code and reproducibility

Check entry commands, dependency assumptions, seeds, data paths, train/test leakage, feasibility and boundary checks, saved outputs, and whether headline numbers reproduce. Ignore cosmetic code style unless it obstructs verification.

### Communication and visual evidence

Check whether a fast reader can identify the problem, method, quantified result, validation, and limitation; whether figures/tables are readable and cited; and whether claims match the evidence. Do not enforce a fixed paragraph, figure, formula, or citation count.

### Competition-specific reader

Use the fifth persona from the active overlay: CUMCM fast-read clarity, MCM stakeholder communication when required, or Diangong engineering feasibility. For an MCM problem without a policy letter/memo, replace the `policy` persona with an independent reproducibility reader at weight `1.0`.

## Aggregation

For reviewer `p`:

```text
panel_mean(p) = mean(the five dimension scores)
```

For the panel:

```text
weighted_mean = sum(panel_mean(p) * persona_weight(p)) / sum(persona_weight(p))
raw_min       = minimum of all dimension scores
```

Deterministic verdict, in priority order:

1. any unresolved high-severity issue → `block`;
2. otherwise `raw_min < 7` or `weighted_mean < 8` → `refine`;
3. otherwise → `ready`.

Weights may prioritize a relevant perspective, but cannot hide the raw minimum or a high-severity issue.

Persist:

```json
{
  "panel_v1": {
    "math_rigor": {},
    "modeling_contribution": {},
    "code_reproducibility": {},
    "communication": {},
    "competition_reader": {}
  },
  "aggregate_v1": {
    "raw_min": 7,
    "weighted_mean": 8.1,
    "verdict": "refine",
    "bottleneck": "§5.2 equation (12)"
  },
  "redo_actions": [],
  "panel_v2": {}
}
```

## Targeted revision

Deduplicate issues that point to the same source defect, then sort by severity and downstream impact. Map each accepted issue to the smallest responsible artifact:

| Concern | Default target |
|---|---|
| formulation, solver, result mismatch | Stage 5 model/code/result files |
| sensitivity or failure boundary | Stage 6 |
| unsupported strength, limitation, or transfer claim | Stage 7 |
| abstract, prose, figure, reference, or appendix assembly | Stage 8 |
| page, anonymity, disclosure, or submission package | Stage 9 compliance gate |

Apply section-level patches where safe. Recompute any downstream value affected by a mathematical or code change; do not patch prose around a wrong result.

Run at most one focused second panel on the affected personas and sections. A second pass verifies the fix rather than restarting an open-ended optimization loop.

## Final handoff

- `ready`: hand back the submission package only if the Stage 9 compliance gate is also green;
- `refine`: keep `submission_ready=false`, apply the accepted targeted fixes, and rerun affected checks;
- `block`: stop and surface the exact correctness or compliance defect to the team.

Time pressure may change which optional improvement the team attempts, but it does not turn a known rule violation or invalid result into `ready`.
