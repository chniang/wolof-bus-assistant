"""Vérifie que chaque phrase de EXEMPLES traverse le pipeline complet.

    phrase en wolof -> extract_intent() (LLM) -> StopsMatcher.find_line() (CSV)

La liste est importée depuis app.py : toute modification de EXEMPLES est donc
contrôlée par ce script. À lancer après chaque changement de EXEMPLES, et avant
une démo, pour ne pas découvrir devant le jury qu'une phrase ne matche aucune ligne.

Usage:
    python -X utf8 -u src/app/check_examples.py

Code de sortie : 0 si toutes les phrases donnent found=True, 1 sinon.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app import EXEMPLES
from intent.extract_intent import extract_intent, get_client
from matching.stops_matcher import StopsMatcher

SEPARATEUR = "=" * 68

# L'API NVIDIA limite le débit : enchaîner les phrases sans pause déclenche des
# 429 qui font échouer la vérification pour une raison étrangère aux phrases.
PAUSE_ENTRE_PHRASES = 4


def verifier_phrase(phrase: str, matcher: StopsMatcher, client) -> dict:
    """Enchaîne extraction puis correspondance sur une phrase."""
    rapport: dict = {"phrase": phrase, "ok": False, "etape": None, "detail": None}

    intent = extract_intent(phrase, client=client)
    rapport["intent"] = intent
    if intent.get("erreur"):
        rapport["etape"] = "extraction"
        rapport["detail"] = intent["erreur"]
        return rapport

    depart, arrivee = intent["depart"], intent["arrivee"]
    rapport["depart"], rapport["arrivee"] = depart, arrivee
    if not depart or not arrivee:
        rapport["etape"] = "extraction"
        rapport["detail"] = f"champ vide (depart={depart!r}, arrivee={arrivee!r})"
        return rapport

    resultat = matcher.find_line(depart, arrivee)
    rapport["resultat"] = resultat
    rapport["etape"] = "correspondance"
    if not resultat["found"]:
        rapport["detail"] = _raison_echec(resultat)
        return rapport

    rapport["ok"] = True
    rapport["detail"] = ", ".join(
        f"{match['compagnie']} {match['ligne']} ({match['sens']})"
        for match in resultat["lignes"]
    )
    return rapport


def _raison_echec(resultat: dict) -> str:
    if not resultat["depart_valide"] or not resultat["arrivee_valide"]:
        details = []
        if not resultat["depart_valide"]:
            details.append(
                f"départ hors réseau (proche : {resultat['depart_matched']} "
                f"{resultat['depart_score']})"
            )
        if not resultat["arrivee_valide"]:
            details.append(
                f"arrivée hors réseau (proche : {resultat['arrivee_matched']} "
                f"{resultat['arrivee_score']})"
            )
        return " ; ".join(details)
    return (
        f"aucune ligne ne relie {resultat['depart_matched']} à "
        f"{resultat['arrivee_matched']} dans le CSV"
    )


def main() -> int:
    print(SEPARATEUR)
    print("Vérification EXEMPLES — pipeline complet (extraction LLM + matcher)")
    print(SEPARATEUR)

    matcher = StopsMatcher()
    client = get_client()
    rapports = []
    for index, phrase in enumerate(EXEMPLES):
        if index:
            time.sleep(PAUSE_ENTRE_PHRASES)
        print(f"\n[{index + 1}/{len(EXEMPLES)}] analyse en cours…")
        rapports.append(verifier_phrase(phrase, matcher, client))

    echecs = 0
    for index, rapport in enumerate(rapports, start=1):
        marque = "OK  " if rapport["ok"] else "ECHEC"
        print(f"\n[{index}/{len(rapports)}] {marque}  {rapport['phrase']}")
        if rapport["etape"] == "extraction" and "intent" in rapport:
            print(f"        extraction  : depart={rapport['intent']['depart']!r} "
                  f"arrivee={rapport['intent']['arrivee']!r}")
        elif "depart" in rapport:
            print(f"        extraction  : depart={rapport['depart']!r} "
                  f"arrivee={rapport['arrivee']!r}")
        print(f"        {rapport['etape']:<13}: {rapport['detail']}")
        if not rapport["ok"]:
            echecs += 1

    print("\n" + SEPARATEUR)
    if echecs:
        print(f"{echecs}/{len(rapports)} phrase(s) en échec :")
        for rapport in rapports:
            if not rapport["ok"]:
                print(f"  - {rapport['phrase']}  ({rapport['etape']} : {rapport['detail']})")
        print("Corriger EXEMPLES dans src/app/app.py avec un trajet présent dans le CSV.")
    else:
        print(f"{len(rapports)}/{len(rapports)} phrase(s) valides : le pipeline de démo tient.")
    print(SEPARATEUR)
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
