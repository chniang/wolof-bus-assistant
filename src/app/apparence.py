"""Apparence de GuindiMa : thème clair forcé, contrôles lisibles, globe micro, étoiles.

Lot C (design), inspiré de l'interface mobile de Koumba : une colonne de 480 px
au plus, fond blanc, accents vert et jaune GuindiMa, cartes bordées tout autour
avec la livrée réelle du bus en bande (Tata : rayures bleues, Dem Dikk : vert,
jaune, rouge).

Tout est local : aucune police ni librairie téléchargée (le thème Gradio
« Soft » chargeait Montserrat depuis Google Fonts). Le globe est un canvas
dessiné à la main ; il pilote le composant d'enregistrement Gradio caché en
dessous, si bien que la chaîne audio (transcription, collecte, code GM-) ne
change pas.
"""

from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Couleurs (contrastes calculés sur fond blanc, WCAG 2.1)
# --------------------------------------------------------------------------- #
VERT = "#00853F"  # 4,7:1 : texte AA, et blanc sur vert 4,7:1
VERT_PROFOND = "#006B33"  # 6,6:1 : texte secondaire vert, contour du bouton principal
JAUNE = "#FDEF42"  # remplissages seulement (halo de focus, particules), jamais du texte
JAUNE_PARTICULE = "#E9C400"
ENCRE = "#11251A"  # 15,9:1
TEXTE_DOUX = "#46594D"  # 7,5:1
CONTOUR = "#5E7A69"  # 4,7:1 : contour des champs et boutons (>= 3:1 exigé)
LIGNE = "#D3DED7"  # bordure neutre des cartes (décor, pas un contrôle)
FOND = "#FFFFFF"
FOND_DOUX = "#F6F9F7"
ETOILE_PLEINE = "#B07D00"  # 3,6:1 : étoile choisie
TATA_BLEU = "#1F5FAD"
TATA_BLEU_CLAIR = "#4F8BD0"
DDD_ROUGE = "#E31B23"

# Polices déjà présentes sur les téléphones (Roboto sur Android, la grande
# majorité à Dakar) : rien à télécharger.
POLICES = ["Roboto", "Segoe UI", "Helvetica Neue", "Arial", "system-ui", "sans-serif"]


# --------------------------------------------------------------------------- #
# Livrées des cartes
# --------------------------------------------------------------------------- #
def livree(compagnie: str) -> str:
    """La bande de couleur de la compagnie, en haut de la carte.

    Tata : les rayures bleues des bus AFTU. Dem Dikk : vert, jaune, rouge.
    Autre (à pied) : aucune bande, la bordure neutre suffit.
    """
    nom = (compagnie or "").lower()
    if "tata" in nom or "aftu" in nom:
        fond = (
            f"repeating-linear-gradient(135deg,{TATA_BLEU} 0 14px,"
            f"{TATA_BLEU_CLAIR} 14px 19px,{FOND} 19px 23px)"
        )
        hauteur = 8
    elif "dem dikk" in nom:
        fond = f"linear-gradient(90deg,{VERT} 0 33.33%,{JAUNE} 33.33% 66.66%,{DDD_ROUGE} 66.66% 100%)"
        hauteur = 6
    else:
        return ""
    return (
        f"<div class='guindima-livree' aria-hidden='true' "
        f"style='height:{hauteur}px;background:{fond};'></div>"
    )


def pastille_compagnie(compagnie: str) -> str:
    """« Tata AFTU » sur bleu, « Dakar Dem Dikk » sur vert : la compagnie en un coup d'œil.

    Le nom complet, celui des panneaux et du bouton de compagnie.
    """
    nom = (compagnie or "").lower()
    if "tata" in nom or "aftu" in nom:
        texte, fond = "Tata AFTU", TATA_BLEU
    elif "dem dikk" in nom:
        texte, fond = "Dakar Dem Dikk", VERT
    else:
        return ""
    return (
        f"<span style='display:inline-block;padding:3px 10px;border-radius:999px;"
        f"background:{fond};color:{FOND};font-size:13px;font-weight:800;'>{texte}</span>"
    )


def ouvrir_carte() -> str:
    """Le cadre d'une carte : bordure neutre sur les quatre côtés, coins arrondis."""
    return (
        f"<div class='guindima-carte' style='border:1.5px solid {LIGNE};border-radius:16px;"
        f"margin:10px 0;background:{FOND};overflow:hidden;max-width:100%;box-sizing:border-box;"
        f"overflow-wrap:anywhere;"
        f"box-shadow:0 2px 10px rgba(17,37,26,0.06);'>"
    )


