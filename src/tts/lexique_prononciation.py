"""Orthographe parlée de la voix : comment Oolel doit lire ce que l'écran affiche.

Oolel-Voices lit le wolof avec ses règles d'écriture (u = « ou », é ë ñ…), mais
certains noms — lieux de la ville, initials, tournures — lui échappent encore.
Ce lexique réécrit uniquement le texte envoyé à la voix : l'écran garde le nom
officiel (« Acapes »), la voix ne lit que la façon de le dire (« Akaapes »).

Format : « mot ou phrase affiché(e) » -> « orthographe parlée ». Le remplacement
se fait mot entier (jamais au cœur d'un autre mot) et sans tenir compte de la
casse ; une clé de plusieurs mots est remplacée en bloc, avant les mots seuls.
La substitution est faite en une seule passe : une valeur n'est jamais
ré-interprétée par une autre entrée du lexique.

En l'état : le lexique est vide, tant que les variantes proposées par
`notebooks/voix_test_prononciation_colab.ipynb` n'ont pas été écoutées.
Après l'écoute, remplir `LEXIQUE`, puis regénérer la liste complète des audios
(scripts/preparer_regen_oolel.py) et le notebook de génération
(scripts/preparer_notebook_oolel.py) : le texte final est calculé au moment de
préparer la liste, jamais au moment de l'app, qui ne joue que des audios
pré-générés.
"""

from __future__ import annotations

import re

# « écran » -> « orthographe parlée ». Vide pour l'instant : chaque entrée doit
# être validée à l'oreille (écoute comparative des deux variantes générées).
# Exemples du format attendu :
#   "Acapes": "Akaapes",            # mot seul
#   "Albeer Saroo": "Alber Saróo",  # phrase entière, renversée d'un coup
LEXIQUE: dict[str, str] = {}


def appliquer(texte: str) -> str:
    """Le texte tel que la voix doit le lire, une fois le lexique appliqué.

    Mot entier et insensible à la casse : « biis » dans « biisbiis » est
    intact, « Biis » en début de phrase est remplacé pareil. Les clés les plus
    longues passent d'abord pour qu'une phrase (« Alber Saroo ») ne se fasse pas
    couper par un de ses mots. Sans entrée (lexique vide), le texte revient tel
    quel : l'écran et la voix disent alors exactement la même chose.
    """
    if not texte or not LEXIQUE:
        return texte
    # Une seule passe : une valeur insérée ne peut pas repartir dans la
    # machine (sinon « bis » -> « biis » pourrait retomber sur « bis »).
    cles = sorted(LEXIQUE, key=len, reverse=True)
    patron = re.compile(
        r"(?<!\w)(?:%s)(?!\w)" % "|".join(re.escape(cle) for cle in cles),
        re.IGNORECASE,
    )
    par_minuscule = {cle.casefold(): cle for cle in LEXIQUE}
    return patron.sub(
        lambda trouve: LEXIQUE[par_minuscule[trouve.group().casefold()]],
        texte,
    )
