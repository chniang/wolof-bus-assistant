"""Interface Streamlit de l'assistant bus wolof : voix ou texte en wolof -> ligne de bus.

Le flux complet enchaîne les briques du pipeline :
    voix -> transcrire() (whisper-small-wolof) -> extract_intent() (LLM) -> StopsMatcher.find_line() (CSV)
Le mode texte saute simplement la première étape.
"""

from __future__ import annotations

import hashlib
import html
import sys
import time
from pathlib import Path

import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asr.transcribe import SAMPLE_RATE, load_audio, load_model, transcrire
from intent.extract_intent import extract_intent, get_client
from matching.stops_matcher import StopsMatcher
from tts.speak import (
    Tts,
    cache_complet,
    load_tts,
    nombre_en_wolof,
    numero_de,
    phrase_reponse,
    synthetiser,
    voix_depuis_cache,
)

# Audios de secours pour la démo : si le micro ou la salle trahit, on rejoue un
# enregistrement propre qui passe exactement par le même pipeline.
DEMO_AUDIO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo_audio"

EXEMPLES = [
    "ma ngi ci Liberté 5, bëgg naa dem Palais 2",
    "maa ngi Guédiawaye, daldi naa dem Palais 1",
    "ma ngi ci Palais 1, bëgg naa dem Guédiawaye",
    "sant de sante Liberté 5, bëgg bi dem Palais 2",
]


# --------------------------------------------------------------------------- #
# Apparence. Aucun impact sur la logique : uniquement du CSS et de la mise en
# page, injectés une fois par run.
# --------------------------------------------------------------------------- #

VERT = "#00853F"  # vert du Senegal

CSS_APP = f"""
<style>
.gd-entete {{
    border-left: 6px solid {VERT};
    padding: 0.2rem 0 0.2rem 1rem;
    margin-bottom: 1.4rem;
}}
.gd-entete .gd-titre {{
    font-size: 2.6rem;
    font-weight: 800;
    line-height: 1.1;
    margin: 0;
}}
.gd-entete .gd-wolof {{
    color: {VERT};
    font-size: 1.15rem;
    font-weight: 600;
    font-style: italic;
    margin-top: 0.35rem;
}}
.gd-entete .gd-fr {{
    color: #55625B;
    font-size: 1.02rem;
    margin-top: 0.1rem;
}}

.gd-carte {{
    border: 1px solid #D6E6DC;
    border-top: 6px solid {VERT};
    border-radius: 0.7rem;
    background: linear-gradient(180deg, #F6FBF8 0%, #FFFFFF 55%);
    padding: 1rem 1.3rem 1.1rem 1.3rem;
    margin: 0.2rem 0 0.6rem 0;
}}
.gd-carte .gd-compagnie {{
    color: {VERT};
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin: 0;
}}
.gd-carte .gd-numero {{
    color: {VERT};
    font-size: 4.4rem;
    font-weight: 800;
    line-height: 1;
    margin: 0.1rem 0 0.35rem 0;
}}
.gd-carte .gd-trajet {{
    color: #17211C;
    font-size: 1.28rem;
    font-weight: 600;
    margin: 0;
}}
.gd-carte .gd-categorie {{
    color: #6B7A72;
    font-size: 0.85rem;
    margin-top: 0.3rem;
}}

.gd-pied {{
    color: #8A968F;
    font-size: 0.8rem;
    text-align: center;
    border-top: 1px solid #E3EAE6;
    padding-top: 0.7rem;
    margin-top: 2.2rem;
}}
</style>
"""


def afficher_css() -> None:
    """Injecte la feuille de style (idempotent : meme CSS a chaque run)."""
    st.markdown(CSS_APP, unsafe_allow_html=True)


