"""Collecte de voix et avis sur les réponses (désactivée par défaut).

Rien ne se passe tant que la variable COLLECTE_ACTIVE n'est pas allumée : l'app
efface alors l'audio après la transcription, comme avant.

Une fois allumée :
- chaque enregistrement de l'onglet Parler est gardé : l'utiliser vaut accord,
  décision du propriétaire du projet, annoncée par la note sous la saisie ;
- l'onglet Écrire ne garde jamais de voix ;
- un avis (« La ligne est juste ? ») est rattaché au code de la demande ; après
  une demande écrite, il ne garde que les lieux compris et les lignes proposées,
  sans quoi « oui » ou « non » ne voudrait rien dire ;
- on ne garde jamais nom, téléphone, adresse IP, navigateur ni heure : chaque
  fiche est construite champ par champ, jamais copiée depuis la requête.

L'envoi part d'un fil d'arrière-plan vers un dépôt Hugging Face privé. Il ne peut
ni ralentir ni casser une réponse : au pire, la contribution est perdue.
"""

from __future__ import annotations

import html
import io
import json
import os
import queue
import re
import secrets
import threading
import wave
from datetime import datetime, timezone

import numpy as np

from app.limites import HEURE, JOUR, LimiteFenetres, LimiteParClient, entier_env

DEPOT = "PythonMindset/guindima-voix-testeurs"
TYPE_DEPOT = "dataset"
VARIABLE_ACTIVE = "COLLECTE_ACTIVE"
VARIABLE_JETON = "HF_TOKEN_COLLECTE"
VARIABLE_CONTACT = "CONTACT_WHATSAPP"
DOSSIER_DEPOT = "donnees"
FREQUENCE = 16_000

# Les commits Hugging Face sont datés à la seconde : envoyer à chaque demande
# publierait l'heure exacte que les fiches taisent. On envoie donc à intervalle
# fixe, que la file soit vide ou non : un commit ne dit rien de plus que
# « pendant cette demi-heure ».
INTERVALLE_ENVOI = 1800.0
# 30 s de voix font moins de 1 Mo : la file reste sous ~100 Mo en mémoire.
CAPACITE_FILE = 100

# Contre le remplissage du dépôt par un script. Au-delà, la réponse reste normale
# et rien n'est gardé : l'usager n'a pas à connaître ces seuils.
DUREE_MAX_VOIX_S = entier_env("COLLECTE_DUREE_MAX_S", 20)
# 15 et non 5 : un testeur se reprend souvent, et un PC et un téléphone sur le
# même wifi comptent pour un seul client. Au premier test public, 6 vocaux en
# moins d'une heure depuis une même maison ont suffi à ne plus rien garder.
LIMITE_VOIX_CLIENT = LimiteParClient(((HEURE, entier_env("COLLECTE_MAX_PAR_CLIENT_HEURE", 15)),))
LIMITE_VOIX_JOUR = LimiteFenetres(((JOUR, entier_env("COLLECTE_MAX_PAR_JOUR", 200)),))
# Chaque clic sur un avis occupe une place dans la file d'envoi.
LIMITE_AVIS_CLIENT = LimiteParClient(((HEURE, entier_env("COLLECTE_AVIS_MAX_PAR_CLIENT_HEURE", 30)),))

# Ce qui vaut accord, écrit dans chaque fiche de voix.
ORIGINE_ACCORD = "usage_onglet_parler"
SUPPRESSION_WHATSAPP = "Pour faire supprimer {quoi}, envoie ce code par WhatsApp au {numero}."
SUPPRESSION_PARTAGE = (
    "Pour faire supprimer {quoi}, envoie ce code à la personne qui t'a partagé l'application."
)
QUOI_VOIX = "ton enregistrement"
QUOI_AVIS = "ton avis"

REPONSES_AVIS = {"oui", "non", "ne_sait_pas"}
# Lot C6 : la question « Temps réel du trajet » est retirée (décision de
# Cheikh) : au moment de la recherche, l'usager ne connaît pas ce temps, ses
# réponses auraient été devinées. avis.json n'écrit plus de temps ; les fiches
# déjà envoyées restent telles quelles.
# Lot C : « Note l'application », de 1 à 5 étoiles, dans le même avis.json.
ETOILES_MIN, ETOILES_MAX = 1, 5

