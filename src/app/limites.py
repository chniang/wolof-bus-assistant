"""Plafonds d'usage : pour tout le Space et pour chaque client.

L'app est publique et sans compte : sans plafond, un script viderait le quota
NVIDIA, occuperait la transcription ou remplirait la collecte. Une fois un plafond
atteint, on refuse aussitôt, sans attendre.

Un client est reconnu à une empreinte de son adresse IP, salée avec une valeur
tirée au démarrage et gardée en mémoire. Ni l'adresse, ni l'empreinte, ni le sel
ne sont écrits où que ce soit ; un redémarrage remet tout à zéro.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import deque

MINUTE = 60
HEURE = 3_600
JOUR = 86_400
# Au-delà, le client vu il y a le plus longtemps est oublié : des adresses
# inventées à la chaîne ne peuvent pas faire grossir la mémoire sans fin.
MAX_CLIENTS = 10_000

_SEL = secrets.token_bytes(32)
_FORMES_SIGNALEES: set[int] = set()


def entier_env(nom: str, defaut: int) -> int:
    """Un réglage entier positif ; une valeur invalide garde le défaut."""
    try:
        valeur = int(os.getenv(nom, "").strip())
    except ValueError:
        return defaut
    return valeur if valeur > 0 else defaut


def _place_libre(instants: deque, fenetres: tuple, maintenant: float) -> bool:
    """Oublie ce qui a expiré et dit si un appel de plus tient dans chaque fenêtre."""
    plus_longue = max(duree for duree, _ in fenetres)
    while instants and maintenant - instants[0] >= plus_longue:
        instants.popleft()
    return all(
        sum(1 for instant in instants if maintenant - instant < duree) < maximum
        for duree, maximum in fenetres
    )


class LimiteFenetres:
    """Fenêtres glissantes (durée en secondes, maximum) pour un compteur unique."""

    def __init__(self, fenetres: tuple, horloge=time.monotonic):
        self.fenetres = fenetres
        self.horloge = horloge
        self._appels: deque[float] = deque()
        self._verrou = threading.Lock()

    def autoriser(self) -> bool:
        """Compte l'appel s'il reste de la place ; un refus ne consomme rien."""
        with self._verrou:
            maintenant = self.horloge()
            if not _place_libre(self._appels, self.fenetres, maintenant):
                return False
            self._appels.append(maintenant)
            return True


class LimiteDebit(LimiteFenetres):
    """Plafond global par minute et par jour."""

    def __init__(self, par_minute: int, par_jour: int, horloge=time.monotonic):
        super().__init__(((MINUTE, par_minute), (JOUR, par_jour)), horloge)


class LimiteParClient:
    """Les mêmes fenêtres, avec un compteur par client."""

    def __init__(self, fenetres: tuple, horloge=time.monotonic, max_clients: int = MAX_CLIENTS):
        self.fenetres = fenetres
        self.horloge = horloge
        self.max_clients = max_clients
        self._clients: dict[str, deque[float]] = {}
        self._verrou = threading.Lock()

    def autoriser(self, cle: str | None) -> bool:
        """Sans client identifié (appel interne), il n'y a rien à compter."""
        if cle is None:
            return True
        with self._verrou:
            maintenant = self.horloge()
            instants = self._clients.get(cle)
            if instants is None:
                if len(self._clients) >= self.max_clients:
                    del self._clients[next(iter(self._clients))]
                instants = self._clients[cle] = deque()
            if not _place_libre(instants, self.fenetres, maintenant):
                return False
            instants.append(maintenant)
            return True


def _adresse_valide(texte: str) -> str | None:
    """L'adresse normalisée ; un réseau /64 en IPv6, où un abonné en possède des milliards."""
    try:
        adresse = ipaddress.ip_address(texte.strip())
    except ValueError:
        return None
    if adresse.version == 6:
        if adresse.ipv4_mapped is not None:
            return str(adresse.ipv4_mapped)
        return str(ipaddress.ip_network((adresse, 64), strict=False).network_address)
    return str(adresse)


def _adresse_client(request) -> str:
    """L'adresse du client derrière le proxy du Space.

    `x-forwarded-for` liste « client, proxy 1, proxy 2 ». Le début de la liste peut
    être écrit par le client lui-même ; IP_PROXYS_CONFIANCE=N prend la N-ième
    adresse depuis la fin, celle qu'a vue un proxy de confiance. Le défaut (début de
    liste) ne risque jamais de mettre tous les usagers dans le même compteur.
    """
    entete = (getattr(request, "headers", None) or {}).get("x-forwarded-for", "") or ""
    adresses = [morceau.strip() for morceau in entete.split(",") if morceau.strip()]
    if adresses:
        forme = min(len(adresses), 10)
        if forme not in _FORMES_SIGNALEES:
            _FORMES_SIGNALEES.add(forme)
            # Le nombre seul, pour régler IP_PROXYS_CONFIANCE : jamais une adresse.
            print(f"[limites] x-forwarded-for contient {forme} adresse(s)", flush=True)
        rang = entier_env("IP_PROXYS_CONFIANCE", 0)
        choisie = adresses[-rang] if 0 < rang <= len(adresses) else adresses[0]
        valide = _adresse_valide(choisie)
        if valide:
            return valide
    hote = getattr(getattr(request, "client", None), "host", "") or ""
    return _adresse_valide(hote) or "inconnu"


def cle_client(request) -> str | None:
    """L'empreinte du client, ou None hors d'une requête Gradio."""
    if request is None:
        return None
    adresse = _adresse_client(request).encode("utf-8")
    return hmac.new(_SEL, adresse, hashlib.sha256).hexdigest()[:32]