# --------------------------------------------------------------------------- #
# Thème clair forcé
# --------------------------------------------------------------------------- #
# Gradio met la classe « dark » sur <body> d'après ?__theme=, le réglage
# enregistré ou le mode du téléphone. Ce script passe avant Gradio : il fixe
# ?__theme=light dans l'adresse (sans recharger) puis retire « dark » dès
# qu'elle réapparaît. Le CSS plus bas redonne aussi les couleurs claires sous
# .dark, au cas où le script n'aurait pas tourné.
HEAD_CLAIR = """
<meta name="color-scheme" content="light only">
<meta name="theme-color" content="#FFFFFF">
<script>
(function () {
  try {
    var adresse = new URL(window.location.href);
    if (adresse.searchParams.get("__theme") !== "light") {
      adresse.searchParams.set("__theme", "light");
      window.history.replaceState(window.history.state, "", adresse.toString());
    }
  } catch (e) {}
  // Seulement si « dark » est là : classList.remove réécrit l'attribut class
  // même quand la classe est absente, ce qui relancerait l'observateur sans
  // fin (page figée, vu en test local).
  function clair() {
    var sombres = document.querySelectorAll(".dark");
    for (var i = 0; i < sombres.length; i++) { sombres[i].classList.remove("dark"); }
  }
  clair();
  var veille = new MutationObserver(clair);
  veille.observe(document.documentElement, { attributes: true, attributeFilter: ["class"], childList: true });
  // Gradio insère ce <head> après le chargement de sa configuration, donc
  // souvent après DOMContentLoaded : on veille <body> tout de suite s'il existe.
  function veillerCorps() {
    clair();
    veille.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }
  if (document.body) { veillerCorps(); }
  else { document.addEventListener("DOMContentLoaded", veillerCorps); }
})();
</script>
"""

