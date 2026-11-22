"""Investor-name handling shared by firm matching and strict round matching.

Names are compared only after `normalize_name`, and a round's investor string is
split into individual names first: "Accel" must equal a name, never be a substring
of one ("Accel-KKR").
"""

import re

# trailing words that vary across sources for the same firm
_SUFFIXES = {
    "ventures", "venture", "capital", "partners", "partner", "fund", "funds", "llp",
    "llc", "ltd", "limited", "inc", "advisors", "advisers", "management", "investments",
    "vc", "india", "group", "holdings", "pvt", "private",
}
_NOTE = re.compile(r"\((?:lead|co-?lead|led|follow[- ]?on)[^)]*\)", re.IGNORECASE)
_SEPARATORS = re.compile(r"\s*[,;|]\s*|\s+&\s+(?=[A-Z])|\s+and\s+(?=[A-Z])")


def normalize_name(name: str) -> str:
    """Lowercase, drop "(lead)"-style notes and punctuation, collapse whitespace."""
    name = _NOTE.sub(" ", name).lower()
    name = re.sub(r"[^\w\s&-]", " ", name)
    return re.sub(r"\s+", " ", name).strip(" -")


def split_investors(field: str | None) -> list[str]:
    """Split a round's investor string ("Accel, Angel Collective (lead)") into names."""
    if not field:
        return []
    return [part.strip() for part in _SEPARATORS.split(field) if part and part.strip()]


def round_names_firm(round_investors: str | None, canonical_names: set[str]) -> str | None:
    """The round's investor name that exactly matches a confirmed canonical name, if any."""
    wanted = {normalize_name(name) for name in canonical_names}
    for name in split_investors(round_investors):
        if normalize_name(name) in wanted:
            return name
    return None


def name_variants(official_name: str, domain: str | None = None) -> list[str]:
    """Search variants for a firm: the name, the name without generic suffixes, the domain stem."""
    variants = [official_name.strip()]
    words = normalize_name(official_name).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    if words:
        variants.append(" ".join(words))
    if domain:
        stem = re.sub(r"^(https?://)?(www\.)?", "", domain.lower()).split(".")[0]
        if stem:
            variants.append(stem)
    seen: set[str] = set()
    unique = []
    for variant in variants:
        key = normalize_name(variant)
        if key and key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique
