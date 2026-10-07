# License scope and release block

This v0.3.0-preview.2 candidate is available from the public Odyphus/MathModel-Copilot repository at the owner's request. Public accessibility records the actual distribution state; it does **not** establish a blanket redistribution license or complete rights clearance for every migrated component.

`LICENSE` preserves the upstream MIT notice exactly. It covers material inherited from `handsomeZR-netizen/mathmodel-skill`, v6.2.0, commit `e0e65c8c56f1f0435fb76e99490dbae7c2704d59`, under that upstream grant. It does not grant rights in separately migrated code, competition assets or third-party data.

| Material | Origin / record | Candidate treatment | Public rights |
|---|---|---|---|
| Inherited workflow, resources and original upstream SVGs | [UPSTREAM.md](UPSTREAM.md), original MIT notice | Preserve attribution and notice | Upstream MIT scope only |
| cumcm-workflow object validators, document checks and templates | [docs/MIGRATION.md](docs/MIGRATION.md) | Retained to preserve the working kernel | No separate license confirmed; blocking |
| Copilot derivative code, packaging, Dashboard and new synthetic examples | Local development for the owner; file manifest records actual files | Public Preview; scope unresolved | Owner/maintainer must confirm copyright and license; blocking |
| Historical simulator / verifier source | Prior internal reproduction package, see THIRD_PARTY_NOTICES.md | Retained code only | Separate public redistribution rights remain unconfirmed |
| Historical CUMCM PDFs, XLS forms and parameter data | Official source in [docs/HISTORICAL_FIXTURES.md](docs/HISTORICAL_FIXTURES.md) | Excluded from candidate ZIP/wheel/sdist; retained only in internal original evidence | No redistribution claim |
| Mobbin screenshots and other reference UI assets | Research references, when available | Excluded; original implementation only | No implied license transfer |
| Optional dependencies and external renderers | Installed separately | Not vendored | Their own terms apply |

Python metadata uses `LicenseRef-Mixed-Review-Only` as an explicit unresolved scope marker, not an open-source license grant. The repository owner Odyphus and its public repository URL are recorded in `RELEASE_METADATA.json`; they do not establish copyright ownership of every migrated file. `published=true` records the owner-authorized public Preview distribution. `public_release_allowed=false` retains the unresolved clearance gate; no new blanket license is granted by changing repository visibility.

A clean file scan and a successful installation do not resolve these rights. Before declaring a cleared general release, obtain the relevant grants and complete the applicable acceptance. The owner's explicit authorization to update this public Preview does not substitute for third-party grants. Do not replace this file with a blanket MIT claim.