# --------------------------------------------------------------------------- #
# CSS de l'application
# --------------------------------------------------------------------------- #
CSS_GUINDIMA = r"""
:root, .dark, body.dark {
    color-scheme: light only;
    --body-background-fill: #FFFFFF !important;
    --background-fill-primary: #FFFFFF !important;
    --background-fill-secondary: #F6F9F7 !important;
    --block-background-fill: #FFFFFF !important;
    --body-text-color: #11251A !important;
    --body-text-color-subdued: #46594D !important;
    --block-label-text-color: #11251A !important;
    --block-title-text-color: #11251A !important;
    --block-info-text-color: #46594D !important;
    --input-background-fill: #FFFFFF !important;
    --input-background-fill-focus: #FFFFFF !important;
    --input-border-color: #5E7A69 !important;
    --input-border-color-focus: #00853F !important;
    --input-placeholder-color: #5E6E64 !important;
    --border-color-primary: #D3DED7 !important;
    --link-text-color: #006B33 !important;
    --neutral-950: #11251A !important;
}
html, body, .dark body, body.dark { background: #FFFFFF !important; color: #11251A !important; }
/* Lot C6 : sur Chrome Android (~412 px), dès qu'une réponse s'affichait, un
   élément plus large que l'écran élargissait toute la page (titre, bouton
   « Dem Dikk », note grise et cartes coupés à droite). Chaque bloc rentre
   désormais dans la largeur (min-width:0, max-width:100%, mots longs coupés) ;
   overflow-x:hidden sur html, body et le conteneur n'est que le dernier filet. */
html, body { overflow-x: hidden !important; max-width: 100%; }
.gradio-container,
.gradio-container .main,
.gradio-container .contain,
.gradio-container .column,
.gradio-container .row,
.gradio-container .block,
.gradio-container .form,
.gradio-container .tabitem,
.gradio-container .tabs,
.gradio-container .prose,
.gradio-container .html-container {
    min-width: 0 !important;
    max-width: 100%;
    box-sizing: border-box;
}
.gradio-container { overflow-x: hidden !important; }
.gradio-container .prose,
.gradio-container .guindima-carte,
.gradio-container .guindima-carte *,
#note_vie_privee,
#accueil_guindima .salut,
#accueil_guindima .sous-titre {
    overflow-wrap: anywhere;
    word-break: normal;
}
.gradio-container .guindima-carte { max-width: 100%; }
.gradio-container .prose img,
.gradio-container .prose audio,
.gradio-container .prose details { max-width: 100%; }

/* Une colonne de téléphone, même sur ordinateur. */
.gradio-container {
    width: 100% !important;
    max-width: 480px !important;
    margin: 0 auto !important;
    padding: 12px 14px 28px !important;
    background: #FFFFFF !important;
    color: #11251A !important;
}
.gradio-container .prose, .gradio-container .prose * { color: inherit; }
/* Lot C2 : à 360 px, la première lettre de « Ton code », « l'application » ou
   « OpenStreetMap » était rognée. Les blocs Markdown sans cadre gardent
   overflow:auto et collent au bord : la jambe gauche d'un glyphe dépassait et
   était coupée. On les laisse déborder et on leur donne un peu d'air. */
.gradio-container .block.hide-container { overflow: visible !important; }
.gradio-container .prose { padding-left: 3px !important; padding-right: 3px !important; }
.gradio-container .block.hide-container > .prose,
.gradio-container .block.hide-container [data-testid="markdown"] { overflow-wrap: anywhere; }

/* Accueil : le logo dans un rond blanc, le nom dans une pastille verte. */
#accueil_guindima { padding: 4px 2px 6px; }
#accueil_guindima .entete {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: nowrap;
    min-width: 0;
}
#accueil_guindima .logo-rond {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 58px;
    height: 58px;
    border-radius: 50%;
    background: #FFFFFF;
    border: 1.5px solid #D3DED7;
    box-shadow: 0 4px 12px rgba(17, 37, 26, 0.10);
}
#accueil_guindima .logo-rond svg { width: 44px; height: 44px; display: block; }
#accueil_guindima .marque {
    display: inline-block;
    min-width: 0;
    margin: 0;
    padding: 7px 20px 8px;
    border-radius: 999px;
    background: #00853F;
    color: #FFFFFF;
    font-size: 30px;
    font-weight: 850;
    letter-spacing: -0.5px;
    line-height: 1.1;
    white-space: nowrap;
    box-shadow: 0 4px 12px rgba(0, 133, 63, 0.28);
}
#accueil_guindima .salut {
    color: #11251A;
    font-size: 20px;
    font-weight: 750;
    line-height: 1.25;
    margin: 8px 0 2px;
}
#accueil_guindima .sous-titre { color: #46594D; font-size: 15px; line-height: 1.4; margin: 0; }

/* 1. Champs : un contour net, des coins arrondis, un focus qu'on voit. */
.gradio-container textarea,
.gradio-container input[type="text"],
.gradio-container input[type="number"],
.gradio-container input[type="search"] {
    background: #FFFFFF !important;
    border: 2px solid #5E7A69 !important;
    border-radius: 12px !important;
    color: #11251A !important;
    font-size: 16px !important;
    min-height: 48px;
    box-shadow: none !important;
}
.gradio-container textarea { padding: 12px 14px !important; }
.gradio-container .wrap-inner:has(input) {
    border: 2px solid #5E7A69 !important;
    border-radius: 12px !important;
    background: #FFFFFF !important;
    min-height: 48px;
}
.gradio-container .wrap-inner:has(input) input { border: 0 !important; min-height: 0; }
.gradio-container textarea:focus,
.gradio-container input:focus,
.gradio-container .wrap-inner:focus-within {
    border-color: #00853F !important;
    outline: 3px solid #FDEF42 !important;
    outline-offset: 1px;
}

/* 1. Boutons : contour visible, cible tactile de 48 px, appui visible. */
.gradio-container button.primary,
.gradio-container button.secondary,
.gradio-container button.lg,
.gradio-container button.sm {
    min-height: 48px !important;
    border-radius: 12px !important;
    font-size: 17px !important;
    font-weight: 800 !important;
    touch-action: manipulation;
}
.gradio-container button.primary {
    background: #00853F !important;
    border: 2px solid #006B33 !important;
    color: #FFFFFF !important;
}
@media (hover: hover) and (pointer: fine) {
    .gradio-container button.primary:hover { background: #006B33 !important; }
}
.gradio-container button.secondary {
    background: #FFFFFF !important;
    border: 2px solid #5E7A69 !important;
    color: #11251A !important;
}
@media (hover: hover) and (pointer: fine) {
    .gradio-container button.secondary:hover { background: #F6F9F7 !important; border-color: #00853F !important; }
}
.gradio-container button:active { transform: translateY(1px) scale(0.99); }
.gradio-container button:focus-visible {
    outline: 3px solid #00853F !important;
    outline-offset: 2px;
    box-shadow: 0 0 0 6px #FDEF42 !important;
}

/* Onglets Parler / Écrire : grands, l'onglet actif souligné en vert. */
.gradio-container .tab-wrapper button,
.gradio-container [role="tab"] {
    min-height: 48px;
    font-size: 17px !important;
    font-weight: 750 !important;
    color: #46594D !important;
}
.gradio-container [role="tab"][aria-selected="true"] { color: #006B33 !important; }

/* Compagnie : trois pastilles bordées, la choisie pleine. */
#compagnie_guindima .wrap { gap: 6px !important; flex-wrap: wrap !important; }
#compagnie_guindima label {
    flex: 1 1 88px;
    justify-content: center;
    min-height: 48px;
    min-width: 0 !important;
    padding: 0 8px !important;
    white-space: nowrap;
    border: 2px solid #5E7A69 !important;
    border-radius: 999px !important;
    background: #FFFFFF !important;
    color: #11251A !important;
    font-weight: 750 !important;
    cursor: pointer;
}
#compagnie_guindima label:has(input:checked) {
    background: #00853F !important;
    border-color: #006B33 !important;
    color: #FFFFFF !important;
}
#compagnie_guindima label:has(input:checked) * { color: #FFFFFF !important; }
/* Le point du bouton radio prenait la place de « Dem Dikk » à 360 px : la
   pastille pleine dit déjà le choix. L'input reste là pour le clavier. */
#compagnie_guindima label { position: relative; }
#compagnie_guindima label input {
    position: absolute !important;
    inset: 0;
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    opacity: 0;
    cursor: pointer;
}
#compagnie_guindima label span { margin: 0 !important; font-size: 15px !important; }
#compagnie_guindima label:has(input:focus-visible) { outline: 3px solid #FDEF42; outline-offset: 2px; }

/* Le panneau d'avis : fond doux et bordure neutre tout autour, comme les cartes. */
#panneau_avis {
    background: #F6F9F7 !important;
    border: 1.5px solid #D3DED7 !important;
    border-radius: 16px !important;
    padding: 12px !important;
    gap: 10px !important;
}
#panneau_avis > *, #panneau_avis .styler, #panneau_avis .form { background: transparent !important; border: 0 !important; }
#panneau_avis .prose { font-size: 17px; }
/* Lot C3 : confirmation sous le contrôle cliqué (vert, ✓), erreur en orange. */
#panneau_avis .retour-ok,
#panneau_avis .retour-erreur {
    margin: 2px 0 0;
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 750;
    line-height: 1.35;
}
#panneau_avis .retour-ok { background: #E8F5EE; border: 1.5px solid #9BD4B5; color: #064E2B; }
#panneau_avis .retour-erreur { background: #FFF4E5; border: 1.5px solid #E8A84A; color: #7A3E00; }
#retour_bas .retour-ok, #retour_bas .retour-erreur { margin-top: 6px; }
#retour_avis, #retour_etoiles, #retour_bas { padding: 0 !important; min-height: 0 !important; }

/* Les blocs (accordéon, groupe d'avis) : bordure neutre tout autour. */
.gradio-container .block,
.gradio-container .form {
    border-color: #D3DED7 !important;
    border-radius: 16px !important;
}

/* Micro Gradio piloté par le globe : ses boutons natifs restent dans le DOM
   (le globe les déclenche) mais sont cachés, seulement si le globe tourne. */
body.globe-guindima-actif #micro_guindima .record-button,
body.globe-guindima-actif #micro_guindima .stop-button,
body.globe-guindima-actif #micro_guindima .stop-button-paused,
body.globe-guindima-actif #micro_guindima .pause-button,
body.globe-guindima-actif #micro_guindima .resume-button {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    min-height: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    clip-path: inset(50%) !important;
    opacity: 0 !important;
}
#micro_guindima {
    border: 1.5px solid #D3DED7 !important;
    border-radius: 16px !important;
    background: #FFFFFF !important;
}
/* Lot C2 : quand le globe tourne, tout le cadre natif disparaît à l'œil. Il
   reste monté dans la page (le globe clique ses boutons, l'enregistrement et
   la chaîne audio passent toujours par lui). Sans globe (script bloqué), ou
   après « Micro classique », la classe est absente et le cadre revient. */
body.globe-guindima-actif #micro_guindima {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden !important;
    clip-path: inset(50%) !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
#micro_guindima .mic-select { display: none !important; }
/* La croix du composant Audio efface l'enregistrement avant qu'il soit traité.
   Le DOM Gradio 6.30.0 la rend en <button class="icon-button" aria-label="Effacer">. */
#micro_guindima .icon-button-wrapper.top-panel button[aria-label="Effacer"],
#micro_guindima .icon-button-wrapper.top-panel button[aria-label="Clear"] {
    display: none !important;
}

/* 3. Étoiles : cinq boutons radio habillés en étoiles, 48 px chacun. */
#etoiles_guindima { border: 0 !important; background: transparent !important; padding: 0 !important; }
/* Lot C7 : à 360 px, cinq étoiles de 48 px plus leurs espaces dépassaient le
   panneau (la 5e était rognée) : elles se partagent la largeur, 56 px au plus. */
#etoiles_guindima .wrap { display: flex !important; flex-wrap: nowrap !important; gap: 0 !important; }
#etoiles_guindima label {
    position: relative;
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    flex: 1 1 0;
    min-width: 0 !important;
    max-width: 56px;
    min-height: 48px;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: 12px !important;
    background: transparent !important;
    box-shadow: none !important;
    cursor: pointer;
}
#etoiles_guindima label input {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    opacity: 0;
    cursor: pointer;
}
#etoiles_guindima label span {
    position: absolute !important;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
#etoiles_guindima label::before {
    content: "☆";
    color: #5E7A69;
    font-size: 36px;
    line-height: 1;
}
#etoiles_guindima label:has(input:focus-visible) { outline: 3px solid #00853F; outline-offset: 1px; }
@@ETOILES@@

/* Trajets fréquents : toute la ligne d'une option est cliquable. Les options
   sont parfois portées hors de #trajets_frequents (position:fixed) : on cible
   aussi .options, il n'y a qu'un seul Dropdown dans cette interface. */
#trajets_frequents .item,
.options .item {
    align-items: center;
    box-sizing: border-box;
    cursor: pointer;
    display: flex;
    justify-content: flex-start;
    min-height: 48px;
    padding: 10px 12px;
    width: 100%;
}
#trajets_frequents .item.selected,
.options .item.selected {
    background: #E8F5EE;
    color: #064E2B;
}
@media (hover: hover) and (pointer: fine) {
    #trajets_frequents .item:hover,
    .options .item:hover { background: #E8F5EE; color: #064E2B; }
}
.options { background: #FFFFFF !important; border: 2px solid #5E7A69 !important; border-radius: 12px !important; }

/* Lot C5 : « Réponse en wolof » tient dans la largeur. WaveSurfer dessine
   20 px par seconde : une réponse de 29 s faisait 580 px, d'où une barre de
   défilement à 360 px. Son conteneur est dans un shadow DOM, joignable par
   ::part(scroll) ; il continue de suivre la lecture (défilement automatique). */
#voix_guindima { max-width: 100% !important; min-width: 0 !important; overflow: hidden !important; }
#voix_guindima ::part(scroll) { overflow-x: hidden !important; scrollbar-width: none; }
#voix_guindima audio, #voix_guindima .component-wrapper { max-width: 100% !important; }

/* Lot C5 : durée totale d'un trajet avec changement. */
.gradio-container .duree-totale {
    margin: 8px 0 4px;
    padding: 10px 14px;
    border: 1.5px solid #D3DED7;
    border-radius: 12px;
    background: #F6F9F7;
    color: #11251A;
    font-size: 16px;
    font-weight: 750;
}

@media (max-width: 380px) {
    .gradio-container { padding: 10px 10px 24px !important; }
    #accueil_guindima .marque { font-size: 26px; padding: 6px 16px 7px; }
    #accueil_guindima .logo-rond { width: 52px; height: 52px; }
    #accueil_guindima .salut { font-size: 18px; }
}
@media (prefers-reduced-motion: reduce) {
    .gradio-container button:active { transform: none; }
}
"""


