from html import escape


def titre_autre_possibilite(numero: int) -> str:
    """Titre HTML : le Markdown « **…** » ne se rend pas après un bloc HTML."""
    return (
        "<div style='color:#0B6B37;font-size:16px;font-weight:700;"
        f"margin:14px 0 4px 0;'>Autre possibilité {escape(str(numero))}</div>"
    )


def titre_section(texte: str) -> str:
    """Titre de section en HTML, jamais en Markdown « ### ».

    Collé à la carte précédente (« </div>### Pas de bus direct »), le Markdown
    restait dans le bloc HTML et l'usager voyait les « ### » tels quels.
    """
    return (
        "<div style='color:#11301C;font-size:20px;font-weight:800;"
        f"margin:18px 0 6px 0;'>{escape(str(texte))}</div>"
    )
