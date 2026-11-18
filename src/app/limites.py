"""Plafond d'appels à un service payant ou limité, partagé par tout le Space.

L'app est publique et sans compte : sans plafond, un script qui enverrait des
phrases incompréhensibles viderait le quota NVIDIA. Une fois le plafond atteint,
la recherche continue avec l'extraction locale ; seul le LLM attend.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque


def entier_env(nom: str, defaut: int) -> int:
    """Un réglage entier positif ; une valeur invalide garde le défaut."""
    try:
        valeur = int(os.getenv(nom, "").strip())
    except ValueError:
        return defaut
    return valeur if valeur > 0 else defaut


class LimiteDebit:
    """Fenêtres glissantes d'une minute et d'une journée."""

    def __init__(self, par_minute: int, par_jour: int, horloge=time.monotonic):
        self.par_minute = par_minute
        self.par_jour = par_jour
        self.horloge = horloge
        self._appels: deque[float] = deque()
        self._verrou = threading.Lock()

    def autoriser(self) -> bool:
        """Compte l'appel s'il reste de la place, sinon répond non sans attendre."""
        with self._verrou:
            maintenant = self.horloge()
            while self._appels and maintenant - self._appels[0] >= 86_400:
                self._appels.popleft()
            recents = sum(1 for instant in self._appels if maintenant - instant < 60)
            if recents >= self.par_minute or len(self._appels) >= self.par_jour:
                return False
            self._appels.append(maintenant)
            return True