def _css_etoiles() -> str:
    """Les étoiles jusqu'à la note choisie deviennent pleines : l'écran suit la valeur cochée.

    Lot C5 (bug vu dans le dataset : 5 étoiles à l'écran, « etoiles »: 1 dans
    avis.json). Le survol remplissait aussi les étoiles (content « ★ ») ; sur
    téléphone, Safari applique alors le premier toucher comme un simple survol,
    sans clic : l'écran montrait 5 étoiles alors que la note cochée restait 1.
    Le survol n'existe plus que sur les appareils à souris, et il ne change que
    la couleur du contour, jamais le dessin des étoiles.
    """
    regles = []
    for n in range(1, 6):
        regles.append(
            f"#etoiles_guindima .wrap:has(label:nth-child({n}) input:checked) "
            f"label:nth-child(-n+{n})::before {{ content: \"★\"; color: {ETOILE_PLEINE}; }}"
        )
    regles.append("@media (hover: hover) and (pointer: fine) {")
    for n in range(1, 6):
        regles.append(
            f"    #etoiles_guindima .wrap:has(label:nth-child({n}):hover) "
            f"label:nth-child(-n+{n})::before {{ color: {ETOILE_PLEINE}; }}"
        )
    regles.append("}")
    return "\n".join(regles)


