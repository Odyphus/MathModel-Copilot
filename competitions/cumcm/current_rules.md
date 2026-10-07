# CUMCM current rules baseline

> Last verified: **2026-10-05**. Re-check the official site at Stage 0 every contest year; the official documents always take precedence over this repository.

## Official sources

- [2026 participation rules](https://www.mcm.edu.cn/html_cn/node/9d8e511fe7a1447b35f53a82c908e2e0.html)
- [2026 paper-format specification](https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html)
- [AI-tool policy, 2026 revision](https://www.mcm.edu.cn/html_cn/node/fef94648f2836ab6cc81586f4c38512b.html)

## Submission-critical checks

### Electronic paper

- Submit the paper and supporting materials as two separate electronic files.
- The paper file must be PDF or Word and no larger than 20 MB; PDF is recommended.
- The electronic paper must not include the commitment form or numbering page. Its first page must be the abstract page.
- Use A4 paper with margins of at least 2.5 cm on every side. The repository template uses 12 pt and CTeX defaults as maintainable defaults, not as an official font or line-spacing mandate.
- Do not include a table of contents.
- The main text begins after the abstract page and is limited to 30 pages; appendices follow the main text and are outside that main-text limit.
- Do not expose team-member, school, or regional identity anywhere in the abstract, body, appendix, metadata, or supporting files.

### Supporting-material archive

- Submit one RAR or ZIP archive no larger than 20 MB.
- Include all runnable source code, independently collected data, and any large intermediate results needed to support the paper.
- List the supporting-material files in the paper appendix.
- Do not include the commitment form, numbering page, credentials, API keys, or identity information.

### AI use

- AI may assist, but the team must independently complete the core modeling and analysis and remains responsible for originality, truthfulness, and accuracy.
- Mark AI-generated or AI-assisted content at the corresponding location in the paper.
- List each AI tool in the references with tool name, model/version, developer/company, and use date.
- If AI was used, supporting materials must contain `AI工具使用详情.pdf`, including the tool/version, purpose and stage, key prompts and responses, adopted content, and human modifications.
- If no AI was used, place the required no-AI declaration before the references.

Failure to follow the applicable rules can lead to loss of award eligibility. Treat this file as a checklist, not as a substitute for the official documents.

## Copilot rule lock

The 2026 AI revision takes effect on 2026-09-01. Both use and no-use declarations go before references. Record the main interaction process and typical examples, adoption, human modifications and verification; the rule does not demand every raw dialogue. The pack is a baseline, not a project signoff: lock actual source snapshots through copilot.py rules-lock. Decimal byte limits in pack.json are explicitly maintainer defaults because the official document states MB without defining exact bytes.

The v0.1.2 paper-source chain selects the official declaration generator (`official=True`), with purposes derived from the actual AI ledger. The older generator output is retained only for API compatibility; that wording is not evidence of compliance with the current official sentence. Source snapshots, page placement, details PDF and honest human-review records remain required.
