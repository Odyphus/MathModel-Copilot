# MCM/ICM competition pack

> The official current-year instructions and problem statement are authoritative. This pack separates a verified rules baseline from maintainer-authored writing and review guidance.

| Field | Repository baseline |
|---|---|
| Code | `mcm` |
| Contest | COMAP Mathematical Contest in Modeling / Interdisciplinary Contest in Modeling |
| Working language | English |
| Renderer | pdfLaTeX with `templates/latex/mcm/main.tex` |
| Problem family | A–C (MCM), D–F (ICM) |
| State of evidence pack | maintainer guidance v0.2; empirical corpus `n=0` |
| Rules baseline | COMAP 2027, verified 2026-07-22; see `current_rules.md` |

## Submission-critical baseline

The current recorded instructions require a complete main solution of no more than 25 pages, readable type of at least 12 points, English, no personal or institutional identity, and the Summary Sheet on page 1. The page count includes references, appendices, code, a table of contents if used, and problem-specific deliverables. A `Report on Use of AI` follows the main solution and is excluded from that 25-page limit.

Reopen the official link in `current_rules.md` during Stages 0, 8, and 9. Never let this README, the template, or a maintainer heuristic override the current instructions.

## Product differences from the CUMCM branch

- The Summary Sheet is the first page; the template does not add a separate decorative cover or default table of contents.
- A letter, memo, or stakeholder brief is included only when the current problem explicitly requires it. Problem letters are not inferred from the letter A–F alone.
- Communication is reviewed independently from mathematical correctness: a figure or paragraph must make its evidence legible, not merely look polished.
- Modeling contribution is judged by necessity, comparison, and evidence. A standard method that fits the problem is preferable to an unsupported hybrid.
- All main-solution material must fit the official page budget; essential reproducibility information is prioritized over long code dumps.
- AI tools are cited/disclosed in the main solution as required, and the separate report is generated from the shared ledger.

## Files

| File | Role | Status |
|---|---|---|
| `current_rules.md` | official links and submission-critical baseline | verified baseline |
| `topic_specs.json` | A–F routing hints | seed |
| `rubric_overlay.json` | MCM-specific Stage 8 dimensions and panel personas | maintainer rubric |
| `empirical.json` / `empirical_notes.md` | explicit `n=0` evidence gap | seed, no numeric thresholds |
| `winning_patterns.md` | evidence-chain writing guidance | seed |
| `phrase_bank.md` | optional English phrasing prompts | seed |
| `anti_patterns.md` | 16 maintainers' final-review checks | seed |
| `abstract_template.md` | Summary Sheet and conditional deliverable content templates | seed |
| `paper_skeleton.md` | a replaceable structure within the 25-page main solution | seed |

This pack does not claim to represent Outstanding Winner statistics and must not be used to predict an award.
