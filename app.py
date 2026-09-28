"""Interface Gradio de GuindiMa AI, pour un Hugging Face Space (ZeroGPU).

Ce fichier ne réimplémente rien : il reprend les modules déjà validés du projet,
dans le même ordre que src/app/app.py. Il n'y a donc qu'une différence avec
l'application Streamlit : le rendu. Ici on ne gère pas de session, chaque
exécution de Gradio est indépendante, ce qui simplifie la mise en cache.

    audio -> transcrire() -> extract_intent() -> StopsMatcher.find_line()
          -> phrase_reponse() + voix_depuis_cache()

Sur un Space, la seule partie qui demande le GPU est la transcription : le
décorateur @spaces.GPU la réserve le temps du calcul puis le libère pour les autres visiteurs.
Le reste du pipeline (extraction, correspondance, voix) tient en CPU et n'a pas
à payer la réservation.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import gradio as gr
import numpy as np

RACINE = Path(__file__).resolve().parent
# Les modules du projet sont importés à plat (asr, intent, matching, tts) : il faut
# que src/ soit dans le chemin, comme le fait src/app/app.py pour son propre lancement.
sys.path.insert(0, str(RACINE / "src"))

from asr.transcribe import (  # noqa: E402
    MODEL_WHISPER,
    SAMPLE_RATE,
    load_audio,
    load_model,
    transcrire,
)
from intent.extract_intent import (  # noqa: E402
    NVIDIA_BASE_URL,
    TIMEOUT_APPEL,
    extract_intent,
)
from matching.stops_matcher import StopsMatcher  # noqa: E402
from tts.speak import (  # noqa: E402
    cache_complet,
    load_tts,
    nombre_en_wolof,
    numero_de,
    phrase_reponse,
    synthetiser,
    voix_depuis_cache,
)

VERT = "#00853F"  # vert du Sénégal, celui du thème et des cartes
DEMO_AUDIO_DIR = RACINE / "data" / "demo_audio"

# --------------------------------------------------------------------------- #
# GPU
# --------------------------------------------------------------------------- #

try:
    import spaces
except ImportError:
    # Hors Space — poste local, CI, machine sans le SDK — le module n'existe pas.
    # On fabrique un décorateur à la même signature pour que le reste du fichier
    # n'ait aucune condition particulière à vérifier.
    class _SpacesLocal:
        """Remplace le SDK spaces quand il n'est pas installé : no-op."""

        @staticmethod
        def GPU(*args, **kwargs):
            def sans_gpu(fonction):
                return fonction

            return sans_gpu

    spaces = _SpacesLocal()


def _charger_whisper():
    """Charge Whisper une seule fois, au chargement du module.

    Sur GPU, le pipeline part en float16 sur « cuda » : c'est de loin le plus
    rapide, et la quantification int8 n'a de sens que pour le CPU. Sur CPU on délègue
    à load_model(), qui applique la quantification int8 validée sur le laptop.
    """
    import torch
    from transformers import pipeline

    if torch.cuda.is_available():
        return pipeline(
            "automatic-speech-recognition",
            model=MODEL_WHISPER,
            device=0,
            torch_dtype=torch.float16,
        )
    return load_model()


MODELE_WHISPER = _charger_whisper()

# Le TTS ne sert qu'en secours, quand le cache disque n'a pas l'audio du résultat.
# Le charger à la volée évite de téléchargement 578 Mo pour rien sur un Space.
_TTS = None


def _tts():
    global _TTS
    if _TTS is None:
        _TTS = load_tts()
    return _TTS


# --------------------------------------------------------------------------- #
# Clients et objets reconstruits une fois
# --------------------------------------------------------------------------- #

MATCHER = StopsMatcher()

_CLIENT = None
_CLIENT_TENTE = False


def _client_llm():
    """Client NVIDIA partagé, ou None si la clé n'est pas là.

    On lit la clé dans l'environnement plutôt que de laisser extract_intent lever :
    sans clé, on renvoie None, extract_intent tente alors de construire le client,
    échoue, et bascule sur son extraction locale. Un Space sans secret configuré
    dégrade donc la qualité de la détection au lieu de casser la démo.
    """
    global _CLIENT, _CLIENT_TENTE
    if _CLIENT_TENTE:
        return _CLIENT
    _CLIENT_TENTE = True
    cle = os.getenv("NVIDIA_API_KEY", "").strip()
    if cle:
        from openai import OpenAI

        _CLIENT = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=cle,
            timeout=TIMEOUT_APPEL,
            # Nos tentatives sont gérées dans extract_intent ; sans cela le SDK en
            # ajoute deux de son côté et triple le délai avant le repli local.
            max_retries=0,
        )
    return _CLIENT


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #

# Gradio veut un chemin de fichier, la synthèse renvoie des octets WAV. On écrit
# donc dans un dossier temporaire, un fichier par réponse.
DOSSIER_VOIX = Path(tempfile.mkdtemp(prefix="guindima_voix_"))
_COMPTEUR = itertools.count()