# Ni 0/O, ni 1/I/L : le code se recopie à la main dans WhatsApp. Six signes et non
# quatre chiffres : avec 10 000 codes, deux testeurs finiraient par partager le
# même, et supprimer l'un effacerait l'autre.
ALPHABET_CODE = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LONGUEUR_CODE = 6
MOTIF_CODE = re.compile(rf"GM-[{ALPHABET_CODE}]{{{LONGUEUR_CODE}}}")


def collecte_active() -> bool:
    """Vrai seulement si COLLECTE_ACTIVE est explicitement allumée."""
    return os.getenv(VARIABLE_ACTIVE, "").strip().lower() in {"1", "true", "oui", "on", "yes"}


def jeton_collecte() -> str:
    """Le jeton dédié. Jamais HF_TOKEN, qui sert à lire les modèles."""
    return os.getenv(VARIABLE_JETON, "").strip()


def nouveau_code() -> str:
    return "GM-" + "".join(secrets.choice(ALPHABET_CODE) for _ in range(LONGUEUR_CODE))


def jour_courant() -> str:
    """La date seule : l'heure n'est jamais conservée."""
    return datetime.now(timezone.utc).date().isoformat()


def dossier_du_code(code: str) -> str:
    return f"{DOSSIER_DEPOT}/{code}"


def numero_contact() -> str:
    """Le numéro configuré, réduit aux signes d'un numéro ; vide s'il n'y en a pas."""
    brut = os.getenv(VARIABLE_CONTACT, "")
    numero = re.sub(r"[^0-9+() -]", "", brut).strip()
    return numero if re.search(r"\d", numero) else ""


def phrase_suppression(quoi: str = QUOI_VOIX) -> str:
    """Comment demander la suppression : aucun numéro s'il n'est pas configuré."""
    numero = numero_contact()
    if numero:
        return SUPPRESSION_WHATSAPP.format(quoi=quoi, numero=html.escape(numero))
    return SUPPRESSION_PARTAGE.format(quoi=quoi)


def message_code(code: str, quoi: str = QUOI_VOIX) -> str:
    return f"**Ton code : {code}**\n\n{phrase_suppression(quoi)}"


def wav_16k(son: np.ndarray) -> bytes:
    """L'audio décodé (float, 16 kHz, mono) en WAV 16 bits, sans métadonnées."""
    echantillons = np.clip(np.asarray(son, dtype=np.float32), -1.0, 1.0)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(FREQUENCE)
        sortie.writeframes((echantillons * 32767).astype("<i2").tobytes())
    return tampon.getvalue()


def _json(fiche: dict) -> bytes:
    return json.dumps(fiche, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")


def _nom_ligne(match: dict) -> str:
    return f"{match.get('compagnie', '')} {match.get('ligne', '')}".strip()


def _noms_etapes(etapes: list[dict]) -> str:
    return " + ".join(_nom_ligne(etape) for etape in etapes)


def lignes_proposees(resultat: dict, limite: int = 3) -> list[str]:
    """Les lignes réellement affichées, dans l'ordre et selon les règles des cartes."""
    possibles = resultat.get("lieux_possibles")
    if possibles:
        noms = []
        for possible in possibles:
            option, genre = possible.get("option") or {}, possible.get("genre")
            if genre == "ligne":
                noms.append(_nom_ligne(option))
            elif genre == "correspondance":
                noms.append(_noms_etapes([option["etape_1"], option["etape_2"]]))
            elif genre != "a_pied":
                noms.append(_noms_etapes(option.get("etapes") or []))
        return noms
    lignes = resultat.get("lignes") or []
    if lignes:
        return [_nom_ligne(match) for match in lignes[:limite]]
    noms = [
        _noms_etapes([trajet["etape_1"], trajet["etape_2"]])
        for trajet in (resultat.get("correspondances") or [])[:limite]
    ]
    noms += [
        _noms_etapes(trajet.get("etapes") or [])
        for trajet in (resultat.get("trajets_2") or [])[:limite]
    ]
    return noms


def televerser_hf(fichiers: dict[str, bytes], api=None) -> None:
    """Un commit pour tout le lot, uniquement vers un dépôt confirmé privé.

    Le dépôt est revérifié à chaque lot : s'il a été créé public par erreur, ou
    rendu public depuis, aucune voix ne part.
    """
    from huggingface_hub import CommitOperationAdd

    if api is None:
        from huggingface_hub import HfApi

        # Sans ce contrôle, un jeton vide ferait retomber la bibliothèque sur
        # HF_TOKEN ou sur le compte connecté.
        jeton = jeton_collecte()
        if not jeton:
            raise PermissionError("jeton de collecte absent")
        api = HfApi(token=jeton)
    if api.repo_info(DEPOT, repo_type=TYPE_DEPOT).private is not True:
        raise PermissionError("dépôt non privé")
    api.create_commit(
        repo_id=DEPOT,
        repo_type=TYPE_DEPOT,
        operations=[
            CommitOperationAdd(path_in_repo=chemin, path_or_fileobj=octets)
            for chemin, octets in fichiers.items()
        ],
        # Ni code ni nombre de personnes dans l'historique.
        commit_message="Contributions des testeurs",
    )


def _resume_erreur(exc: Exception) -> str:
    """Le type d'erreur et le statut HTTP : les messages contiennent des chemins, donc des codes."""
    statut = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__} {statut}" if statut else type(exc).__name__


