from html import escape

# Les titres portent leur propre fond clair : en thème sombre, le vert foncé
# posé directement sur le fond bleu nuit de Gradio était presque illisible
# (« Pas de bus direct : un changement suffit », test en ligne). Vert très
# foncé sur vert très pâle : contraste ~9:1, le même dans les deux thèmes.
TITRE_TEXTE = "#064E2B"
TITRE_FOND = "#E8F5EE"
TITRE_BORD = "#00853F"


def _titre(texte: str, taille: int, graisse: int, marge: str) -> str:
    return (
        f"<div style='color:{TITRE_TEXTE};background:{TITRE_FOND};"
        f"border-left:5px solid {TITRE_BORD};border-radius:8px;padding:6px 12px;"
        f"font-size:{taille}px;font-weight:{graisse};margin:{marge};'>"
        f"{escape(str(texte))}</div>"
    )


def titre_autre_possibilite(numero: int) -> str:
    """Titre HTML : le Markdown « **…** » ne se rend pas après un bloc HTML."""
    return _titre(f"Autre possibilité {numero}", 16, 700, "14px 0 4px 0")


def titre_section(texte: str) -> str:
    """Titre de section en HTML, jamais en Markdown « ### ».

    Collé à la carte précédente (« </div>### Pas de bus direct »), le Markdown
    restait dans le bloc HTML et l'usager voyait les « ### » tels quels.
    """
    return _titre(texte, 20, 800, "18px 0 6px 0")
