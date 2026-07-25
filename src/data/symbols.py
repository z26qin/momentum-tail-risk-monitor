"""Symbol normalisation across four sources that disagree with one another.

Observed during the Stage 1 probe, by direct query rather than assumption:

| Security           | Nasdaq screener | Price vendor | FINRA short interest | FINRA CNMS daily |
|--------------------|-----------------|--------------|----------------------|------------------|
| Berkshire B        | ``BRK/B``       | ``BRK-B``    | ``BRKB``             | ``BRK/B``        |
| Brown-Forman B     | ``BF/B``        | ``BF-B``     | ``BFB``              | ``BF/B``         |
| Lennar B           | ``LEN/B``       | ``LEN-B``    | ``LENB``             | ``LEN/B``        |

``BRK-B`` returns zero rows from the FINRA short-interest dataset and ``BRK/B``
returns zero rows as well; only ``BRKB`` matches. A per-source mapping is
therefore mandatory, not a nicety: without it every dual-class name silently
drops out of the positioning panel.
"""

from __future__ import annotations

import re


#: The project's canonical form. Chosen to match the price vendor because that
#: is the source with the largest number of downstream uses.
CANONICAL_CLASS_SEPARATOR = "-"

_CLASS_SUFFIX = re.compile(r"^([A-Z]+)[./-]([A-Z])$")


def to_canonical(symbol: str) -> str:
    """Normalise any vendor spelling to the canonical ``ROOT-CLASS`` form."""

    cleaned = symbol.strip().upper()
    match = _CLASS_SUFFIX.match(cleaned)
    if match:
        return f"{match.group(1)}{CANONICAL_CLASS_SEPARATOR}{match.group(2)}"
    return cleaned


def to_price_vendor(symbol: str) -> str:
    """Canonical -> price vendor (``BRK-B``)."""

    return to_canonical(symbol)


def to_finra_short_interest(symbol: str) -> str:
    """Canonical -> FINRA consolidated short interest (``BRKB``)."""

    canonical = to_canonical(symbol)
    match = _CLASS_SUFFIX.match(canonical)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return canonical


def to_finra_daily(symbol: str) -> str:
    """Canonical -> FINRA CNMS daily short volume file (``BRK/B``)."""

    canonical = to_canonical(symbol)
    match = _CLASS_SUFFIX.match(canonical)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return canonical


def has_class_suffix(symbol: str) -> bool:
    """True when the symbol denotes a share class rather than a plain ticker."""

    return bool(_CLASS_SUFFIX.match(to_canonical(symbol)))
