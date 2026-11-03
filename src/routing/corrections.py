"""Apply small, human-reviewed field corrections to the bus itineraries.

The public CSV is a useful starting point, but a Dakar rider can spot a stop
that is missing, misplaced, or listed after the bus has already left a street.
This module keeps those fixes in a small JSON file instead of editing the
downloaded data by hand.  A bad correction is reported and skipped; it must
never stop the app from starting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from .network import Line

DEFAULT_CORRECTIONS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "corrections.json"
)


@dataclass(frozen=True)
class CorrectionResult:
    """The corrected lines and the counts shown at startup."""

    lines: list[Line]
    applied: int
    skipped: int


def _warn(message: str) -> None:
    print(f"[corrections] warning: {message}")


def load_corrections(
    path: str | Path | None = None,
) -> list[Any]:
    """Read the correction list, returning no corrections if it is unusable."""

    correction_path = Path(path) if path is not None else DEFAULT_CORRECTIONS_PATH
    try:
        raw = correction_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # GuindiMa n'a pas encore de fichier de corrections : son absence est
        # normale et ne doit pas polluer le journal.  Un chemin demandé
        # explicitement, lui, mérite un avertissement.
        if path is not None:
            _warn(f"{correction_path} was not found; using the CSV data as-is.")
        return []
    except OSError as exc:
        _warn(f"could not read {correction_path}: {exc}; using the CSV data.")
        return []

    try:
        corrections = json.loads(raw)
    except json.JSONDecodeError as exc:
        _warn(f"{correction_path} is not valid JSON: {exc}; skipping it.")
        return []

    if not isinstance(corrections, list):
        _warn(f"{correction_path} must contain a JSON list; skipping it.")
        return []
    return corrections


def _text(value: Any) -> str:
    return str(value or "").strip()


# Reviewed spelling fixes for stops that the public CSV names inconsistently.
# Keys are normalized names, values are the name riders should see.
STOP_NAME_ALIASES = {
    "case ba": "Case Ba",
    "pattesd oie": "Patte d'Oie",
    "patte d oie": "Patte d'Oie",
    "sahm": "Sahm",
}


def _display_name_rank(name: str) -> tuple[bool, bool, int, str]:
    """Prefer a mixed-case name over an all-caps or lowercase spelling."""

    return (name.isupper(), name.islower(), len(name), name.casefold())


def _case_display_names(
    targets: tuple[tuple[Any, tuple[str, ...]], ...],
) -> dict[str, str]:
    """Find spelling pairs such as "SAHM" and "Sahm" in the loaded frames.

    We only replace a name when the dataset really contains a non-caps
    spelling for the same normalized stop.  A stop that only exists in
    capitals, such as "PAI" or "UCAD", is therefore left untouched.
    """

    from .places import normalize_name

    variants: dict[str, set[str]] = {}
    for frame, columns in targets:
        for column in columns:
            if column not in frame.columns:
                continue
            for value in frame[column]:
                if not isinstance(value, str):
                    continue
                text = value.strip()
                if not text:
                    continue
                variants.setdefault(normalize_name(text), set()).add(text)

    preferred: dict[str, str] = {}
    for normalized, names in variants.items():
        normal = [name for name in names if not name.isupper()]
        if normal and len(normal) < len(names):
            preferred[normalized] = min(normal, key=_display_name_rank)
    return preferred


def canonical_stop_name(name: Any) -> str:
    """Return the reviewed display name for a stop, or the name unchanged."""

    text = str(name or "").strip()
    if not text:
        return text

    # Imported here so corrections can keep its small module surface and
    # avoid an import cycle through the network module.
    from .places import normalize_name

    return STOP_NAME_ALIASES.get(normalize_name(text), text)


def canonicalize_data_stop_names(data: Any) -> None:
    """Apply the reviewed stop names to every column that carries one.

    This runs on the loaded frames before the graph is built, so a route
    through "Case-Ba" and another through "Case Ba" become the same stop
    without editing the downloaded CSV by hand.  It also uses the dataset
    itself to choose "Sahm" over "SAHM" when both spellings are present.
    """

    from .places import normalize_name

    targets = (
        (data.arrets, ("arret",)),
        (data.lieux, ("lieu",)),
        (data.itineraires, ("arret",)),
        (data.lignes, ("terminus_a", "terminus_b")),
    )
    case_names = _case_display_names(targets)

    def display_name(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return value
        return case_names.get(normalize_name(text), canonical_stop_name(text))

    for frame, columns in targets:
        for column in columns:
            if column not in frame.columns:
                continue
            frame[column] = frame[column].map(display_name)


def _line_label(operator: str, line: str) -> str:
    return f"{operator} {line}".strip()


def apply_corrections(
    lines: Iterable[Line],
    corrections: Iterable[Any],
    known_stops: Iterable[str],
) -> CorrectionResult:
    """Apply the supported operations and print one summary line.

    Unsupported operations, missing fields, unknown lines, and unknown stops
    are printed as warnings and counted as skipped.  A correction is also
    rejected if it would leave a line with fewer than two stops.
    """

    corrected = list(lines)
    line_positions = {line.key: index for index, line in enumerate(corrected)}
    stops_in_data = {str(stop) for stop in known_stops}
    applied = 0
    skipped = 0

    def skip(position: int, operation: str, message: str) -> None:
        nonlocal skipped
        skipped += 1
        print(
            f"[corrections] skipped #{position} "
            f"({operation or 'unknown op'}): {message}"
        )

    for position, correction in enumerate(corrections, start=1):
        if not isinstance(correction, dict):
            skip(position, "unknown", "the entry is not a JSON object")
            continue

        operation = _text(correction.get("op"))
        operator = _text(correction.get("operator"))
        line_name = _text(correction.get("line"))
        reason = _text(correction.get("reason"))
        if not reason:
            skip(position, operation, "the correction needs a reason")
            continue

        key = (operator, line_name)
        if key not in line_positions:
            skip(
                position,
                operation,
                f"unknown line {_line_label(operator, line_name)!r}",
            )
            continue

        line_index = line_positions[key]
        line = corrected[line_index]
        stops = list(line.stops)
        operation_label = f"{line.company} {line.name}"

        if operation == "remove_stop":
            stop = _text(correction.get("stop"))
            if stop not in stops:
                skip(
                    position,
                    operation,
                    f"unknown stop {stop!r} on {operation_label}",
                )
                continue
            new_stops = [item for item in stops if item != stop]

        elif operation == "replace_stop":
            stop = _text(correction.get("stop"))
            replacement = _text(correction.get("by"))
            if stop not in stops:
                skip(
                    position,
                    operation,
                    f"unknown stop {stop!r} on {operation_label}",
                )
                continue
            if replacement not in stops_in_data:
                skip(
                    position,
                    operation,
                    f"unknown replacement stop {replacement!r} in the data",
                )
                continue
            new_stops = [
                replacement if item == stop else item for item in stops
            ]

        elif operation == "insert_stop_after":
            after = _text(correction.get("after"))
            stop = _text(correction.get("stop"))
            if after not in stops:
                skip(
                    position,
                    operation,
                    f"unknown stop {after!r} on {operation_label}",
                )
                continue
            if stop not in stops_in_data:
                skip(
                    position,
                    operation,
                    f"unknown stop {stop!r} in the data",
                )
                continue
            insert_at = stops.index(after) + 1
            new_stops = stops[:insert_at] + [stop] + stops[insert_at:]

        elif operation == "truncate_after":
            stop = _text(correction.get("stop"))
            if stop not in stops:
                skip(
                    position,
                    operation,
                    f"unknown stop {stop!r} on {operation_label}",
                )
                continue
            new_stops = stops[: stops.index(stop) + 1]

        else:
            skip(position, operation, "unsupported operation")
            continue

        if len(new_stops) < 2:
            skip(
                position,
                operation,
                f"{operation_label} would have fewer than two stops",
            )
            continue

        # A corrected path should also expose its new endpoints as termini.
        corrected[line_index] = replace(
            line,
            stops=tuple(new_stops),
            terminus_a=new_stops[0],
            terminus_b=new_stops[-1],
        )
        applied += 1

    print(f"[corrections] {applied} applied, {skipped} skipped")
    return CorrectionResult(corrected, applied, skipped)
