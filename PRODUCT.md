# MathModel Copilot

## Product language

Canonical Chinese names and state meanings live in [产品术语与文案规范](docs/PRODUCT_LANGUAGE.md). The Dashboard is 建模工作台. 建模意见 discusses the current problem with AI; 使用反馈 reports product experience to the developer through an independent, explicitly authorized draft and sending flow. 项目进展简报 shares a current observation, while 任务交接说明 supports continuing a specific task. Retain exact internal identifiers and historical evidence; a wording change does not introduce new capabilities or certify release readiness.

## Product truth

A local workspace for mathematical modeling. The versioned Core owns requirements, contracts, execution, validation, evidence, writing and delivery. The Dashboard defaults to read-only; an opt-in local interaction component records user opinions and separate analysis receipts through the same Store. Its immediate user is a Chinese-speaking student working with AI on the project recorded on this computer. Humans own the paper's reasoning and final text; AI assists with evidence, critique and explicitly requested local drafting.

The first task is to understand progress, useful outcomes, outstanding problems and the next step. The primary destinations are 项目总览、各问进展、成果与依据、论文准备. The overview contains per-question progress, next work, major results, outstanding issues and paper preparation only when there are meaningful records. Requirements and the currently selected model belong with each question; actual human confirmation needs are prioritized. Important changes show their effect when current records require rechecking. Empty optional panels disappear. Preview 2 adds a local unread-change summary and structured interpretation decisions with recorded alternatives and impact; a browser read marker never means team receipt, adoption or verification.

## Decisions from the content discussion

The user requested plain Chinese, no visible hashes or opaque IDs in ordinary pages, and a purpose-led local workbench before expanding cloud collaboration. The user authorized implementation with “可以，那你修改一下吧”. This authorizes implementation of the discussed direction; it is not a claim of visual approval or acceptance of the finished UI.

The Dashboard shows this computer's recorded project state. Refresh does not learn what another team member has done elsewhere. Existing optional Git proposals and checked adoption remain available outside the read-only UI. No cloud accounts, remote upload, automatic merge or team synchronization are added. Data remains under the existing sole authority.

## Presentation and trust

Chinese task-oriented names replace raw object names. Ordinary pages do not show project UUIDs, revision counters, hash strings or run IDs. Internal references remain exact in memory and in optional downloadable diagnostic records. Source text and full numeric result data are explicitly requested, labeled original material; unknown English content is not invented or silently discarded. Required unknown blocker reasons retain an expandable original explanation.

Requirement verification, successful execution, independent result checks, paper source checks and submission readiness remain distinct. No stage-derived percentage or overall readiness score. A historical audit cannot establish formal readiness. Superseded versions do not automatically become current work blockers. Refresh preserves reading with an explicit previous-observation notice until the new check completes. Same-revision file drift is checked. Failed refresh removes old current facts.

Preview exposes a number's declared meaning/unit and current run/check evidence on demand, reusing the existing result drawer. Missing or conflicting declarations remain explicit; field names never imply scientific units. Decisions show the recorded choice and reason without treating the actor label as authenticated human approval. The new factual Markdown report reads the same live projection and creates a new file; it cannot grant completion from external prose or overwrite earlier evidence.

The modeling conversation begins with the whole problem and then compares genuinely useful candidates per question. Explanations stay readable while naming the mathematical model, its variables/constraints, the solution algorithm and intended verification. One sound model may be preferable to artificial alternatives. Humans own substantive tradeoffs; routine authorized work proceeds without repeated stage approvals. Interpretation and assumption choices enter the same versioned authority, and adopting an assumption remains distinct from checking it against actual results.

## Design and implementation

Feature discovery follows [功能发现与首次体验](references/feature_guidance.md): introduce the workflow briefly on first full use, then offer relevant capabilities in context without a mandatory tour. Once the real project is initialized, the agent should start and attempt to show the packaged read-only workbench when the host supports it and the user has not declined. A scoped question does not trigger project setup or a viewer. The CLI itself does not open a browser. Version 0.3 adds a private schema-1 experience store, persistent explicit preferences, a shared tutorial catalog, timely selected events, generated Markdown recaps and fresh-authority resumption. The original authority schema is unchanged. Instructions invoke these functions during normal Skill execution; this is not an always-on daemon or proof of every host following the lifecycle. Cross-project lessons are opt-in, tag-matched, conditional and source-checked. The browser keeps its own first-use display preference; manual tutorial remains available independently.

Retain the researched original warm-white / forest-green design, flat ruled rows, restrained status colors and native Chinese sans typography. Mobbin research belongs to the earlier v0.2 design phase: eight actual authenticated reads, 28 distinct previews, 12 deeper inspections, recorded in the existing separate design evidence. This content revision does not claim a new research round or copy third-party assets.

Vanilla HTML/CSS/JavaScript and an optional standard-library Python loopback server. No frontend build or account is required for local views or feedback. Reuse the existing shell, data module and styles; interaction.js adds one bounded component. The opt-in API accepts only note, ask and cancel, with origin/session validation, revision checks and exact retry deduplication. It cannot edit arbitrary files, run user-supplied commands or bypass evidence gates. A separately configured CLI adapter starts fresh read-only analysis; it does not take over the desktop chat. Business facts stay in the original authority; browser storage holds only drafts and exact retry payloads.

## Acceptance

All active questions and requirements must remain discoverable; requirement counts never deduplicate semantically similar requirements. Current model, task prerequisite, output, source and consumer links remain navigable. Details distinguish generated, executed, verified and stale records. Default screens use Chinese descriptions and contain no opaque identifiers. Meaningful empty, unknown, failure and historical states are tested alongside the real local project. Desktop and narrow/mobile layouts, explicit local scope, file reads and unchanged authority are verified. External software, cloud collaboration and human review remain separately unverified unless real evidence exists.

## 0.3 experience and feedback boundaries

Private records are outside the contest workspace and Git trees; copying a teammate project cannot import that local path binding. Checksums and request attestations do not authenticate people or defend against malicious local processes. Current model/result facts are always freshly read from the original authority, including same-revision file drift. Recaps describe partial captured context.

Feedback has off/review/limited_auto choices. Review sends only the precise reviewed payload bound to repository, account and visibility. Limited automatic content excludes free text, target/problem names, result metrics and raw logs; it reports allowlisted program observations only. An uncertain create is reconciled before retry, and sent requires reading back actual remote content. Missing repository/auth leaves a local draft. CLI implementation and offline injected tests do not establish live GitHub acceptance. Public release and installation replacement are not performed.