CSS_GUINDIMA = CSS_GUINDIMA.replace("@@ETOILES@@", _css_etoiles())
CSS_ACCUEIL = r"""
/* Lot C7 : sections sous l'outil. Une colonne, bordures neutres tout autour,
   aucune animation, rien de flottant, rien qui dépasse la largeur. */
#accueil_sections, #accueil_sections * { min-width: 0; box-sizing: border-box; overflow-wrap: anywhere; }
#accueil_sections { margin-top: 18px; }
#accueil_sections .section-accueil {
    margin: 0 0 14px;
    padding: 14px 16px;
    border: 1.5px solid #D3DED7;
    border-radius: 16px;
    background: #FFFFFF;
}
#accueil_sections .titre-section-accueil {
    margin: 0 0 10px;
    color: #11251A;
    font-size: 20px;
    font-weight: 800;
    line-height: 1.25;
}
#accueil_sections .etapes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
#accueil_sections .etape { display: flex; align-items: flex-start; gap: 10px; }
#accueil_sections .etape-numero {
    flex: 0 0 auto;
    padding: 2px 9px;
    border-radius: 999px;
    background: #00853F;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 800;
    line-height: 1.6;
}
#accueil_sections .etape-texte { flex: 1 1 auto; color: #46594D; font-size: 15px; line-height: 1.4; }
#accueil_sections .etape-titre { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }
#accueil_sections .etape-titre svg { flex: 0 0 26px; width: 26px; height: 26px; }
#accueil_sections .etape-titre b { color: #11251A; font-size: 16px; }
#accueil_sections details.question { border-top: 1px solid #E3EAE6; }
#accueil_sections details.question:first-of-type { border-top: 0; }
#accueil_sections details summary,
#pied_guindima details summary {
    min-height: 48px;
    display: flex;
    align-items: center;
    cursor: pointer;
    color: #11251A;
    font-size: 16px;
    font-weight: 750;
}
#accueil_sections details p,
#pied_guindima details p { margin: 0 0 12px; color: #46594D; font-size: 15px; line-height: 1.45; }
#accueil_sections .partage-qr { text-align: center; }
#accueil_sections .qr-guindima { display: block; width: 100%; max-width: 180px; height: auto; margin: 4px auto; }
#accueil_sections .partage-texte { margin: 6px 0; text-align: center; color: #46594D; font-size: 15px; }
#accueil_sections .partage-bouton { margin: 8px 0 2px; text-align: center; }
#accueil_sections .partage-bouton a {
    display: inline-flex;
    align-items: center;
    min-height: 48px;
    padding: 0 18px;
    border: 2px solid #006B33;
    border-radius: 999px;
    background: #00853F;
    color: #FFFFFF !important;
    font-size: 16px;
    font-weight: 800;
    text-decoration: none;
}
#accueil_sections .partage-bouton a:focus-visible,
#accueil_sections details summary:focus-visible,
#pied_guindima details summary:focus-visible { outline: 3px solid #00853F; outline-offset: 2px; }
#pied_guindima details.confidentialite { margin: 8px auto 2px; text-align: left; }
#pied_guindima details.confidentialite summary { justify-content: center; font-size: 14px; color: #46594D; }
#pied_guindima .un-probleme { margin: 4px 0 0; color: #46594D; font-size: 13px; }
"""
CSS_GUINDIMA = CSS_GUINDIMA + CSS_ACCUEIL

# Lot C2 : logo (assets/logo_guindima.svg), dessiné pour l'app : un bus vu de
# face, vert GuindiMa, pare-brise jaune, et une bulle de voix. Il est inséré en
# ligne (pas d'URL à servir) ; s'il manque, l'en-tête garde la pastille seule.
DOSSIER_ASSETS = Path(__file__).resolve().parents[2] / "assets"
LOGO_SVG = DOSSIER_ASSETS / "logo_guindima.svg"
FAVICON = DOSSIER_ASSETS / "favicon_guindima.svg"


