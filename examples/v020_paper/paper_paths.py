"""Explicit fresh workspace only; no historical state discovery or fallback."""
import os
from pathlib import Path
HERE=Path(__file__).resolve().parent
PRODUCT=HERE.parents[1]
if not os.environ.get('MATHMODEL_PAPER_PROJECT'):
    raise RuntimeError('Set MATHMODEL_PAPER_PROJECT to a newly executed benchmark workspace')
PROJECT=Path(os.environ['MATHMODEL_PAPER_PROJECT']).resolve()
RULES=Path(os.environ.get('MATHMODEL_RULE_SNAPSHOTS',str(PROJECT/'rules'))).resolve()
