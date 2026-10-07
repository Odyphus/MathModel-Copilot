# Fresh historical case manuscripts

These builders retain the existing canonical Runtime and document-source gate. They do not certify arbitrary Word documents and do not create a PDF receipt or a human signoff merely by writing a file. The source subset includes paragraphs, explicit headings, tables, embedded images, a named simple native OMML fraction, and code bound to a current CodeManifest.

For an already newly executed MCM project:

```bash
export MATHMODEL_PAPER_PROJECT=/absolute/path/to/mcm-traffic-new
python examples/v020_paper/mcm_prepare.py
```

On PowerShell use `$env:MATHMODEL_PAPER_PROJECT = (Resolve-Path ../mcm-traffic-new).Path`. The English manuscript has a summary sheet, an engineer-facing double-spaced technical summary, model and control definitions, current result table, sensitivity interpretation, limitations, source note and final AI report. Bound source code remains in the workspace; the CUMCM manuscript also exercises native code appendices. The MCM manuscript is historical, without an invented team control number. Formula token/source equality and model validation are different checks.

For a fresh complete CUMCM case, obtain the official 2018 B PDF, appendix PDF and four empty XLS workbooks separately from the [official archive](https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html). The asset directory also requires the retained `official_parameters.json` transcription. Source material rights are separate from source-code rights; do not assume contest files can be publicly redistributed.

```bash
python examples/v020_paper/run_cumcm.py --assets-dir /path/to/official-assets --workspace ../cumcm-new
export MATHMODEL_PAPER_PROJECT=/absolute/path/to/cumcm-new
export MATHMODEL_RULE_SNAPSHOTS=/path/to/actually-fetched-cumcm-rule-snapshots
python examples/v020_paper/cumcm_prepare.py
python examples/v020_paper/build_documents.py
```

The CUMCM source builder reuses the earlier historical-paper builder with explicit workspace paths and adds a native efficiency fraction. It binds new Result IDs; it does not copy authority, claims, old numeric results or old rendering receipts. Rule snapshots must include their actual `fetch-record.json`; official rules and their dates must be checked separately.

After generation, use an actual Word or LibreOffice conversion with a separate profile and record the precise source/PDF hashes, process result and version. Render all PDF pages to PNG and inspect them. The product's `copilot_paper_source.audit_paper_source` compares the actual DOCX to registered sources; `copilot_document_checks` handles structural/derivative checks. Neither alone proves that a PDF was rendered or that a person reviewed it.

TeX is a separate path: these DOCX examples do not certify a pure TeX source-to-submission chain. Unsupported `w:sym`, dynamic fields in source-controlled body text and unsupported drawings still fail explicitly. Do not flatten or discard them to manufacture a pass.

Builders create or version authoring objects in their designated new workspace. Preserve a completed evidence workspace; use a fresh run for future manuscript experiments. Re-running a builder is not an idempotent regeneration of a signed final release.