def logo_en_ligne() -> str:
    """Le SVG du logo prêt à insérer dans l'en-tête (décoratif : le nom est écrit à côté)."""
    try:
        svg = LOGO_SVG.read_text(encoding="utf-8")
    except OSError:
        return ""
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r"<title[^>]*>.*?</title>", "", svg, flags=re.S)
    svg = re.sub(r'\s(?:role|aria-labelledby)="[^"]*"', "", svg)
    return svg.replace("<svg ", '<svg class="logo-guindima" aria-hidden="true" focusable="false" ', 1).strip()


ACCUEIL_HTML = (
    "<div class='entete'>"
    f"<span class='logo-rond'>{logo_en_ligne()}</span>"
    "<p class='marque'>GuindiMa</p>"
    "</div>"
    "<p class='salut'>Wax ma fi nga jëm, ma won la bus bi.</p>"
    "<p class='sous-titre'>Dis ton trajet en wolof : je te montre le bus à prendre à Dakar.</p>"
)

# --------------------------------------------------------------------------- #
# 2. Le globe micro
# --------------------------------------------------------------------------- #
# Lot C7 : sous « Bës te wax », ce que l'usager doit savoir avant de parler.
PROMESSE = "Gratuit · sans inscription · en wolof"
# Lot G0 : pendant la transcription (jusqu'à 30 s sur le CPU de secours), la
# même ligne dit qu'on attend, puis reprend la promesse.
ATTENTE = "⏳ Je t'écoute… (jusqu'à 30 secondes)"
# Lot G1 : si aucune réponse n'arrive, le globe le dit au lieu de revenir en silence.
SANS_REPONSE = "Pas de réponse. Réessaie, ou utilise l'onglet Écrire."
DELAI_SANS_REPONSE_MS = 60000
TEXTES_GLOBE = {
    "repos": "Bës te wax",
    "ecoute": "Maa ngi lay déglu…",
    "traitement": "Maa ngi xool…",
}
ARIA_GLOBE = {
    "repos": "Appuie pour parler : dis ton trajet en wolof",
    "ecoute": "Appuie pour arrêter l'enregistrement",
    "traitement": "Recherche du bus en cours",
}

# Gabarit gr.HTML (chaîne de gabarit JS) : ni accent grave ni « ${ » ici.
GLOBE_HTML = f"""
<div class="globe-zone" data-etat="repos">
  <button type="button" class="globe" aria-label="{ARIA_GLOBE['repos']}" aria-pressed="false">
    <canvas class="globe-anneau" aria-hidden="true"></canvas>
    <span class="globe-coeur" aria-hidden="true">
      <svg class="icone icone-micro" viewBox="0 0 24 24" width="44" height="44" fill="none"
           stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="3" width="6" height="11" rx="3"></rect>
        <path d="M5.5 11a6.5 6.5 0 0 0 13 0"></path>
        <path d="M12 17.5V21"></path>
      </svg>
      <svg class="icone icone-stop" viewBox="0 0 24 24" width="38" height="38" fill="#FFFFFF">
        <rect x="6" y="6" width="12" height="12" rx="2.5"></rect>
      </svg>
      <svg class="icone icone-attente" viewBox="0 0 24 24" width="44" height="44" fill="#FFFFFF">
        <circle cx="6" cy="12" r="2.2"></circle><circle cx="12" cy="12" r="2.2"></circle>
        <circle cx="18" cy="12" r="2.2"></circle>
      </svg>
    </span>
  </button>
  <p class="globe-etat" aria-live="polite">{TEXTES_GLOBE['repos']}</p>
  <p class="globe-promesse">{PROMESSE}</p>
  <button type="button" class="globe-secours">Problème de micro ? Micro classique</button>
</div>
"""

GLOBE_CSS = """
/* Lot C6 : zone de taille fixe, isolée (contain) : rien de ce qui s'y passe
   ne change la taille ou la place des autres éléments. */
.globe-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 326px;
  padding: 6px 0 2px;
  contain: layout paint;
  overflow: hidden;
}
.globe-zone[data-secours="oui"] { height: 278px; }
.globe {
  position: relative;
  flex: 0 0 212px;
  width: 212px;
  height: 212px;
  contain: layout paint;
  border: 0;
  border-radius: 50%;
  padding: 0;
  background: transparent;
  cursor: pointer;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.globe:focus-visible { outline: 3px solid #00853F; outline-offset: 4px; box-shadow: 0 0 0 10px #FDEF42; }
.globe-anneau { position: absolute; inset: 0; width: 100%; height: 100%; }
.globe-coeur {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 116px;
  height: 116px;
  margin: -58px 0 0 -58px;
  border-radius: 50%;
  background: #00853F;
  border: 4px solid #FFFFFF;
  box-shadow: 0 0 0 2px #006B33, 0 10px 24px rgba(0, 133, 63, 0.28);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 160ms ease, opacity 160ms ease;
}
.globe:active .globe-coeur { transform: scale(0.96); }
.globe-zone[data-etat="ecoute"] .globe-coeur { background: #006B33; }
.icone { display: none; }
.globe-zone[data-etat="repos"] .icone-micro,
.globe-zone[data-etat="ecoute"] .icone-stop,
.globe-zone[data-etat="traitement"] .icone-attente { display: block; }
.globe-zone[data-etat="traitement"] .globe { cursor: progress; }
.globe-etat {
  margin: 4px 0 0;
  height: 1.4em;
  line-height: 1.4em;
  white-space: nowrap;
  color: #11251A;
  font-size: 19px;
  font-weight: 750;
  text-align: center;
}
.globe-promesse {
  margin: 2px 0 0;
  height: 1.4em;
  line-height: 1.4em;
  color: #46594D;
  font-size: 14px;
  text-align: center;
  white-space: nowrap;
}
/* Secours discret : révèle le micro Gradio classique (et le dépôt d'un fichier). */
.globe-secours {
  min-height: 48px;
  margin-top: 2px;
  padding: 0 12px;
  border: 0 !important;
  border-radius: 8px;
  background: transparent !important;
  box-shadow: none !important;
  color: #006B33;
  font-size: 14px;
  white-space: nowrap;
  font-weight: 650;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.globe-secours:focus-visible { outline: 3px solid #00853F; outline-offset: 2px; border-radius: 8px; }
.globe-zone[data-secours="oui"] .globe-secours { display: none; }
@media (prefers-reduced-motion: reduce) {
  .globe-coeur { transition: none; }
  .globe:active .globe-coeur { transform: none; }
}
"""

