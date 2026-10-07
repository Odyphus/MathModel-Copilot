# License scope and release block

This v0.3.0-preview.1 candidate is stored in the private Odyphus/MathModel-Copilot repository at the owner's request. It is **not cleared for public redistribution**. A private source upload is not a public open-source release.

`LICENSE` preserves the upstream MIT notice exactly. It covers material inherited from `handsomeZR-netizen/mathmodel-skill`, v6.2.0, commit `e0e65c8c56f1f0435fb76e99490dbae7c2704d59`, under that upstream grant. It does not grant rights in separately migrated code, competition assets or third-party data.

| Material | Origin / record | Candidate treatment | Public rights |
|---|---|---|---|
| Inherited workflow, resources and original upstream SVGs | [UPSTREAM.md](UPSTREAM.md), original MIT notice | Preserve attribution and notice | Upstream MIT scope only |
| cumcm-workflow object validators, document checks and templates | [docs/MIGRATION.md](docs/MIGRATION.md) | Retained to preserve the working kernel | No separate license confirmed; blocking |
| Copilot derivative code, packaging, Dashboard and new synthetic examples | Local development for the owner; file manifest records actual files | Local review | Owner/maintainer must confirm copyright and license; blocking |
| Historical simulator / verifier source | Prior internal reproduction package, see THIRD_PARTY_NOTICES.md | Retained code only | Separate public redistribution rights remain unconfirmed |
| Historical CUMCM PDFs, XLS forms and parameter data | Official source in [docs/HISTORICAL_FIXTURES.md](docs/HISTORICAL_FIXTURES.md) | Excluded from candidate ZIP/wheel/sdist; retained only in internal original evidence | No redistribution claim |
| Mobbin screenshots and other reference UI assets | Research references, when available | Excluded; original implementation only | No implied license transfer |
| Optional dependencies and external renderers | Installed separately | Not vendored | Their own terms apply |

Python metadata uses `LicenseRef-Mixed-Review-Only` as an explicit unresolved scope marker, not an open-source license grant. The repository owner Odyphus and its actual private repository URL are recorded in `RELEASE_METADATA.json`; they do not establish copyright ownership of every migrated file. `published` describes public release and remains false.

A clean file scan and a successful installation do not resolve these rights. Before public distribution, obtain the relevant grants, confirm the actual maintainer/repository and final acceptance, then obtain explicit publication authorization. Do not replace this file with a blanket MIT claim.
