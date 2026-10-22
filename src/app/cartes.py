def titre_autre_possibilite(numero: int) -> str:
    """Titre HTML : le Markdown « **…** » ne se rend pas après un bloc HTML."""
    return (
        "<div style='color:#0B6B37;font-size:16px;font-weight:700;"
        f"margin:14px 0 4px 0;'>Autre possibilité {numero}</div>"
    )