def afficher_entete() -> None:
    """Titre, puis la promesse en wolof et en francais."""
    st.markdown(
        f"""
        <div class="gd-entete">
          <div class="gd-titre">🚌 GuindiMa AI</div>
          <div class="gd-wolof">Wax ma fu nga jëm, ma won la bus bi</div>
          <div class="gd-fr">Dis-moi où tu vas, je te montre le bus</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _texte(valeur) -> str:
    """Échappe une valeur avant de l'injecter en HTML."""
    return html.escape(str(valeur if valeur is not None else ""))


def afficher_carte_ligne(match: dict) -> None:
    """Grande carte : compagnie, numéro de ligne en très gros, trajet en dessous.

    Le numéro affiché est aussi énoncé en wolof : c'est la version que le
    locuteur pronunciera, ce qui évite de lire un chiffre à l'écran.
    """
    numero = numero_de(match.get("ligne"))
    # numero_de() renvoie None si le CSV n'a pas de numero : nombre_en_wolof()
    # fait int(n) et leverait TypeError sur None, donc on garde l'affichage nu.
    if numero is None:
        affiche, en_wolof = match.get("ligne", ""), ""
    else:
        affiche, en_wolof = numero, f"ligne {html.escape(nombre_en_wolof(numero))}"
    details = " · ".join(part for part in (_texte(match.get("categorie")), en_wolof) if part)
    st.markdown(
        f"""
        <div class="gd-carte">
          <div class="gd-compagnie">{_texte(match.get('compagnie'))}</div>
          <div class="gd-numero">{_texte(affiche)}</div>
          <div class="gd-trajet">
            {_texte(match.get('depart'))} → {_texte(match.get('arrivee'))}
          </div>
          <div class="gd-categorie">{details}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def afficher_pied() -> None:
    """Pied de page discret : d'où viennent les données et les modèles."""
    st.markdown(
        '<div class="gd-pied">Données : Dakar Dem Dikk, Tata AFTU '
        "· IA : Whisper wolof, NVIDIA Build</div>",
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_matcher() -> StopsMatcher:
    return StopsMatcher()


@st.cache_resource
def get_llm_client():
    """Client HTTP réutilisé entre les requêtes (st.cache_resource le garde en mémoire)."""
    return get_client()


@st.cache_resource(show_spinner=False)
def get_asr_model():
    """Whisper wolof chargé une seule fois : le recharger à chaque question coûterait ~1 min."""
    return load_model()


@st.cache_resource(show_spinner=False)
def get_tts() -> Tts:
    """SpeechT5 wolof chargé une seule fois : le recharger coûterait 578 Mo à chaque fois."""
    return load_tts()


@st.cache_resource(show_spinner=False)
def prechauffer_voix_synthetisee() -> None:
    """Charge le TTS et le teste sur une phrase courte.

    Le test ne sert qu'à vérifier que toute la chaîne marche (tokenizer, modèle,
    vociseur) : on le paie une fois au démarrage plutôt que de découvrir une
    voix cassée après avoir répondu à l'utilisateur.
    """
    synthetiser(get_tts(), "Baal ma, gisuma bus bu dem fa.")


def dire_la_reponse(lignes: list[dict], origine: str) -> None:
    """Fait lire le résultat, et le garde en mémoire pour ne pas le regénérer.

    Deux chemins : les audios déjà sur disque (le cas de la démo, aucun modèle à
    charger), sinon la synthèse en direct. Dans les deux cas le résultat est
    mémorisé par phrase, car Streamlit relit tout le script à chaque clic et la
    synthèse est lente. Volontairement pas décorée de cache_resource : elle a un
    effet d'affichage, elle doit donc être rejouée à chaque rendu.
    """
    if st.session_state.get("tts_ko"):
        st.caption("Voix de synthèse indisponible, la réponse reste affichée en texte.")
        return

    phrase = phrase_reponse(lignes)
    deja_vus = st.session_state.setdefault("audio_par_phrase", {})

    # st.audio n'accepte pas de key (Streamlit 1.64) et, quand autoplay=True,
    # Streamlit dérive son identifiant du contenu audio : les deux onglets, rendus
    # dans le même run, produiraient le même identifiant et lèveraient
    # StreamlitDuplicateElementID. Deux lecteurs identiques qui se déclenchent
    # aussi en même temps produiraient un son parasite, donc on n'en affiche qu'un
    # par phrase et par run.
    if phrase in st.session_state.setdefault("audio_deja_rendu_run", set()):
        return
    st.session_state["audio_deja_rendu_run"].add(phrase)

    if phrase in deja_vus:
        st.audio(deja_vus[phrase], format="audio/wav", autoplay=True)
        return

    # Démo : tout est déjà synthétisé, on colle les morceaux sans charger le modèle.
    octets = voix_depuis_cache(lignes) if cache_complet() else None

    if octets is None:
        try:
            tts = get_tts()
            with st.spinner("Préparation de la voix…"):
                octets = synthetiser(tts, phrase)
        except Exception as exc:
            # On note l'échec : sans cela, chaque clic retenterait le chargement.
            st.session_state["tts_ko"] = True
            st.caption(f"Voix de synthèse indisponible ({exc}), la réponse reste affichée en texte.")
            return

    deja_vus[phrase] = octets
    st.audio(octets, format="audio/wav", autoplay=True)


@st.cache_resource(show_spinner=False)
def prechauffer_moteur_vocal() -> None:
    """Charge Whisper au démarrage et le chauffe sur 1 s de silence.

    Le chargement du modèle dure ~1 min et la première transcription est la plus
    lente : on fait les deux ici pour que l'utilisateur n'attende pas au milieu de
    sa phrase. Le cache_resource évite de refaire ce travail à chaque interaction.
    """
    transcrire(get_asr_model(), np.zeros(SAMPLE_RATE, dtype=np.float32))


def afficher_phrase(phrase: str) -> None:
    """Étape 1 : rappel de la phrase saisie."""
    with st.container(border=True):
        st.subheader("1 · Phrase")
        st.markdown(f"> {phrase}")


def afficher_extraction(phrase: str) -> dict | None:
    """Étape 2 : extraction départ / arrivée. Retourne None si le LLM échoue."""
    with st.container(border=True):
        st.subheader("2 · Extraction (LLM)")
        # Streamlit relance tout le script à chaque clic : on garde les réponses
        # déjà obtenues pour ne pas rappeler le LLM (et griller le quota) pour rien.
        deja_vus = st.session_state.setdefault("intents_par_phrase", {})
        try:
            if phrase in deja_vus:
                intent = deja_vus[phrase]
            else:
                with st.spinner("Analyse de la phrase en cours…"):
                    intent = extract_intent(phrase, client=get_llm_client())
                if not intent.get("erreur"):
                    deja_vus[phrase] = intent
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


def afficher_lignes(matcher: StopsMatcher, depart: str, arrivee: str, origine: str) -> None:
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
            st.caption(f"{len(result['lignes'])} ligne(s) trouvée(s) dans le jeu de données.")
            for match in result["lignes"]:
                afficher_carte_ligne(match)
            # Le lecteur audio reste juste sous la carte.
            dire_la_reponse(result["lignes"], origine)
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

        dire_la_reponse(result["lignes"], origine)


def lancer_pipeline(matcher: StopsMatcher, phrase: str, origine: str) -> None:
    """Phrase -> extraction -> lignes : commun aux modes voix et texte.

    `origine` identifie l'onglet qui a déclenché le pipeline : les onglets sont
    rendus dans le même run, il faut donc pouvoir distinguer les deux rendus.
    """
    # Le detail technique (phrase recue, extraction) est replie : le jury voit
    # surtout le resultat. Ouvert par defaut, ca reste demonstrable au besoin.
    with st.expander("Voir le détail (IA)", expanded=True):
        afficher_phrase(phrase)
        intent = afficher_extraction(phrase)
    if intent is not None:
        afficher_lignes(matcher, intent["depart"], intent["arrivee"], origine)


def _lister_audios_demo() -> list[Path]:
    if not DEMO_AUDIO_DIR.exists():
        return []
    return sorted(
        p for p in DEMO_AUDIO_DIR.iterdir() if p.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"}
    )


def _transcrire_une_fois(audio_bytes: bytes) -> tuple[str, float]:
    """Transcrit un audio, en mémorisant le résultat par empreinte du fichier.

    Sans ça, chaque clic dans la page relancerait Whisper sur le même audio.
    Renvoie (texte, durée en secondes) ; la durée vaut 0 si on ressort du cache.
    """
    empreinte = hashlib.md5(audio_bytes).hexdigest()
    cache = st.session_state.setdefault("transcriptions", {})
    if empreinte in cache:
        return cache[empreinte], 0.0

    with st.spinner("Chargement du modèle vocal (la première fois seulement)…"):
        modele = get_asr_model()
    debut = time.perf_counter()
    with st.spinner("J'écoute… transcription en wolof"):
        texte = transcrire(modele, load_audio(audio_bytes))
    duree = time.perf_counter() - debut
    cache[empreinte] = texte
    return texte, duree


def mode_vocal(matcher: StopsMatcher) -> None:
    """Flux principal de la démo : on parle en wolof, on obtient la ligne."""
    # st.audio_input est arrivé dans Streamlit 1.39 (d'abord sous le nom « experimental »).
    audio_input = getattr(st, "audio_input", None) or getattr(st, "experimental_audio_input", None)
    if audio_input is None:
        st.error("Enregistrement micro indisponible : mettez Streamlit à jour (pip install -U streamlit).")
        return

    enregistrement = audio_input("Appuyez, puis dites votre trajet en wolof", key="micro")

    # On retient la dernière source utilisée (micro ou audio de secours), pour que
    # choisir un audio de démo ne soit pas écrasé par un vieil enregistrement.
    if enregistrement is not None:
        octets = enregistrement.getvalue()
        empreinte = hashlib.md5(octets).hexdigest()
        if st.session_state.get("empreinte_micro") != empreinte:
            st.session_state["empreinte_micro"] = empreinte
            st.session_state["source_audio"] = ("micro", octets)

    audios_demo = _lister_audios_demo()
    with st.expander("Audios de secours (si le micro ne coopère pas)", expanded=False):
        if audios_demo:
            choix = st.selectbox(
                "Audio pré-enregistré",
                audios_demo,
                format_func=lambda p: p.stem,
                label_visibility="collapsed",
            )
            if st.button("Utiliser cet audio", use_container_width=True):
                st.session_state["source_audio"] = ("demo", choix.read_bytes())
        else:
            st.caption(
                f"Aucun audio dans {DEMO_AUDIO_DIR.name}/. Enregistrez une phrase au micro "
                "puis cliquez sur « Garder comme audio de secours »."
            )

    source = st.session_state.get("source_audio")
    if source is None:
        return

    type_source, octets = source
    if type_source == "demo":
        # Pas de key possible sur st.audio, mais sans autoplay Streamlit
        # n'enregistre aucun identifiant : aucun risque de doublon ici.
        st.audio(octets)

    try:
        phrase, duree = _transcrire_une_fois(octets)
    except Exception as exc:
        st.error(f"Transcription impossible : {exc}")
        return

    if not phrase:
        st.warning("Je n'ai rien entendu de clair. Rapprochez-vous du micro et réessayez.")
        return

    if duree:
        st.caption(f"Transcrit en {duree:.1f} s par whisper-small-wolof")

    # Petit outil de préparation : on transforme une bonne prise en audio de secours.
    if type_source == "micro":
        with st.popover("Garder comme audio de secours"):
            nom = st.text_input("Nom du fichier", value="trajet", key="nom_audio_demo")
            if st.button("Enregistrer", key="sauver_audio_demo"):
                DEMO_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                cible = DEMO_AUDIO_DIR / f"{nom.strip() or 'trajet'}.wav"
                cible.write_bytes(octets)
                st.success(f"Sauvegardé : data/demo_audio/{cible.name}")

    lancer_pipeline(matcher, phrase, "voix")


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
        lancer_pipeline(matcher, phrase, "texte")


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
            afficher_lignes(matcher, depart, arrivee, "avance")


def main() -> None:
    st.set_page_config(page_title="GuindiMa AI", page_icon="🚌")
    # Le main() est rejoué à chaque run : on repart d'un registre vide, sinon le
    # lecteur audio déjà affiché dans le run précédent bloquerait celui d'aujourd'hui.
    st.session_state["audio_deja_rendu_run"] = set()
    afficher_css()
    afficher_entete()

    # Le modèle vocal se charge dès le démarrage, avant le premier clic sur le micro :
    # sinon le premier enregistrement attend le chargement en plein milieu de la phrase.
    try:
        with st.spinner("Préparation du modèle vocal…"):
            prechauffer_moteur_vocal()
    except Exception as exc:
        st.warning(
            f"Modèle vocal indisponible ({exc}). "
            "L'onglet « Écrire » reste utilisable."
        )

    # Si le cache audio est complet, inutile de charger 578 Mo de modèle au
    # démarrage : l'app se contente de coller des fichiers déjà prêts.
    if not cache_complet():
        try:
            with st.spinner("Préparation de la synthèse vocale…"):
                prechauffer_voix_synthetisee()
        except Exception as exc:
            st.caption(
                f"Synthèse vocale indisponible ({exc}), les réponses seront en texte seul."
            )

    matcher = get_matcher()
    onglet_voix, onglet_texte = st.tabs(["🎙️ Parler", "⌨️ Écrire"])
    with onglet_voix:
        mode_vocal(matcher)
    with onglet_texte:
        mode_simple(matcher)
    mode_avance(matcher)
    afficher_pied()


if __name__ == "__main__":
    main()
