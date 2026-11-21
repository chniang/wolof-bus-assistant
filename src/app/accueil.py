"""Lot C7 : ce qui vient sous l'outil (comment ça marche, questions, partage, confidentialité).

L'outil (micro, onglets, résultat) reste en premier ; ces sections viennent
ensuite, sans animation, sans élément flottant, en une colonne qui tient dans
l'écran du téléphone (mêmes règles que le lot C6 : min-width:0, mots longs
coupés, aucune unité vh).

Aucun numéro ni e-mail ici : le partage passe par un lien wa.me sans
destinataire, et la suppression par le code GM- remis à la personne qui a
partagé l'app.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

try:  # import à plat (app.py) ou en paquet
    from app.partage import LIEN_APP, lien_partage
except ImportError:  # pragma: no cover
    from .partage import LIEN_APP, lien_partage

DOSSIER_ASSETS = Path(__file__).resolve().parents[2] / "assets"
QR_SVG = DOSSIER_ASSETS / "qr_guindima.svg"

# Icônes simples, au trait, aux couleurs GuindiMa (décoratives : le titre dit tout).
_ICONE = (
    "<svg viewBox='0 0 24 24' width='30' height='30' fill='none' stroke='#00853F' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' "
    "focusable='false'>{}</svg>"
)
ICONE_MICRO = _ICONE.format(
    "<rect x='9' y='3' width='6' height='11' rx='3'></rect>"
    "<path d='M5.5 11a6.5 6.5 0 0 0 13 0'></path><path d='M12 17.5V21'></path>"
)
ICONE_BUS = _ICONE.format(
    "<rect x='4' y='3' width='16' height='15' rx='4'></rect>"
    "<path d='M4 11h16'></path><circle cx='8.5' cy='14.5' r='1'></circle>"
    "<circle cx='15.5' cy='14.5' r='1'></circle><path d='M7 18v3M17 18v3'></path>"
)
ICONE_ECOUTE = _ICONE.format(
    "<path d='M4 9v6h4l5 4V5L8 9H4z'></path>"
    "<path d='M16.5 8.5a5 5 0 0 1 0 7'></path><path d='M19 6a8.5 8.5 0 0 1 0 12'></path>"
)

ETAPES = (
    ("01", ICONE_MICRO, "Dis ton trajet",
     "Appuie sur le micro et dis d'où tu pars et où tu vas, en wolof."),
    ("02", ICONE_BUS, "Vois ton bus",
     "GuindiMa te montre la ligne Dem Dikk ou Tata, où monter et où descendre."),
    ("03", ICONE_ECOUTE, "Écoute la réponse",
     "La réponse est lue en wolof. Dis-nous si la ligne est juste."),
)

SUPPRESSION = (
    "Pour la faire supprimer, envoie ton code GM- à la personne qui t'a partagé "
    "l'application."
)


def reponse_voix(collecte_active: bool) -> str:
    """« Ma voix est-elle gardée ? » : le même sens que la note grise sous la saisie."""
    if collecte_active:
        return (
            "Si tu parles, ta voix est gardée pour améliorer le wolof de GuindiMa, sans ton "
            "nom ni ton numéro. Pour qu'elle ne soit pas gardée, utilise l'onglet Écrire. "
            + SUPPRESSION
        )
    return "Non : ta voix n'est pas enregistrée. Elle sert seulement à comprendre ton trajet."


def questions(collecte_active: bool) -> tuple[tuple[str, str], ...]:
    return (
        ("Quelles lignes sont couvertes ?",
         "Les bus Dakar Dem Dikk et Tata (AFTU) de Dakar et de sa banlieue, d'après les "
         "données publiques des compagnies. Les cars rapides, Ndiaga Ndiaye, le BRT et le "
         "TER ne sont pas encore inclus."),
        ("Est-ce que c'est fiable ?",
         "Les lignes viennent des sources officielles et sont vérifiées. Les durées sont "
         "des estimations, données en fourchette. Si une ligne te semble fausse, réponds "
         "« Non » sous le résultat : ça nous aide à corriger."),
        ("Ma voix est-elle gardée ?", reponse_voix(collecte_active)),
        ("C'est gratuit ?", "Oui, gratuit et sans compte."),
        ("Mon quartier n'est pas reconnu, je fais quoi ?",
         "Dis un lieu connu tout près (marché, rond-point, station, mosquée, arrêt) ou "
         "utilise l'onglet Écrire."),
        ("Qui a créé GuindiMa ?",
         "TECH INNOV, une entreprise de Dakar fondée par Cheikh Niang."),
    )


def qr_en_ligne() -> str:
    """Le QR fourni (assets/qr_guindima.svg), inséré tel quel et mis à l'échelle.

    Le fichier n'a pas de viewBox : sans lui, réduire sa largeur rognerait le
    code au lieu de le réduire. On l'ajoute à partir de sa taille d'origine.
    """
    try:
        svg = QR_SVG.read_text(encoding="utf-8")
    except OSError:
        return ""
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    if "viewBox" not in svg:
        largeur = re.search(r'\swidth="(\d+(?:\.\d+)?)"', svg)
        hauteur = re.search(r'\sheight="(\d+(?:\.\d+)?)"', svg)
        if largeur and hauteur:
            svg = svg.replace("<svg ", f'<svg viewBox="0 0 {largeur.group(1)} {hauteur.group(1)}" ', 1)
    racine = re.match(r"<svg\b[^>]*>", svg)
    if racine is None:
        return ""
    # Sur la balise <svg> seulement : sa taille fixe part (le CSS la règle) et
    # sa classe d'origine (« segno ») rejoint la nôtre.
    balise = racine.group(0)
    origine = re.search(r'\sclass="([^"]*)"', balise)
    balise = re.sub(r'\s(?:width|height|class)="[^"]*"', "", balise)
    classes = "qr-guindima" + (f" {origine.group(1)}" if origine else "")
    balise = balise.replace(
        "<svg", f'<svg class="{classes}" role="img" aria-label="QR code vers GuindiMa"', 1
    )
    return balise + svg[racine.end():]


def _titre(texte: str) -> str:
    return f"<h2 class='titre-section-accueil'>{escape(texte)}</h2>"


def sections_accueil(collecte_active: bool) -> str:
    """Comment ça marche, questions fréquentes, partage : sous l'outil, avant le pied de page."""
    etapes = "".join(
        "<li class='etape'>"
        f"<span class='etape-numero'>{numero}</span>"
        f"<span class='etape-texte'><span class='etape-titre'>{icone}<b>{escape(titre)}</b></span>"
        f"{escape(texte)}</span>"
        "</li>"
        for numero, icone, titre, texte in ETAPES
    )
    faq = "".join(
        f"<details class='question'><summary>{escape(q)}</summary><p>{escape(r)}</p></details>"
        for q, r in questions(collecte_active)
    )
    message = f"GuindiMa : dis ton trajet en wolof, il te dit quel bus prendre à Dakar. {LIEN_APP}"
    partage = (
        f"<div class='partage-qr'>{qr_en_ligne()}</div>"
        "<p class='partage-texte'>Scanne ou partage le lien à tes proches</p>"
        f"<p class='partage-bouton'><a href='{escape(lien_partage(message), quote=True)}' "
        "target='_blank' rel='noopener'>Partager sur WhatsApp</a></p>"
    )
    return (
        "<section class='section-accueil' id='comment_ca_marche'>"
        f"{_titre('Comment ça marche')}<ol class='etapes'>{etapes}</ol></section>"
        "<section class='section-accueil' id='questions_frequentes'>"
        f"{_titre('Questions fréquentes')}{faq}</section>"
        "<section class='section-accueil' id='partage_guindima'>"
        f"{_titre('Partage GuindiMa')}{partage}</section>"
    )


def confidentialite(note_vie_privee: str, collecte_active: bool) -> str:
    """Le bloc dépliable « Confidentialité » du pied de page, et la ligne « Un problème ? »."""
    texte = note_vie_privee
    if collecte_active:
        texte = f"{texte} {SUPPRESSION}"
    return (
        "<details class='confidentialite' id='confidentialite_guindima'>"
        "<summary>Confidentialité</summary>"
        f"<p>{escape(texte)}</p></details>"
        "<p class='un-probleme'>Un problème ? Réponds « Non » sous ton résultat ou envoie ton "
        "code GM- à la personne qui t'a partagé l'app.</p>"
    )
