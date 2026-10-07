<!-- SEED v0.3 — flexible structure under the COMAP 2027 rules baseline. -->

# MCM/ICM paper skeleton

> The complete main solution must stay within the current official limit. Under the recorded 2027 baseline, the Summary Sheet, solution, references, optional table of contents, appendices, code, and problem-specific deliverables together are at most 25 pages and use readable type of at least 12pt. Recheck `current_rules.md` every year.

## Workspace contract

| File | Content |
|---|---|
| `01_abstract.md` | Summary Sheet content, no top-level heading |
| `02_problem_restate.md` | context, scope, and tasks |
| `03_analysis.md` | decomposition, dependencies, and technical route |
| `04_assumptions.md` | assumptions, evidence, and affected scope |
| `05_notation.md` | symbols, indices, and units |
| `06_models.md` | formulations, algorithms, results, interpretation, and any required letter/memo before references |
| `07_sensitivity.md` | validation, robustness, and failure conditions |
| `08_evaluation.md` | strengths, limitations, transfer conditions, and conclusion |
| `09_references.md` | verified references and required AI-tool citations |
| `10_appendix.md` | essential reproducibility material within the main-solution limit |
| `11_ai_use_report.md` | Report on Use of AI after the main solution, no top-level heading |

Files `02`–`10` each own a clear top-level Markdown heading. The renderer's MCM template supplies the Summary and AI-report headings and does not emit a table of contents by default.

## Suggested evidence chain

```text
[Summary Sheet — page 1]
  problem → approach → traceable results → validation → limitation

1. Problem Context and Requirements
  scope, data, decision, constraints, requested deliverables

2. Problem Analysis and Technical Route
  subproblems, dependencies, alternatives, evaluation plan

3. Assumptions and Notation
  supported assumptions; unique symbols and units

4. Model Development, Solution, and Results
  formulation → solver → result → validation → interpretation for each task

5. Validation, Sensitivity, and Failure Conditions
  checks selected for the actual model risk

6. Strengths, Limitations, and Conclusions
  evidence-backed claims and conditions for use

[Problem-specific deliverable — only when the current prompt requires it]

References

Appendix / essential reproducibility material

[Report on Use of AI — after the main solution]
```

Section names and ordering may change to fit the problem. Do not preserve an empty section merely because it appears in this skeleton.

## Page-budget decisions

Start from the official total and allocate pages after the solution is known. Protect the Summary Sheet, the main evidence chain, required deliverables, verified references, and enough reproducibility detail to support the claims. A table of contents, long code listing, extra figure, or decorative cover is optional only if the current rules allow it and the team deliberately spends the page budget.

## Stage 9 checks

- [ ] Summary Sheet is page 1 and agrees with the final results;
- [ ] control number and page numbering meet the current instructions;
- [ ] no student, advisor, school, or institution identity appears;
- [ ] main solution, including every counted component, stays within the official page limit;
- [ ] font is readable and at least the current minimum size;
- [ ] every requested letter, memo, or other deliverable is present;
- [ ] every headline value reproduces from saved artifacts;
- [ ] references, data, parameters, and code provide a usable verification path;
- [ ] AI tools are cited/disclosed and the report follows the main solution.
