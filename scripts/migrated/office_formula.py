# Migrated from user-provided cumcm-workflow 1.6.0; see docs/MIGRATION.md.
"""Original deterministic formula bookmark helper only."""
import hashlib
import re

def formula_bookmark_name(formula_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", formula_id.strip())
    if not clean:
        raise ValueError("formula_id must contain at least one letter or digit")
    if not clean[0].isalpha():
        clean = "F_" + clean
    elif not clean.startswith("F_"):
        clean = "F_" + clean
    # Different IDs can collapse to the same sanitized Word name (for example
    # ``F-Q1-1`` and ``F_Q1_1``).  A digest is therefore always included, not
    # only when truncation occurs.  Word bookmark names remain <= 40 chars.
    suffix = hashlib.sha256(formula_id.strip().encode("utf-8")).hexdigest()[:12]
    return f"{clean[:27]}_{suffix}"