# Exécuté par gr.HTML au chargement (`element` = la racine du composant).
GLOBE_JS = r"""
const zone = element.querySelector('.globe-zone');
const bouton = element.querySelector('.globe');
const etiquette = element.querySelector('.globe-etat');
const promesse = element.querySelector('.globe-promesse');
const PROMESSE = __PROMESSE__;
const ATTENTE = __ATTENTE__;
const SANS_REPONSE = __SANS_REPONSE__;
const toile = element.querySelector('.globe-anneau');
const TEXTES = __TEXTES__;
const ARIA = __ARIA__;
const lent = window.matchMedia('(prefers-reduced-motion: reduce)');
let etat = 'repos';
let depuis = 0;
let empreinte = '';

document.body.classList.add('globe-guindima-actif');
const secours = element.querySelector('.globe-secours');
const lancement = performance.now();

// Secours : le cadre natif du micro revient (enregistrement classique, dépôt
// d'un fichier). Sur demande, ou tout seul si le micro Gradio est introuvable.
function micro_classique() {
  document.body.classList.remove('globe-guindima-actif');
  zone.dataset.secours = 'oui';
}
secours.addEventListener('click', function () {
  micro_classique();
  const m = micro();
  if (m) { m.scrollIntoView({ block: 'center' }); }
});

function micro() { return document.getElementById('micro_guindima'); }
// Gradio garde les deux boutons natifs dans le DOM et bascule leur
// « display » : seul celui qui est affiché compte.
function boutonNatif(classe) {
  const m = micro();
  const b = m ? m.querySelector(classe) : null;
  return b && window.getComputedStyle(b).display !== 'none' ? b : null;
}
// La réponse affichée : la carte, la voix et la transcription. Quand elle
// change, le traitement est fini.
function reponse() {
  const carte = document.querySelector('#reponse_guindima .prose');
  const voix = document.querySelector('#voix_guindima audio');
  const texte = document.querySelector('#transcription_guindima textarea');
  return [carte ? carte.innerHTML.length + ':' + carte.textContent.slice(0, 200) : '',
          voix ? voix.getAttribute('src') || '' : '',
          texte ? texte.value : ''].join('|');
}
function poser(nouvel) {
  if (nouvel === etat) { return; }
  etat = nouvel;
  depuis = performance.now();
  zone.dataset.etat = nouvel;
  etiquette.textContent = TEXTES[nouvel];
  if (promesse) { promesse.textContent = nouvel === 'traitement' ? ATTENTE : PROMESSE; }
  bouton.setAttribute('aria-label', ARIA[nouvel]);
  bouton.setAttribute('aria-pressed', nouvel === 'ecoute' ? 'true' : 'false');
  if (nouvel === 'traitement') { empreinte = reponse(); }
  if (lent.matches) { dessiner(0); }
}

// Les boutons natifs ne se prennent pas au clavier : le globe les remplace.
function cacherNatifs() {
  const m = micro();
  if (!m) { return; }
  // Lot C6 : n'écrit qu'une fois. Réécrire ces attributs quatre fois par
  // seconde faisait muter le DOM sans fin (observateurs, iframe du Space qui
  // se redimensionne) : une cause du tremblement sur téléphone.
  m.querySelectorAll('.record-button, .stop-button').forEach(function (b) {
    if (b.getAttribute('tabindex') !== '-1') { b.setAttribute('tabindex', '-1'); }
    if (b.getAttribute('aria-hidden') !== 'true') { b.setAttribute('aria-hidden', 'true'); }
  });
}

bouton.addEventListener('click', function () {
  if (etat === 'repos') {
    // « écoute » seulement quand l'enregistrement a vraiment démarré (le
    // suivi ci-dessous voit le bouton d'arrêt) : un refus du micro laisse
    // le globe au repos au lieu de faire croire qu'on écoute.
    const enregistrer = boutonNatif('.record-button');
    if (enregistrer) { enregistrer.click(); }
  } else if (etat === 'ecoute') {
    const arreter = boutonNatif('.stop-button');
    if (arreter) { arreter.click(); }
    poser('traitement');
  }
});

// Suivi de l'état réel du micro, quatre fois par seconde. Un globe retiré de
// la page (onglet reconstruit) arrête son suivi : il ne doit plus rien décider.
const suivi = setInterval(function () {
  if (!document.body.contains(element)) { clearInterval(suivi); return; }
  cacherNatifs();
  const m = micro();
  if (zone.dataset.secours !== 'oui' && performance.now() - lancement > 6000
      && !(m && m.querySelector('.record-button'))) {
    micro_classique();
  }
  const enregistre = !!boutonNatif('.stop-button');
  const pret = !!boutonNatif('.record-button');
  const ecoule = performance.now() - depuis;
  if (enregistre && etat !== 'ecoute') { poser('ecoute'); return; }
  if (etat === 'ecoute' && !enregistre && ecoule > 600) { poser('traitement'); return; }
  if (etat === 'traitement') {
    // Fin : le gestionnaire a vidé le micro (bouton natif revenu) ou la
    // réponse a changé ; au pire, après 60 s.
    if ((pret && ecoule > 1500) || reponse() !== empreinte) { poser('repos'); }
    else if (ecoule > __DELAI__) {
      // Lot G1 : rien n'est arrivé. Jamais un retour silencieux à « Bës te wax ».
      poser('repos');
      if (promesse) { promesse.textContent = SANS_REPONSE; }
    }
  }
}, 250);

// L'anneau de particules.
const ctx = toile.getContext('2d');
const PALETTE = ['#00853F', '#00853F', '#2FA866', '#E9C400', '#00853F', '#F2D61C'];
const N = 84;
const particules = [];
for (let i = 0; i < N; i++) {
  particules.push({
    angle: (i / N) * Math.PI * 2 + (Math.random() - 0.5) * 0.05,
    decalage: (Math.random() - 0.5) * 12,
    taille: 1.6 + Math.random() * 2.0,
    phase: Math.random() * Math.PI * 2,
    couleur: PALETTE[i % PALETTE.length],
  });
}
let largeur = 0;
function dimensionner() {
  const ratio = window.devicePixelRatio || 1;
  largeur = toile.clientWidth || 212;
  toile.width = Math.round(largeur * ratio);
  toile.height = Math.round(largeur * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}
function dessiner(t) {
  if (!largeur) { dimensionner(); }
  const c = largeur / 2;
  const rayon = largeur * 0.4;
  ctx.clearRect(0, 0, largeur, largeur);
  let rotation = t * 0.00022;
  let ampleur = 1.5;
  let grossir = 1;
  if (etat === 'ecoute') {
    rotation = t * 0.0011;
    const battement = 0.5 + 0.5 * Math.sin(t * 0.0065);
    ampleur = 4 + 6 * battement;
    grossir = 1.25 + 0.25 * battement;
    const halo = ctx.createRadialGradient(c, c, rayon * 0.55, c, c, rayon * 1.2);
    halo.addColorStop(0, 'rgba(253, 239, 66, 0)');
    halo.addColorStop(0.7, 'rgba(253, 239, 66, ' + (0.18 + 0.2 * battement).toFixed(3) + ')');
    halo.addColorStop(1, 'rgba(253, 239, 66, 0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(c, c, rayon * 1.2, 0, Math.PI * 2);
    ctx.fill();
  } else if (etat === 'traitement') {
    rotation = t * 0.0005;
  }
  const tete = (t * 0.004) % (Math.PI * 2);
  for (const p of particules) {
    const a = p.angle + rotation;
    const r = rayon + p.decalage * (etat === 'ecoute' ? 1.5 : 1) + Math.sin(t * 0.002 + p.phase) * ampleur;
    let alpha = 0.92;
    if (etat === 'traitement') {
      // Une comète fait le tour : l'app cherche.
      let ecart = (tete - ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
      alpha = 0.18 + 0.82 * Math.max(0, 1 - ecart / (Math.PI * 0.9));
    }
    ctx.globalAlpha = alpha;
    ctx.fillStyle = p.couleur;
    ctx.beginPath();
    ctx.arc(c + Math.cos(a) * r, c + Math.sin(a) * r, p.taille * grossir, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}
function boucle(t) {
  if (!lent.matches && !document.hidden) { dessiner(t); }
  window.requestAnimationFrame(boucle);
}
dimensionner();
dessiner(0);
window.addEventListener('resize', function () { dimensionner(); dessiner(0); });
lent.addEventListener('change', function () { dessiner(0); });
window.requestAnimationFrame(boucle);
"""


def globe_js() -> str:
    import json

    return (
        GLOBE_JS.replace("__TEXTES__", json.dumps(TEXTES_GLOBE, ensure_ascii=False))
        .replace("__ARIA__", json.dumps(ARIA_GLOBE, ensure_ascii=False))
        .replace("__PROMESSE__", json.dumps(PROMESSE, ensure_ascii=False))
        .replace("__ATTENTE__", json.dumps(ATTENTE, ensure_ascii=False))
        .replace("__SANS_REPONSE__", json.dumps(SANS_REPONSE, ensure_ascii=False))
        .replace("__DELAI__", str(DELAI_SANS_REPONSE_MS))
    )


# --------------------------------------------------------------------------- #
# 3. Étoiles
# --------------------------------------------------------------------------- #
CHOIX_ETOILES = [(f"{n} étoile{'s' if n > 1 else ''} sur 5", n) for n in range(1, 6)]