class Collecteur:
    """File en mémoire, vidée par un fil d'arrière-plan à intervalle fixe."""

    def __init__(self, televerser=televerser_hf, intervalle=INTERVALLE_ENVOI, capacite=CAPACITE_FILE):
        self.televerser = televerser
        self.intervalle = intervalle
        self.file: queue.Queue = queue.Queue(maxsize=capacite)
        self._a_reessayer: dict[str, bytes] = {}
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        self._jeton_signale = False

    def soumettre(self, fichiers: dict[str, bytes]) -> bool:
        """Ajoute à la file sans jamais attendre. Faux si rien ne sera envoyé."""
        if not jeton_collecte():
            if not self._jeton_signale:
                self._jeton_signale = True
                print(f"[collecte] {VARIABLE_JETON} absent : rien n'est envoyé", flush=True)
            return False
        try:
            self.file.put_nowait(fichiers)
        except queue.Full:
            print("[collecte] file pleine : contribution ignorée", flush=True)
            return False
        self._demarrer()
        return True

    def _demarrer(self) -> None:
        with self._verrou:
            if self._fil is None or not self._fil.is_alive():
                self._fil = threading.Thread(target=self._boucle, name="collecte", daemon=True)
                self._fil.start()

    def arreter(self) -> None:
        self._arret.set()

    def _boucle(self) -> None:
        while not self._arret.wait(self.intervalle):
            try:
                self.vider()
            except Exception as exc:
                print(f"[collecte] erreur du fil d'envoi ({_resume_erreur(exc)})", flush=True)

    def vider(self) -> int:
        """Envoie ce qui attend ; renvoie le nombre de fichiers partis.

        Un même chemin soumis deux fois (avis corrigé) ne part qu'une fois, dans
        sa dernière version. Un lot refusé est retenté une seule fois, au passage
        suivant, puis abandonné : des voix ne restent pas indéfiniment en mémoire.
        """
        retente, self._a_reessayer = self._a_reessayer, {}
        lot = dict(retente)
        nouveaux: dict[str, bytes] = {}
        while True:
            try:
                nouveaux.update(self.file.get_nowait())
            except queue.Empty:
                break
        lot.update(nouveaux)
        if not lot:
            return 0
        # Un dossier par code (voix, avis) : le nombre de contributions, pas de fichiers.
        dossiers = len({chemin.rsplit("/", 1)[0] for chemin in lot})
        print(f"[collecte] envoi : {dossiers} dossier(s)", flush=True)
        try:
            self.televerser(lot)
        except Exception as exc:
            print(f"[collecte] envoi impossible ({_resume_erreur(exc)})", flush=True)
            # Seuls les fichiers encore jamais retentés ont droit à un second essai.
            self._a_reessayer = nouveaux
            return 0
        return len(lot)


COLLECTEUR = Collecteur()


def limite_voix_atteinte(son, cle: str | None) -> str | None:
    """Le nom de la limite qui écarte cette voix, ou None si elle est gardée.

    Durée, puis plafond du client, puis plafond du jour, dans cet ordre : une
    voix trop longue n'entame pas le quota du client, une voix refusée au client
    n'entame pas celui du jour.
    """
    if len(son) > DUREE_MAX_VOIX_S * FREQUENCE:
        return "durée"
    if not LIMITE_VOIX_CLIENT.autoriser(cle):
        return "par client et par heure"
    if not LIMITE_VOIX_JOUR.autoriser():
        return "par jour"
    return None


def voix_acceptable(son, cle: str | None) -> bool:
    return limite_voix_atteinte(son, cle) is None