@spaces.GPU(duration=30)
def transcrire_wolof(chemin_audio: str) -> str:
    """Transcrit un enregistrement de micro ou un fichier envoyé.

    Seul endroit de l'app qui réserve le GPU. Le modèle est déjà en mémoire, la
    réservation ne couvre donc que le calcul.
    """
    octets = Path(chemin_audio).read_bytes()
    try:
        audio = load_audio(octets)
    except Exception:
        # Le navigateur enregistre en WebM/Opus, que soundfile ne sait pas lire.
        # ffmpeg, déclaré dans packages.txt, ramène ça en WAV avant de réessayer.
        with tempfile.TemporaryDirectory() as dossier:
            converti = Path(dossier) / "micro.wav"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", chemin_audio,
                    "-ar", str(SAMPLE_RATE),
                    "-ac", "1",
                    str(converti),
                ],
                check=True,
                capture_output=True,
            )
            audio = load_audio(converti.read_bytes())
    return transcrire(MODELE_WHISPER, audio)


def _voix_wolof(lignes: list[dict]) -> str | None:
    """La réponse lue en wolof, sous forme de chemin de fichier.

    Cache disque d'abord : à la démo, tout est déjà synthétisé et aucun modèle n'a
    besoin d'être chargé. Synthèse directe seulement s'il manque un morceau.
    """
    if not lignes:
        return None
    octets = voix_depuis_cache(lignes) if cache_complet() else None
    if octets is None:
        try:
            octets = synthetiser(_tts(), phrase_reponse(lignes))
        except Exception as exc:
            print(f"Voix de synthèse indisponible ({exc}), la réponse reste en texte.")
            return None
    chemin = DOSSIER_VOIX / f"reponse_{next(_COMPTEUR)}.wav"
    chemin.write_bytes(octets)
    return str(chemin)


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #


def _carte(resultat: dict, depart: str, arrivee: str) -> str:
    """La réponse en Markdown : compagnie et numéro de ligne mis en avant."""
    if not depart or not arrivee:
        return (
            "### 🤷 Lieu non détecté\n\n"
            "Je n'ai pas trouvé un départ **et** une arrivée dans ta phrase. "
            "Reformule, ou parle plus près du micro."
        )

    if not resultat["found"]:
        hors_reseau = []
        if not resultat["depart_valide"]:
            hors_reseau.append(f"le départ **« {depart} »**")
        if not resultat["arrivee_valide"]:
            hors_reseau.append(f"l'arrivée **« {arrivee} »**")
        detail = " et ".join(hors_reseau) or "ce trajet"
        return (
            "### 🗺 Lieu hors réseau\n\n"
            f"{detail} n'est pas desservi par les lignes du jeu de données. "
            f"Essaie un quartier voisin, par exemple Guédiawaye, Ouakam ou Palais."
        )

    cartes = []
    for match in resultat["lignes"]:
        numero = numero_de(match["ligne"])
        affiche = numero if numero is not None else match["ligne"]
        rappel = nombre_en_wolof(numero) if numero is not None else ""
        cartes.append(
            f"""
<div style="border:1px solid #D6E6DC;border-top:6px solid {VERT};
            border-radius:12px;padding:16px 20px;margin:8px 0;background:#F6FBF8;">
  <div style="color:{VERT};font-size:12px;font-weight:700;letter-spacing:.14em;
              text-transform:uppercase;">{match['compagnie']}</div>
  <div style="color:{VERT};font-size:56px;font-weight:800;line-height:1.05;
              margin:4px 0 6px 0;">{affiche}</div>
  <div style="color:#17211C;font-size:20px;font-weight:600;">
    {match['depart']} → {match['arrivee']}</div>
  <div style="color:#6B7A72;font-size:13px;margin-top:6px;">
    {rappel} · {match.get('categorie', '')}</div>
</div>
"""
        )
    return "".join(cartes)


def _mention(intent: dict) -> str:
    """Rappelle que la détection est tombée sur le filet local, sans LLM."""
    if intent.get("source") == "local":
        return (
            "> ⚠️ **Extraction de secours (sans LLM)** — l'API NVIDIA était "
            "indisponible, la détection a été faite sur place."
        )
    if intent.get("erreur"):
        return f"> ⚠️ {intent['erreur']}"
    return ""


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def trouver_le_bus(audio: str | None, phrase_ecrite: str) -> tuple:
    """Le pipeline complet, dans l'ordre de src/app/app.py.

    Le micro l'emporte sur le texte : si un enregistrement arrive, on le
    transcrit. Les cinq retours correspondent aux cinq sorties de l'interface.
    """
    vide = ("", "", _carte({}, "", ""), None, "")

    if audio:
        try:
            phrase = transcrire_wolof(audio)
        except Exception as exc:
            return ("", "", f"### 🎤 Audio illisible\n\n{_court(exc)}", None, "")
    else:
        phrase = (phrase_ecrite or "").strip()

    if not phrase:
        return vide

    # L'extraction gère elle-même son repli local : si l'API est saturée, elle
    # rend quand même un départ et une arrivée tant que la phrase les porte.
    intent = extract_intent(phrase, client=_client_llm())
    depart, arrivee = intent.get("depart") or "", intent.get("arrivee") or ""

    if not depart or not arrivee:
        return (phrase, "", _carte({}, depart, arrivee), None, _mention(intent))

    resultat = MATCHER.find_line(depart, arrivee)
    return (
        phrase,
        f"{depart} → {arrivee}",
        _carte(resultat, depart, arrivee),
        _voix_wolof(resultat["lignes"]),
        _mention(intent),
    )


