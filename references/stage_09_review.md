---
stage: 9
name: review
duration_h: 2-6
inputs: ["paper.tex", "paper.pdf", "decision_log_full", "decision_log.competition"]
outputs:
  - "stage.9.{anti_patterns_check, compliance_checks, panel_scores, weakest_section, redo_log, red_team_record, final_pdf_path, submission_ready}"
loads_reference:
  - "competitions/<comp>/current_rules.md"
  - "competitions/<comp>/anti_patterns.md"
  - "competitions/<comp>/rubric_overlay.json"
  - "references/feedback_layer3_panel.md"
loads_template: ["templates/latex/<comp>/"]
feedback: ["L1", "L3_panel", "red_team_in_championship"]
next: SUBMIT
---

> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。


# Stage 9 — Submission review

The final gate is compliance first, content consistency second, presentation third. A polished paper that violates the current rules is not submission-ready.

## 1. Re-open the official rules

Read `competitions/<comp>/current_rules.md`, open its official links, and compare the final artifacts against the current contest year. Record the check in `decision_log.stages.9.compliance_checks`.

Minimum branches:

### CUMCM

- electronic paper starts with the abstract page;
- no commitment form, numbering page, table of contents, or identity information;
- main text and file size meet the current limits;
- appendix lists the supporting-material files;
- support ZIP/RAR contains runnable code and required evidence, is within the size limit, and excludes secrets;
- AI-assisted content is marked and cited;
- if AI was used, support materials contain `AI工具使用详情.pdf`; otherwise the required no-AI declaration is present.

### MCM/ICM

- Summary Sheet is page 1;
- main solution, including references, appendices, code, TOC, and required letter/memo, is at most 25 pages;
- readable font is at least 12pt;
- each solution page has the control number and page number, with no personal or institutional identity;
- AI tools are cited in the main solution;
- `Report on Use of AI` follows the main solution and is not counted inside the 25-page solution.

### Diangong

- page 1 is the anonymous cover with registration number and the official problem title; page 2 contains title, abstract and keywords and begins Arabic page numbering at 1;
- the body begins on page 3, contains no table of contents and stays within the current 25-page body limit; appendices follow the body;
- A4 margins are 2.5 cm and Chinese body text uses 小四; no team-member or school identity appears anywhere;
- the paper is a single uncompressed PDF or Word file, while support materials are ZIP/RAR no larger than 20 MB and contain the runnable code and necessary evidence;
- citations appear in the text and references follow citation order;
- the currently checked official pages do not define a dedicated AI-disclosure format, so recheck the annual notice and preserve the ledger rather than inventing one.

Any unresolved rule violation sets `submission_ready=false` and yields `block`.

## 2. Run the active anti-pattern checklist

Read `competitions/<comp>/anti_patterns.md` and derive the count from the active file rather than copying a remembered or example count.

These are maintainer heuristics, not official scoring weights. Fix high-severity hits; record accepted medium-risk items with an explicit rationale.

## 3. Verify the evidence chain

Cross-check the final paper against `decision_log.json` and the saved artifacts:

- no abandoned model remains in the abstract or conclusion;
- no symbol changes meaning between sections;
- all headline values reproduce from stored results;
- every figure/table path resolves and its caption matches the content;
- every external claim has a verified source;
- AI-generated citations have been opened and checked manually.

## 4. Review presentation

- labels, units, legends, equations, and captions remain readable at final PDF size;
- fonts and colors are consistent and accessible;
- tables use consistent units and precision;
- there are no unresolved `??` references, missing glyphs, clipped figures, or large overfull boxes;
- all required sections are present in the compiled PDF, not merely on disk as detached `.tex` files.

## 5. Run the five-view panel

Use `references/feedback_layer3_panel.md` as the single source for panel roles and aggregation. Prefer independent parallel views when the harness supports them; otherwise run the views separately to reduce cross-contamination.

Map every high-severity concern back to one source section and apply a targeted patch. Re-run only the affected checks and panel views. Do not ask the panel to predict an award; use `ready`, `refine`, or `block` against the repository rubric.

## 6. Generate AI disclosure artifacts

For CUMCM or MCM, run from the user project root:

```bash
python <skill>/scripts/render_ai_usage.py \
  --competition <competition> \
  --decision-log state/decision_log.json \
  --paper-workspace paper_workspace/ \
  --support-dir support_materials/
```

For CUMCM with AI use, verify `support_materials/AI工具使用详情.pdf` is in the supporting archive and that inline marks and AI-tool references are present. For an explicit empty CUMCM ledger, the helper instead creates `paper_workspace/AI工具未使用声明.md`; rerender and verify that the declaration appears immediately before the references, with no details PDF. For MCM, verify `paper_workspace/11_ai_use_report.md` is rendered once, after the 25-page main solution. The helper intentionally does not invent a Diangong disclosure format; for Diangong, compare the ledger with the current official notice and record that manual check.

## 7. Compile and inspect the final PDF

Use `<skill>/scripts/render_paper.py` or the selected LaTeX engine. Compilation succeeds only when the PDF exists, includes all intended sections, and has no unresolved high-severity warnings. Visually inspect the first page, dense equations, wide tables, figure-heavy pages, references, appendices, and the AI report.

## 8. Persist the final gate

Write actual runtime-derived counts and paths. The schema is:

```json
{
  "anti_patterns_check": {
    "total": null,
    "passed": null,
    "fixed": null,
    "deferred": null
  },
  "compliance_checks": {
    "rules_verified": null,
    "anonymity_passed": null,
    "page_limit_passed": null,
    "ai_disclosure_passed": null
  },
  "final_pdf_path": "paper_output/paper.pdf",
  "submission_ready": null
}
```

The `null` values above are schema placeholders only. Replace every one with an observed count or verified boolean before persisting Stage 9; never copy a sample result into the final gate.

## Exit conditions

- current official rules verified with no unresolved violation;
- anti-pattern and consistency checks completed;
- all high-severity panel findings resolved;
- PDF compiled and visually inspected;
- AI disclosure and supporting materials complete when required;
- `copilot.py status` 的 version-bound `submission.ready == true`；旧 Stage 布尔不参与证明.

Only then hand the final submission package back to the team.