def avis_autorise(cle: str | None) -> bool:
    return LIMITE_AVIS_CLIENT.autoriser(cle)


def nouveau_suivi(trace: dict) -> tuple[dict, str]:
    """Après une réponse : le suivi de session et le message à afficher.

    Une demande vocale est mise en file et son code affiché. Une demande écrite
    n'a pas d'audio : rien n'est envoyé ici, seul un avis donné ensuite produira
    une fiche. Au-delà des plafonds, rien n'est gardé et aucun code n'est promis.
    """
    code = nouveau_code()
    suivi = {
        "code": code,
        "depart": trace.get("depart") or "",
        "arrivee": trace.get("arrivee") or "",
        "lignes": list(trace.get("lignes") or []),
        "voix": False,
        "reponse": None,
        "etoiles": None,
    }
    son, phrase = trace.get("son"), trace.get("phrase")
    if son is None or not phrase:
        return suivi, ""
    limite = limite_voix_atteinte(son, trace.get("client"))
    if limite:
        # Au test public, ce refus était muet : on croyait le chemin CPU en cause.
        # Le nom de la limite seulement, jamais le client ni la phrase.
        print(f"[collecte] ignorée : limite {limite} atteinte", flush=True)
        return suivi, ""
    fiche = {
        "code": code,
        "date": jour_courant(),
        "consentement_voix": ORIGINE_ACCORD,
        "transcription": phrase,
        "modele_asr": trace.get("modele_asr") or "",
        "depart": suivi["depart"],
        "arrivee": suivi["arrivee"],
        "lignes_proposees": suivi["lignes"],
    }
    # Lot G0 : transcription jugée absurde (boucle, autre langue) : la fiche
    # garde la transcription brute, marquée, pour réentraîner l'ASR.
    if trace.get("garde_fou"):
        fiche["garde_fou"] = True
    dossier = dossier_du_code(code)
    suivi["voix"] = COLLECTEUR.soumettre(
        {f"{dossier}/audio.wav": wav_16k(son), f"{dossier}/demande.json": _json(fiche)}
    )
    if suivi["voix"]:
        # Le code seul : c'est lui que l'usager montrera pour faire supprimer sa voix.
        print(f"[collecte] en file {code}", flush=True)
    return suivi, message_code(code) if suivi["voix"] else ""


def suivi_mis_a_jour(suivi: dict, trace: dict) -> dict:
    """Changement de compagnie : même code, mais l'avis portera sur les lignes affichées."""
    return {
        **suivi,
        "depart": trace.get("depart") or "",
        "arrivee": trace.get("arrivee") or "",
        "lignes": list(trace.get("lignes") or []),
    }


def etoiles_valides(valeur: object) -> int | None:
    """La note de l'application, entière de 1 à 5, ou None si elle n'est pas valable."""
    if isinstance(valeur, bool):
        return None
    try:
        note = float(valeur)
    except (TypeError, ValueError):
        return None
    if not note.is_integer() or not ETOILES_MIN <= note <= ETOILES_MAX:
        return None
    return int(note)


def noter_avis(suivi: dict, reponse: str | None = None, etoiles: int | None = None) -> tuple[dict, str]:
    """Enregistre l'avis (Oui / Non / Je ne sais pas) et la note de l'application.

    La note en étoiles (lot C) va dans le même avis.json, sous le même code GM- :
    un chiffre de 1 à 5, rien d'autre sur l'usager.
    """
    suivi = dict(suivi)
    if reponse in REPONSES_AVIS:
        suivi["reponse"] = reponse
    if etoiles_valides(etoiles) is not None:
        suivi["etoiles"] = etoiles_valides(etoiles)
    fiche = {
        "code": suivi["code"],
        "date": jour_courant(),
        "reponse": suivi.get("reponse"),
        "etoiles": suivi.get("etoiles"),
        "depart": suivi["depart"],
        "arrivee": suivi["arrivee"],
        "lignes_proposees": suivi["lignes"],
        "avec_voix": suivi["voix"],
    }
    chemin = f"{dossier_du_code(suivi['code'])}/avis.json"
    if not COLLECTEUR.soumettre({chemin: _json(fiche)}):
        return suivi, ""
    quoi = QUOI_VOIX if suivi["voix"] else QUOI_AVIS
    return suivi, f"Merci, c'est noté.\n\n{message_code(suivi['code'], quoi)}"