def _court(exc: Exception, longueur: int = 160) -> str:
    """Un message d'erreur court : les exceptions techniques font plusieurs lignes."""
    return f"{type(exc).__name__} : {exc}"[:longueur]


def trouver_le_bus_vocal(audio: str | None) -> tuple:
    """Raccourci pour les exemples audio : on part du micro, le texte est vide."""
    return trouver_le_bus(audio, "")


def trouver_le_bus_texte(phrase: str) -> tuple:
    """Raccourci pour les exemples texte : le micro est vide."""
    return trouver_le_bus(None, phrase)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #


def _theme():
    """Thème vert Sénégal.

    colors.hsl est la voie documentée pour passer une couleur exacte à un thème ;
    si l'API bouge, on retombe sur le nom « green » plutôt que de planter au
    démarrage du Space.
    """
    try:
        from gradio.themes.utils import colors

        return gr.themes.Soft(primary_hue=colors.hsl(146, 0.90, 0.31))
    except Exception:
        return gr.themes.Soft(primary_hue="green")


EXEMPLES_TEXTE = [
    "maa ngi Ouakam, bëgg naa dem Palais 2",
    "maa ngi ci Liberté 5, bëgg naa dem Palais 2",
]


def _construire():
    with gr.Blocks(theme=_theme(), title="GuindiMa AI 🚌") as interface:
        gr.Markdown("# GuindiMa AI 🚌\n### Wax ma fu nga jëm, ma won la bus bi")
        gr.Markdown(
            "Dis-moi où tu vas, je te montre le bus. "
            "Parle ou écris ton trajet en wolof, à Dakar."
        )

        # Les exemples ont besoin des sorties avant qu'elles soient affichées.
        # On les crée donc « hors écran » (render=False), et on les place plus bas,
        # sous le bouton, avec .render().
        transcription_out = gr.Textbox(label="Transcription", interactive=False, render=False)
        trajet_out = gr.Textbox(label="Départ → arrivée", interactive=False, render=False)
        mention_out = gr.Markdown(render=False)
        carte_out = gr.Markdown(render=False)
        audio_out = gr.Audio(label="Réponse en wolof", autoplay=True, render=False)
        sorties = [transcription_out, trajet_out, carte_out, audio_out, mention_out]

        with gr.Tab("Parler"):
            audio_in = gr.Audio(
                sources=["microphone", "upload"],
                type="filepath",
                label="Dis ton trajet en wolof",
            )
            audios_demo = sorted(DEMO_AUDIO_DIR.glob("*.wav"))
            if audios_demo:
                gr.Examples(
                    examples=[[str(chemin)] for chemin in audios_demo],
                    inputs=[audio_in],
                    fn=trouver_le_bus_vocal,
                    outputs=sorties,
                    cache_examples=False,
                    label="Ou alors, rejoue un enregistrement déjà prêt",
                )

        with gr.Tab("Écrire"):
            texte_in = gr.Textbox(
                label="Ton trajet en wolof",
                placeholder=EXEMPLES_TEXTE[0],
                lines=2,
            )
            gr.Examples(
                examples=[[phrase] for phrase in EXEMPLES_TEXTE],
                inputs=[texte_in],
                fn=trouver_le_bus_texte,
                outputs=sorties,
                cache_examples=False,
                label="Quelques phrases qui marchent",
            )

        bouton = gr.Button("Trouver mon bus", variant="primary", size="lg")

        with gr.Accordion("Ce que l'IA a compris", open=True):
            carte_out.render()
            audio_out.render()
            mention_out.render()
            transcription_out.render()
            trajet_out.render()

        gr.Markdown(
            "<div style='text-align:center;color:#8A968F;font-size:12px;"
            "border-top:1px solid #E3EAE6;padding-top:10px;margin-top:18px'>"
            "Données : Dakar Dem Dikk, Tata AFTU · IA : Whisper wolof, NVIDIA Build"
            "</div>"
        )

    bouton.click(trouver_le_bus, inputs=[audio_in, texte_in], outputs=sorties)
    return interface


demo = _construire()


if __name__ == "__main__":
    # queue() est obligatoire pour ZeroGPU : la réservation du GPU ne fonctionne que
    # si les exécutions passent par la file. Sur un Space, Gradio règle tout seul
    # l'hôte et le port à lancer.
    demo.queue().launch()
