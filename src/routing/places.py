"""Fuzzy place matching for Dakar stop and place names.

People do not type official stop names.  They write "Guediawaye" without
the accent, "Rond-Point Sahm" when the stop is simply "Sahm", or a
neighbourhood name such as "Malika" that covers several stops.  This
module keeps those friendly matches together and returns candidates with
scores instead of guessing one answer.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

# src/routing/places.py -> remonter jusqu'à la racine du dépôt GuindiMa.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_SPOKEN_OVERRIDE_FILES = (
    "voice_word_overrides.csv",
    "voice_overrides.csv",
)

# Two fuzzy candidates closer than this are treated as a real choice for the
# rider.  Guessing one of them is how "Saam" once became "Sam Notaire".
AMBIGUITY_MARGIN = 5.0

# Small, common abbreviations seen in the dataset and in day-to-day typing.
# We expand them before comparing so "Av. Malick Sy" and "Avenue Malick Sy"
# are the same thing.
_ABBREVIATIONS = {
    "rpt": "rond point",
    "rp": "rond point",
    "av": "avenue",
    "ave": "avenue",
    "avn": "avenue",
    "bd": "boulevard",
    "bld": "boulevard",
    "blvd": "boulevard",
    "rte": "route",
    "pl": "place",
    "st": "saint",
    "ste": "sainte",
    "cim": "cimetiere",
    "hop": "hopital",
    "univ": "universite",
    "gare": "gare",
}

MATCH_THRESHOLD = 80.0

# Words that appear in many stop names.  They should not, on their own,
# make "Rond-Point Sahm" match every other "Rond-Point ..." in the city.
_GENERIC_TOKENS = {
    "rond",
    "point",
    "route",
    "avenue",
    "boulevard",
    "place",
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "et",
    "gare",
    "arret",
    "cite",
    "village",
    "marche",
}


def normalize_name(text: object) -> str:
    """Lowercase, strip accents/punctuation, and expand abbreviations."""

    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""

    # NFKD splits accented letters, then ASCII keeps the base letter.
    folded = (
        unicodedata.normalize("NFKD", str(text))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    folded = folded.replace("&", " et ")
    folded = re.sub(r"[^a-z0-9]+", " ", folded)

    tokens: list[str] = []
    for token in folded.split():
        tokens.extend(_ABBREVIATIONS.get(token, token).split())
    return " ".join(tokens).strip()


def terminus_forms(name: object) -> tuple[str, ...]:
    """Les lieux que désigne un nom de terminus ou de gare.

    « Terminus liberté 5 (Dieuppeul) » -> Liberté 5 et Dieuppeul ;
    « Terminus Parcelles Assainies » -> Parcelles Assainies ; « Gare de Colobane »
    -> Colobane.  Un numéro seul (« Terminus 221 (Gadaye) ») ne désigne aucun lieu.
    """

    text = str(name or "").strip()
    match = re.fullmatch(
        r"(?:terminus|gare(?:\s+(?:de|du|d'))?)\s+([^()]+?)\s*(?:\(([^()]*)\))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ()
    return tuple(
        form.strip()
        for form in match.groups()
        if form and form.strip() and not form.strip().isdigit()
    )


def _spoken_display_rank(name: str) -> tuple[bool, bool, int, str]:
    """Prefer normal title case when two rows name the same place."""

    return (name.islower(), name.isupper(), len(name), name.casefold())


@lru_cache(maxsize=1)
def spoken_aliases() -> dict[str, str]:
    """Map the reviewed TTS spellings back to the real place names.

    The voice CSVs were written for speaking: the stop "Sahm" is pronounced
    "Saam".  Listening needs the opposite direction, so a raw ASR word such
    as "saam" or "wakaam" can win as an exact alias instead of relying on a
    fuzzy guess.  Keys are normalized, so case and accents do not matter.
    """

    aliases: dict[str, str] = {}
    for filename in _SPOKEN_OVERRIDE_FILES:
        path = DATA_DIR / filename
        try:
            handle = path.open("r", encoding="utf-8", newline="")
        except OSError:
            # A missing review file should only cost us the aliases, never
            # the whole place index.
            continue
        with handle:
            for row in csv.DictReader(handle):
                spoken = normalize_name(row.get("say_as"))
                real_name = str(row.get("word") or "").strip()
                if not spoken or not real_name:
                    continue
                current = aliases.get(spoken)
                if (
                    current is None
                    or _spoken_display_rank(real_name)
                    < _spoken_display_rank(current)
                ):
                    aliases[spoken] = real_name
    return aliases


def spoken_alias(query: object) -> str | None:
    """Return the real name for an exact spoken form, when one is known."""

    normalized = normalize_name(query)
    if not normalized:
        return None
    return spoken_aliases().get(normalized)


def exact_normalized_names(query: object) -> set[str]:
    """Normalized names that should count as an exact match for a query."""

    names: set[str] = set()
    normalized = normalize_name(query)
    if normalized:
        names.add(normalized)
    alias = spoken_alias(normalized)
    if alias:
        alias_name = normalize_name(alias)
        if alias_name:
            names.add(alias_name)
    return names


def ambiguous_pair(
    candidates: list[PlaceCandidate],
    query: object,
) -> tuple[PlaceCandidate, PlaceCandidate] | None:
    """Return two close candidates when guessing would be unsafe.

    An exact name or a reviewed spoken alias settles the question first.
    Otherwise, two different places within ``AMBIGUITY_MARGIN`` are shown to
    the rider as a choice instead of letting the sorter pick one.
    """

    if len(candidates) < 2:
        return None
    first, second = candidates[0], candidates[1]
    if first.normalized == second.normalized:
        return None

    settled = exact_normalized_names(query)
    if first.normalized in settled or second.normalized in settled:
        return None
    if second.score < MATCH_THRESHOLD:
        return None
    if first.score - second.score > AMBIGUITY_MARGIN:
        return None
    return first, second


@dataclass(frozen=True)
class PlaceCandidate:
    """One possible interpretation of what the user typed."""

    name: str
    normalized: str
    score: float
    lat: float | None
    lon: float | None
    is_stop: bool
    is_place: bool
    stop_names: tuple[str, ...] = ()
    eligible: bool = True

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass
class _Entry:
    name: str
    normalized: str
    lat: float | None = None
    lon: float | None = None
    is_stop: bool = False
    is_place: bool = False
    stop_names: list[str] | None = None

    def __post_init__(self) -> None:
        if self.stop_names is None:
            self.stop_names = []


def _valid_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


class PlaceIndex:
    """All known stop and place names, searchable with fuzzy matching."""

    def __init__(self, entries: list[_Entry]) -> None:
        # Merge entries that normalize to the same name.  "Sahm" and "SAHM"
        # are the same physical stop, so they should not compete.
        merged: dict[str, _Entry] = {}
        for entry in entries:
            if not entry.normalized:
                continue
            current = merged.get(entry.normalized)
            if current is None:
                current = _Entry(
                    name=entry.name,
                    normalized=entry.normalized,
                    lat=entry.lat,
                    lon=entry.lon,
                    is_stop=entry.is_stop,
                    is_place=entry.is_place,
                    stop_names=list(entry.stop_names or []),
                )
                merged[entry.normalized] = current
                continue

            if entry.is_stop:
                current.is_stop = True
                for stop_name in entry.stop_names or []:
                    if stop_name not in current.stop_names:
                        current.stop_names.append(stop_name)
                # A stop's coordinates are usually more precise than a place.
                if current.lat is None or current.lon is None:
                    current.lat = entry.lat
                    current.lon = entry.lon
            if entry.is_place:
                current.is_place = True
                if current.lat is None or current.lon is None:
                    current.lat = entry.lat
                    current.lon = entry.lon

        self._entries = list(merged.values())

    @classmethod
    def from_data(cls, data) -> "PlaceIndex":
        """Build from the real ``arrets_geo`` and ``lieux_geo`` tables."""

        entries: list[_Entry] = []
        for row in data.arrets.itertuples(index=False):
            name = str(row.arret)
            entries.append(
                _Entry(
                    name=name,
                    normalized=normalize_name(name),
                    lat=_valid_number(row.lat),
                    lon=_valid_number(row.lon),
                    is_stop=True,
                    stop_names=[name],
                )
            )
        for row in data.lieux.itertuples(index=False):
            name = str(row.lieu)
            entries.append(
                _Entry(
                    name=name,
                    normalized=normalize_name(name),
                    lat=_valid_number(row.lat),
                    lon=_valid_number(row.lon),
                    is_place=True,
                )
            )
        # En dernier, pour que la position générale d'un arrêt connu reste prioritaire :
        # les arrêts des itinéraires (noms officiels de Dem Dikk compris), et les
        # lieux que désigne un terminus : « Dieuppeul » pour « Terminus liberté 5
        # (Dieuppeul) ».  Leur position est celle de l'arrêt sur sa ligne.
        positions = getattr(data, "positions_ligne", {})
        for row in data.itineraires.itertuples(index=False):
            name = str(row.arret)
            position = positions.get((str(row.compagnie), str(row.ligne)), {}).get(
                int(row.ordre)
            )
            lat, lon = position or (None, None)
            for label in (name, *terminus_forms(name)):
                entries.append(
                    _Entry(
                        name=label,
                        normalized=normalize_name(label),
                        lat=lat,
                        lon=lon,
                        is_stop=True,
                        stop_names=[name],
                    )
                )
        return cls(entries)

    @classmethod
    def from_network(cls, network) -> "PlaceIndex":
        """Build from a Network object (used by synthetic unit tests)."""

        entries: list[_Entry] = []
        for name in network.stop_names:
            lat, lon = network.coords(name) or (None, None)
            entries.append(
                _Entry(
                    name=name,
                    normalized=normalize_name(name),
                    lat=lat,
                    lon=lon,
                    is_stop=True,
                    stop_names=[name],
                )
            )
        return cls(entries)

    def _scored(self, query: str) -> list[PlaceCandidate]:
        query_norm = normalize_name(query)
        if not query_norm:
            return []

        exact_names = exact_normalized_names(query_norm)
        query_tokens = set(query_norm.split())
        query_specific = query_tokens - _GENERIC_TOKENS

        results: list[PlaceCandidate] = []
        for entry in self._entries:
            token_set_score = fuzz.token_set_ratio(query_norm, entry.normalized)
            wratio_score = fuzz.WRatio(query_norm, entry.normalized)
            raw_score = max(token_set_score, wratio_score)

            entry_tokens = set(entry.normalized.split())
            entry_specific = entry_tokens - _GENERIC_TOKENS
            exact = query_norm == entry.normalized
            # A reviewed spoken form, such as "saam" for Sahm, is exact even
            # though the letters differ.  Give it a full score so it cannot
            # lose to an unrelated but spell-similar stop.
            alias_exact = entry.normalized in exact_names
            shared_specific = bool(query_specific & entry_specific)

            # A fuzzy score is only believable when the two names share a
            # real name token (not just "rond point" or "route").  A single
            # distinctive word may still carry a typo, so allow that case
            # when the whole strings are very close.
            near_single_name = (
                len(query_specific) == 1
                and fuzz.ratio(query_norm, entry.normalized) >= 88
            )
            eligible = (
                exact or alias_exact or shared_specific or near_single_name
            )

            results.append(
                PlaceCandidate(
                    name=entry.name,
                    normalized=entry.normalized,
                    score=100.0 if alias_exact else float(raw_score),
                    lat=entry.lat,
                    lon=entry.lon,
                    is_stop=entry.is_stop,
                    is_place=entry.is_place,
                    stop_names=tuple(entry.stop_names or ()),
                    eligible=eligible,
                )
            )

        # Best score first.  On a tie, prefer an exact or alias match, then
        # a real stop, then the shorter name.
        results.sort(
            key=lambda candidate: (
                -candidate.score,
                not candidate.eligible,
                candidate.normalized not in exact_names,
                not candidate.is_stop,
                len(candidate.name),
            )
        )
        return results

    def match(
        self,
        query: str,
        min_score: float = MATCH_THRESHOLD,
        limit: int = 25,
    ) -> list[PlaceCandidate]:
        """Return every good candidate, not just the single best one."""

        return [
            item
            for item in self._scored(query)
            if item.eligible and item.score >= min_score
        ][:limit]

    def suggestions(self, query: str, limit: int = 3) -> list[tuple[str, float]]:
        """Low-confidence names to show when nothing matched."""

        return [(item.name, item.score) for item in self._scored(query)[:limit]]


def prefer_exact_matches(
    candidates: list[PlaceCandidate],
    query: str,
) -> list[PlaceCandidate]:
    """Keep only exact normalized matches when the user's name is known.

    Fuzzy matching is useful for typos and for neighbourhood names, but it
    must not turn an exact stop such as "Yoff" into a longer stop such as
    "Grand Yoff".  The exact candidate still carries its spelling variants in
    ``stop_names``, so the router can use those variants as the same place.
    """

    targets = exact_normalized_names(query)
    if not targets:
        return candidates
    exact = [
        candidate
        for candidate in candidates
        if candidate.normalized in targets
    ]
    return exact or candidates


def representative_coordinates(
    candidates: list[PlaceCandidate],
) -> tuple[float, float] | None:
    """Pick a coordinate for the user's place.

    Candidates are already sorted by relevance, so the first one with a
    usable coordinate is a fair representative for detour checks.
    """

    for candidate in candidates:
        if candidate.has_coordinates:
            return float(candidate.lat), float(candidate.lon)
    return None
