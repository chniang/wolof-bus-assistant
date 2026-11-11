"""Le partage d'un trajet sur WhatsApp.

Le texte est composé ici, sans HTML ni Gradio, pour que les tests vérifient
exactement ce que recevra le contact. Le lien wa.me, sans numéro, laisse
l'utilisateur choisir la personne à qui envoyer le message.
"""

from __future__ import annotations

from urllib.parse import quote

# L'app publiée, mise en lien dans chaque message partagé.
LIEN_APP = "https://huggingface.co/spaces/PythonMindset/guindima-ai"


def _bout(match: dict, cle: str, lieu_dit: str) -> str:
    """L'arrêt à nommer, ou le lieu dit avec un conseil si l'arrêt est loin.

    Un arrêt à plus de 600 m du lieu dit (``monte_a_vague``) n'est jamais
    écrit : le contact irait l'attendre à l'autre bout du quartier.
    """
    if match.get(f"{cle}_vague") and lieu_dit:
        numero = str(match.get("ligne", "")).replace("Ligne", "").strip()
        return f"{lieu_dit} (cherche l'arrêt de la ligne {numero} le plus proche)"
    return str(match.get(cle, ""))


def _phrase_bus(match: dict, depart: str = "", arrivee: str = "") -> str:
    """« Ligne 7 (Dakar Dem Dikk) : monte à Ouakam, descends à Palais 2. »"""
    return (
        f"{match.get('ligne', '')} ({match.get('compagnie', '')}) : "
        f"monte à {_bout(match, 'monte_a', depart)}, "
        f"descends à {_bout(match, 'descend_a', arrivee)}."
    )


def _lignes_changement(etapes, marches=(), depart: str = "", arrivee: str = "") -> list[str]:
    """Les bus numérotés, et ce qu'il faut faire entre deux bus.

    Même arrêt : un seul nom des deux côtés, celui où l'on descend, car les lignes
    l'écrivent différemment (« Rond Point Liberté 6 », « Rond-Point Liberté 6 »).
    Deux arrêts différents : le message dit où descendre, combien de minutes marcher
    et où prendre le bus suivant.  `marches` donne ces minutes, 0 pour le même arrêt.
    """
    morceaux = []
    precedent = None
    for i, etape in enumerate(etapes, start=1):
        marche = marches[i - 2] if 2 <= i <= len(marches) + 1 else 0
        if marche:
            morceaux.append(
                f"À pied : environ {marche} min jusqu'à {etape.get('monte_a', '')}."
            )
        elif precedent is not None:
            etape = {**etape, "monte_a": precedent.get("descend_a", "")}
        # Seuls les deux bouts portent un lieu dit : le changement est un
        # vrai arrêt du réseau, toujours nommé.
        morceaux.append(
            f"{i}. {_phrase_bus(etape, depart if i == 1 else '', arrivee if i == len(etapes) else '')}"
        )
        precedent = etape
    return morceaux


def texte_partage(
    depart: str,
    arrivee: str,
    resultat: dict,
    trajet: dict | None = None,
) -> str:
    """Le message WhatsApp d'un résultat, ou "" s'il n'y a pas de trajet.

    Un trajet direct liste les lignes proposées ; une correspondance les numérote
    dans l'ordre des deux bus. `trajet` permet de partager une possibilité précise
    quand l'app en propose plusieurs.
    """
    lignes = resultat.get("lignes") or []
    correspondances = resultat.get("correspondances") or []
    trajets_2 = resultat.get("trajets_2") or []
    if trajet is not None:
        etapes = trajet.get("etapes") or (trajet["etape_1"], trajet["etape_2"])
        morceaux = _lignes_changement(etapes, trajet.get("marches") or (), depart, arrivee)
    elif lignes:
        morceaux = [_phrase_bus(ligne, depart, arrivee) for ligne in lignes]
    elif correspondances:
        etapes = correspondances[0]
        morceaux = _lignes_changement(
            (etapes["etape_1"], etapes["etape_2"]),
            etapes.get("marches") or (),
            depart,
            arrivee,
        )
    elif trajets_2:
        morceaux = _lignes_changement(
            trajets_2[0]["etapes"], trajets_2[0].get("marches") or (), depart, arrivee
        )
    else:
        return ""
    return "\n".join([f"🚌 GuindiMa : {depart} → {arrivee}", *morceaux, LIEN_APP])


def lien_partage(texte: str) -> str:
    """Le lien wa.me qui pré-remplit le message, accents et retours encodés."""
    return f"https://wa.me/?text={quote(texte, safe='')}"


def bouton_partage(
    depart: str,
    arrivee: str,
    resultat: dict,
    trajet: dict | None = None,
) -> str:
    """Le bouton discret sous une carte, ou "" quand aucun trajet n'est trouvé."""
    texte = texte_partage(depart, arrivee, resultat, trajet)
    if not texte:
        return ""
    lien = lien_partage(texte)
    return (
        "<div style='margin-top:14px;text-align:right;'>"
        f"<a href='{lien}' target='_blank' rel='noopener' "
        "style='display:inline-block;background:#EAF6EF;color:#0B6B37;"
        "border:1px solid #C7E6D4;border-radius:20px;padding:10px 16px;"
        "font-size:14px;font-weight:600;text-decoration:none;'>"
        "Partager sur WhatsApp</a></div>"
    )
