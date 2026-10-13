r"""Vérifie la « seconde chance » ASR : `transcrir_avec_seconde_chance`.

Les modèles sont des bouchons — on ne charge ni whisper ni Kiriku — pour ne
tester que la logique du réessai : si la première transcription ne mène à aucun
trajet (lieu manquant ou aucune ligne), on retranscrit une fois avec l'autre
modèle, et on garde le résultat qui trouve un trajet (la mention « (2e essai) »
distingue ce second passage).

    .\.venv\Scripts\python.exe tests\test_seconde_chance.py

Code de sortie : 0 si tout passe, 1 sinon.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from asr.transcribe import transcrir_avec_seconde_chance  # noqa: E402


def _premier(phrase: str, libelle: str = "Kiriku-Wolof-ASR (GPU)", duree: float = 1.0):
    """Un premier essai factice : il transcrit toujours pareil."""

    def essai(son):
        return phrase, libelle, duree

    return essai


def _second(phrase: str, libelle: str = "whisper-small", duree: float = 1.5, lever: bool = False):
    """Un second essai factice ; `lever` simule le GPU de nouveau refusé."""

    def essai(son, libelle_premier):
        if lever:
            raise RuntimeError("No CUDA GPUs are available")
        return phrase, libelle, duree

    return essai


def cas_premier_suffit() -> int:
    """La première transcription mène à un trajet : pas de second essai."""
    appels: list[str] = []

    def second(*args):
        appels.append(args)
        raise AssertionError("le second essai ne doit pas être appelé")

    phrase, libelle, duree, retente = transcrir_avec_seconde_chance(
        object(),
        _premier("maa ngi Ouakam, bëgg naa dem Palais 2"),
        second,
        lambda p: "ouakam" in p.lower(),
    )
    bon = (
        (phrase, libelle, duree, retente)
        == ("maa ngi Ouakam, bëgg naa dem Palais 2", "Kiriku-Wolof-ASR (GPU)", 1.0, False)
        and appels == []
    )
    print(f"{'OK ' if bon else 'ÉCHEC'} | premier essai trouvé → pas de second essai")
    return not bon


def cas_second_essai_gagne() -> int:
    """Le premier ne trouve rien, le second (whisper) trouve un trajet."""
    phrase, libelle, duree, retente = transcrir_avec_seconde_chance(
        object(),
        _premier("liberte pale"),
        _second("maa ngi Ouakam, bëgg naa dem Palais 2"),
        lambda p: "ouakam" in p.lower(),
    )
    bon = (
        phrase == "maa ngi Ouakam, bëgg naa dem Palais 2"
        and libelle == "whisper-small (2e essai)"
        and duree == 1.5
        and retente is True
    )
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | second essai gagnant → "
        f"{phrase!r}, {libelle!r}, {duree}s, retente={retente}"
    )
    return not bon


def cas_second_essai_echoue_on_garde_le_premier() -> int:
    """Ni le premier ni le second ne trouvent : on garde le premier résultat."""
    phrase, libelle, duree, retente = transcrir_avec_seconde_chance(
        object(),
        _premier("liberte pale"),
        _second("guediawaye ouakam"),
        lambda p: False,
    )
    bon = (phrase, libelle, duree, retente) == ("liberte pale", "Kiriku-Wolof-ASR (GPU)", 1.0, True)
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | aucun trajet → premier résultat gardé "
        f"({phrase!r}, {libelle!r}, retente={retente})"
    )
    return not bon


def cas_gpu_de_nouveau_refuse() -> int:
    """Le second essai lève (GPU refusé à nouveau) : on garde le premier."""
    phrase, libelle, duree, retente = transcrir_avec_seconde_chance(
        object(),
        _premier("liberte pale"),
        _second("", lever=True),
        lambda p: False,
    )
    bon = (phrase, libelle, duree, retente) == ("liberte pale", "Kiriku-Wolof-ASR (GPU)", 1.0, True)
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | second essai => GPU refusé → premier gardé "
        f"({phrase!r}, {libelle!r}, retente={retente})"
    )
    return not bon


def cas_premier_impossible_leve() -> int:
    """Plus aucune transcription possible (audio illisible, modèles absents) : ça remonte."""
    def premier(son):
        raise RuntimeError("aucun modèle ne répond")

    try:
        transcrir_avec_seconde_chance(object(), premier, _second("x"), lambda p: True)
    except RuntimeError as exc:
        bon = "aucun modèle" in str(exc)
    else:
        bon = False
    print(f"{'OK ' if bon else 'ÉCHEC'} | premier essai impossible → exception remontée")
    return not bon


def cas_second_informe_du_premier_modele() -> int:
    """L'autre modèle est choisi d'après le libellé du premier essai."""
    recu: dict = {}

    def second(son, libelle_premier):
        recu["libelle"] = libelle_premier
        return "maa ngi Ouakam, bëgg naa dem Palais 2", "whisper-small", 0.9

    transcrir_avec_seconde_chance(
        object(),
        _premier("liberte pale"),
        second,
        lambda p: False,
    )
    bon = recu == {"libelle": "Kiriku-Wolof-ASR (GPU)"}
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | second essai reçoit le libellé du premier "
        f"({recu.get('libelle')!r})"
    )
    return not bon


def cas_vide_donne_la_place_au_second() -> int:
    """Une transcription vide (rien d'audible) laisse au second essai sa chance."""
    phrase, libelle, _, retente = transcrir_avec_seconde_chance(
        object(),
        _premier(""),
        _second("maa ngi Ouakam, bëgg naa dem Palais 2"),
        lambda p: bool(p),
    )
    bon = phrase.startswith("maa ngi") and retente is True
    print(f"{'OK ' if bon else 'ÉCHEC'} | transcription vide → second essai tenté (retente={retente})")
    return not bon


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Test de la seconde chance ASR ===\n")
    echecs = 0
    for essai in (
        cas_premier_suffit,
        cas_second_essai_gagne,
        cas_second_essai_echoue_on_garde_le_premier,
        cas_gpu_de_nouveau_refuse,
        cas_premier_impossible_leve,
        cas_second_informe_du_premier_modele,
        cas_vide_donne_la_place_au_second,
    ):
        echecs += essai()
    print(f"\n{7 - echecs}/7 réussis")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()