<!-- SEED v0.2 — maintainer guidance, not a measured winner corpus. -->

# MCM/ICM high-quality submission patterns (SEED v0.2)

> These are review prompts, not COMAP scoring rules or award predictors. The pack has no measured paper corpus. `current_rules.md` and the current problem always take precedence.

## 1. Make the Summary Sheet a result map

State the problem, decomposition, actual methods, decision-relevant results, validation, and one material limitation. Every headline value should point to a body table, figure, equation, or saved result.

## 2. Explain contribution with evidence

Describe what changed relative to a baseline or standard formulation and why it was needed. A well-supported classical method is acceptable; do not manufacture novelty by renaming a model or combining unrelated methods.

## 3. Match validation to model risk

Prediction needs out-of-sample evidence, optimization needs feasibility and baseline checks, simulation needs repeated runs and uncertainty, and sensitive coupled parameters may need joint perturbation. No single sensitivity technique is mandatory for every problem.

## 4. Treat special deliverables as part of the argument

When the current prompt requires a letter, memo, or other artifact, write for its intended reader and preserve the same evidence and caveats as the technical solution. Do not infer a letter requirement from the problem letter alone.

## 5. Connect disciplines only when the problem connects them

An interdisciplinary framing is useful when it adds variables, constraints, mechanisms, or stakeholder trade-offs that alter the analysis. Decorative terminology does not improve the model.

## 6. Preserve a reproducibility path inside the page budget

Identify data provenance, parameter sources, environment, key algorithms, seeds, and an entry command or compact pseudocode. Include only code needed to verify the claims under the current submission rules.

## 7. Write limitations as affected conclusions

For each material limitation, say which result it affects, what evidence revealed it, what alternative could address it, and what new data or computation would be required. Estimate improvement only when an experiment supports the estimate.

## 8. Give every figure a job

A figure should explain data, a mechanism, a result, a comparison, uncertainty, or a failure boundary. Captions define axes/units and state the takeaway; figure counts are not a quality target.

## 9. Compare like with like

Baselines must share the same data, objective, constraints, evaluation window, and units. Report absolute values alongside percentages and explain any trade-off the comparison hides.

## 10. Prefer precise English to promotional English

Use consistent terms and calibrated verbs (`suggests`, `supports`, `demonstrates under...`). Remove unsupported superlatives, verify citations, and make claims no broader than the tested conditions.

Use these patterns to ask better review questions. Do not turn them into fixed section, word, figure, reference, or recommendation counts.
