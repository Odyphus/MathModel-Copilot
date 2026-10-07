<!-- SEED v0.2 — 16 maintainer checks; not an official COMAP rubric. -->

# MCM/ICM anti-patterns (SEED v0.2)

## A. Summary Sheet

### A1. Summary has no traceable result
**Risk:** it describes activity but gives the reader no conclusion.

**Fix:** include the material results the body actually supports, with units and references to evidence.

### A2. Summary does not fit the current first-page form
**Risk:** a fixed prose template, oversized title, or extra cover displaces required content.

**Fix:** render the current COMAP Summary Sheet and inspect page 1; do not enforce a repository word count.

### A3. Summary disagrees with the body
**Risk:** it cites an abandoned model or a stale numerical run.

**Fix:** trace every method and number to the final result version.

## B. Problem-specific deliverable

### B1. A required letter or memo is written for the wrong reader
**Risk:** unexplained formulas and jargon make the recommendation unusable.

**Fix:** translate the evidence into the stakeholder's decisions while retaining conditions and caveats.

### B2. Recommendations are not supported by the model
**Risk:** action items become generic advocacy.

**Fix:** map each recommendation to a finding, trade-off, and affected stakeholder.

### B3. Deliverable requirements are inferred from A–F
**Risk:** the team adds or omits content based on an old convention.

**Fix:** follow the current problem's explicit deliverables, not a hard-coded problem-letter rule.

## C. Modeling contribution

### C1. A textbook model is renamed without a real change
**Risk:** the contribution claim is misleading.

**Fix:** describe the actual adaptation and baseline evidence, or use the standard name honestly.

### C2. Complexity is added only to sound novel
**Risk:** an unsupported hybrid reduces correctness and interpretability.

**Fix:** keep only components tied to a data pattern, constraint, failure mode, or measured improvement.

## D. Validation and robustness

### D1. Validation method does not match model risk
**Risk:** OAT, cross-validation, or Monte Carlo is applied by habit rather than purpose.

**Fix:** choose checks for leakage, feasibility, stochastic uncertainty, parameter interaction, or the actual failure risk.

### D2. Robustness is shown but not interpreted
**Risk:** plots do not say when the decision changes.

**Fix:** report a meaningful stability range, failure condition, and affected conclusion.

## E. Reproducibility

### E1. Headline results cannot be rerun
**Risk:** no entry command, data path, seed, or saved parameter set connects code to the paper.

**Fix:** provide the smallest complete reproduction path allowed by the page and submission rules.

### E2. Parameter values have no provenance
**Risk:** readers cannot distinguish fitted, assumed, and cited values.

**Fix:** consolidate each material parameter with unit, value, source, and role.

### E3. Data source or license is missing
**Risk:** evidence is unverifiable or unusable.

**Fix:** record dataset name, source, access date, relevant terms, and preprocessing.

## F. Communication

### F1. Figure captions are not self-contained
**Risk:** “Results” does not identify axes, units, scenario, or takeaway.

**Fix:** state what is plotted and what evidence the reader should take from it.

### F2. Terms or units drift across sections
**Risk:** the same symbol or phrase changes meaning.

**Fix:** reconcile the notation table, code columns, figures, and prose.

### F3. English editing changes technical meaning
**Risk:** polishing introduces stronger claims, wrong numbers, or fake citations.

**Fix:** compare the edited version with formulas/results and verify every citation after language review.

## Stage 9 protocol

Derive the total from this file (currently 16). Record each hit with severity, evidence, and disposition. No fixed hit count predicts an award: unresolved high-severity defects block submission; lower-severity items are prioritized by impact and remaining time.
