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

Après l'écoute des variantes de `notebooks/voix_test_prononciation_colab.ipynb`,
le locuteur natif a rempli `LEXIQUE`. Rejouer ensuite la liste complète des
audios (scripts/preparer_regen_oolel.py pour le CSV, puis
scripts/preparer_notebook_oolel.py pour le notebook) : le texte final est
calculé au moment de préparer la liste, jamais au moment de l'app, qui ne joue
que des audios pré-générés.
"""

from __future__ import annotations

import re

# « écran » -> « orthographe parlée ». Choix validés à l'oreille par un locuteur
# natif, après l'écoute comparative des variantes du notebook de test (biis/bis,
# Taaf/Taf, Akapes…) : le mot entier remplace la lecture à l'aveugle d'Oolel.
LEXIQUE: dict[str, str] = {
    # « bus » se fait dire « biis » : c'est le mot wolof, pas une lettre lue.
    "bus": "biis",
    # Les majuscules isolées ont une lecture hasardeuse chez Oolel ; on écrit
    # « Taf Taf » comme on le dit.
    "TAF TAF": "Taf Taf",
    # Lieux dits : orthographes que la voix sait lire, validées à l'écoute.
    "Acapes": "Akaapes",
    "Albert Sarraut": "Alber Saroo",
    "ASECNA": "Aseknaa",
}


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
