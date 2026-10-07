# MCM/ICM Summary Sheet content template

> `01_abstract.md` contains only the Summary text; `main.tex` supplies the heading and first-page wrapper. Confirm the current COMAP form and problem-specific requirements before rendering.

## What the first-page Summary must communicate

A fast reader should be able to identify:

1. the decision or phenomenon being modeled;
2. the team's decomposition and why each method fits;
3. the most decision-relevant results, with units and traceable sources;
4. how the results were tested;
5. one important limitation or condition for use.

COMAP's page requirement is authoritative; this repository does not impose a universal word count or a fixed number of results.

## Fillable Summary text

```text
We address {decision/problem} under {important constraints and data scope}. We divide the
problem into {subproblems and dependency}, because {reason the decomposition is useful}.

For {subproblem 1}, we formulate {model and objective} and solve it with {method}. For
{subproblem 2}, we use {upstream result/version} to {purpose}. {Additional method} is used
only where {evidence for the design choice}. We compare the final design with {credible
baseline or alternative}.

The analysis yields {result A, value, unit, reference to table/figure}, {result B}, and
{result C when material}. {Validation method} shows {quantified error/feasibility/robust
range}. The conclusion changes when {failure condition or material assumption}.

These results support {specific decision or interpretation}. They should be recalibrated
when {data, environment, or stakeholder condition} changes.

Keywords: {problem domain}, {core method}, {validation method}, {application}
```

Every number must already exist in the body or a saved result artifact. Do not put an expected improvement, fabricated example, or unverified citation on the Summary Sheet.

## Conditional letter or memo

Create a stakeholder deliverable only if the current problem explicitly asks for one. Put it in the main solution before References and count it inside the official page limit unless the problem states otherwise.

```text
Dear {named role or stakeholder},

{Why this decision matters, in the stakeholder's language.}

Our analysis of {scope and evidence} indicates {plain-language finding}. We recommend:

1. {Action}, because {evidence and expected effect}.
2. {Action}, because {evidence and expected effect}.
3. {Additional action only when supported}.

These recommendations assume {material assumption}. Revisit them if {measurable trigger}
changes, because {affected conclusion}.

Sincerely,
Team #{control number}
```

Use as many recommendations as the evidence supports; the repository does not impose a universal count. Remove formulas and unexplained jargon, but retain the caveat and traceable reasoning.

## Final checks

- [ ] page 1 uses the current Summary Sheet and contains no identity information;
- [ ] the title, problem choice, and control number placeholders are replaced;
- [ ] the Summary agrees with the body, figures, and saved results;
- [ ] no forced claim of novelty appears without a specific implemented difference;
- [ ] any problem-specific deliverable follows the exact current prompt;
- [ ] AI-assisted material and tools are cited/disclosed under the current rules.
