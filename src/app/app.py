"""Interface Streamlit de l'assistant bus wolof : phrase en wolof -> ligne de bus.

Le flux normal enchaîne les 3 briques du pipeline :
    phrase en wolof -> extract_intent() (LLM) -> StopsMatcher.find_line() (CSV)
L'audio n'est pas encore branché : la phrase est saisie au clavier.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intent.extract_intent import extract_intent, get_client
from matching.stops_matcher import StopsMatcher

EXEMPLES = [
    "ma ngi ci Liberté 5, bëgg naa dem Palais 2",
    "maa ngi Guédiawaye, daldi naa dem Palais 1",
    "ma ngi ci Palais 1, bëgg naa dem Guédiawaye",
    "sant de sante Liberté 5, bëgg bi dem Palais 2",
]


@st.cache_resource
def get_matcher() -> StopsMatcher:
    return StopsMatcher()


@st.cache_resource
def get_llm_client():
    """Client HTTP réutilisé entre les requêtes (st.cache_resource le garde en mémoire)."""
    return get_client()


def afficher_phrase(phrase: str) -> None:
    """Étape 1 : rappel de la phrase saisie."""
    with st.container(border=True):
        st.subheader("1 · Phrase")
        st.markdown(f"> {phrase}")


def afficher_extraction(phrase: str) -> dict | None:
    """Étape 2 : extraction départ / arrivée. Retourne None si le LLM échoue."""
    with st.container(border=True):
        st.subheader("2 · Extraction (LLM)")
        try:
            with st.spinner("Analyse de la phrase en cours…"):
                intent = extract_intent(phrase, client=get_llm_client())
        except Exception as exc:
            st.error(f"Extraction impossible : {exc}")
            return None
        if intent.get("erreur"):
            st.error(f"Extraction impossible : {intent['erreur']}")
            return None

        st.session_state["dernier_depart"] = intent["depart"]
        st.session_state["dernier_arrivee"] = intent["arrivee"]
        col_depart, col_arrivee = st.columns(2)
        col_depart.metric("Départ", intent["depart"] or "non détecté")
        col_arrivee.metric("Arrivée", intent["arrivee"] or "non détecté")
    return intent


def afficher_lignes(matcher: StopsMatcher, depart: str, arrivee: str) -> None:
    """Étape 3 : correspondance avec le CSV des lignes de bus."""
    with st.container(border=True):
        st.subheader("3 · Ligne(s)")

        if not depart or not arrivee:
            st.warning(
                "Départ ou arrivée non détecté dans la phrase. "
                "Reformulez, ou complétez au clavier dans le mode avancé ci-dessous."
            )
            return

        result = matcher.find_line(depart, arrivee)

        if result["found"]:
            st.success(f"{len(result['lignes'])} ligne(s) trouvée(s) :")
            for match in result["lignes"]:
                st.markdown(
                    f"- **{match['compagnie']} — {match['ligne']}** : "
                    f"{match['depart']} → {match['arrivee']} "
                    f"({match.get('categorie', 'N/A')})"
                )
            return

        depart_valide, arrivee_valide = result["depart_valide"], result["arrivee_valide"]
        if not depart_valide or not arrivee_valide:
            inconnus = [
                f"{label} « {saisi} »"
                for label, valide, saisi in (
                    ("départ", depart_valide, depart),
                    ("arrivée", arrivee_valide, arrivee),
                )
                if not valide
            ]
            st.warning(
                f"Lieu hors réseau ({', '.join(inconnus)}) : le plus proche est "
                + " / ".join(
                    f"{trouve} ({score:.2f})"
                    for trouve, score in (
                        (result["depart_matched"], result["depart_score"]),
                        (result["arrivee_matched"], result["arrivee_score"]),
                    )
                )
                + f". Correspondances ignorées sous le seuil de similarité."
            )
        else:
            st.warning(
                f"Aucune ligne ne relie {result['depart_matched']} à "
                f"{result['arrivee_matched']} dans le jeu de données."
            )


def mode_simple(matcher: StopsMatcher) -> None:
    """Flux principal : une phrase en wolof."""
    with st.expander("Exemples de phrases", expanded=False):
        exemple = st.selectbox("Phrase d'exemple", EXEMPLES, label_visibility="collapsed")
        if st.button("Charger cet exemple", use_container_width=True):
            st.session_state["phrase"] = exemple

    phrase = st.text_input(
        "Votre phrase en wolof",
        key="phrase",
        placeholder=EXEMPLES[0],
    )

    if st.button("Trouver ma ligne", type="primary", use_container_width=True):
        if not phrase.strip():
            st.warning("Saisissez d'abord une phrase en wolof.")
            return
        afficher_phrase(phrase)
        intent = afficher_extraction(phrase)
        if intent is not None:
            afficher_lignes(matcher, intent["depart"], intent["arrivee"])


def mode_avance(matcher: StopsMatcher) -> None:
    """Saisie directe départ / arrivée, sans appel au LLM (debug démo)."""
    with st.expander("Mode avancé — saisir départ et arrivée", expanded=False):
        st.caption("Contourne l'extraction LLM : utile pour vérifier le CSV ou le seuil.")
        col_depart, col_arrivee = st.columns(2)
        depart = col_depart.text_input(
            "Départ (quartier)",
            key="avance_depart",
            value=st.session_state.get("dernier_depart", ""),
        )
        arrivee = col_arrivee.text_input(
            "Arrivée (quartier)",
            key="avance_arrivee",
            value=st.session_state.get("dernier_arrivee", ""),
        )
        if st.button("Chercher directement", use_container_width=True):
            if not depart.strip() or not arrivee.strip():
                st.warning("Renseignez le départ et l'arrivée.")
                return
            afficher_lignes(matcher, depart, arrivee)


def main() -> None:
    st.set_page_config(page_title="GuindiMa AI", page_icon="🚌")
    st.title("GuindiMa AI")
    st.caption("Dites votre trajet en wolof, on trouve la ligne (Dakar Dem Dikk / Tata AFTU).")

    matcher = get_matcher()
    mode_simple(matcher)
    mode_avance(matcher)


if __name__ == "__main__":
    main()
