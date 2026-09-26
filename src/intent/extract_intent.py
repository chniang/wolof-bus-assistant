"""Extraction départ/destination via LLM NVIDIA Build (Nemotron 3.5 Lightning).

Entrée : transcription vocale wolof (sortie d'un ASR imparfait).
Sortie  : {"depart": str, "arrivee": str, "erreur": str | None}
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL_NAME = "moonshotai/kimi-k3"
MAX_TOKENS = 300
RETRY_DELAYS = (0, 4, 12)

INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"depart": {"type": "string"}, "arrivee": {"type": "string"}},
    "required": ["depart", "arrivee"],
}

SYSTEM_PROMPT = (
    "Tu reçois la transcription d'une commande vocale en wolof, produite par un "
    "modèle ASR (whisper-small-wolof) imparfait : l'orthographe est phonétique, "
    "bruitée et peut contenir des erreurs. Tu dois extraire exactement 2 champs JSON : "
    "\"depart\" (le lieu de départ, d'où parle l'utilisateur) et \"arrivee\" (le lieu de "
    "destination). Normalise chaque champ vers un nom de lieu plausible de Dakar "
    "(arrêts de bus / quartiers) même si l'orthographe d'entrée est approximative, "
    "par exemple \"gaspaar kamara\" -> \"Gaspar Camara\", \"liberté five\" -> \"Liberté 5\". "
    "Renvoie une chaîne vide (\"\") pour un champ absent ou ambigu. "
    "Réponds avec uniquement le JSON attendu."
)


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)


_load_env()


def get_client() -> "OpenAI":
    """Client OpenAI partagé : à construire une fois puis à réutiliser."""
    from openai import OpenAI

    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY absente : copier .env.example vers .env et renseigner la clé."
        )
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=180)


def _message_content(response) -> str:
    """Contenu utile d'une réponse : `content`, sinon `reasoning_content`.

    kimi-k3 peut renvoyer `content` vide quand le mode reasoning a consommé le
    budget de tokens ; le raisonnement sert alors de repli.
    """
    message = response.choices[0].message
    content = str(getattr(message, "content", None) or "").strip()
    if not content:
        content = str(getattr(message, "reasoning_content", None) or "").strip()
    return content


def _is_usable(content: str) -> bool:
    """Vrai si la réponse contient les deux clés attendues.

    L'API NVIDIA renvoie parfois un contenu corrompu (ex. `{"!!!!!!!!`) avec un
    `finish_reason` `stop` et sans erreur HTTP : ces réponses sont écartées pour
    que la boucle de retry reparte.
    """
    lowered = content.lower()
    return '"depart"' in lowered and '"arrivee"' in lowered


def _call_llm(client, transcription: str) -> str:
    """Renvoie un contenu JSON exploitable, en réessaiant tant que la réponse est fausse.

    kimi-k3 rejette `nvext` / `guided_json` (400 « unknown field ») et possède un mode
    reasoning : on tente donc d'abord `json_object` avec le reasoning coupé via
    `chat_template_kwargs.enable_thinking = False`, puis on retombe sur `guided_json`
    (nvext puis plateau) si la première syntaxe est refusée. L'appel est rejoué sur
    429, sur réponse sans choix et sur contenu vide ou corrompu.
    """
    from openai import BadRequestError, RateLimitError

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": transcription},
    ]
    common = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "stream": False,
    }
    thinking_off = {"chat_template_kwargs": {"enable_thinking": False}}
    attempts = [
        {"response_format": {"type": "json_object"}, "extra_body": thinking_off},
        {"extra_body": {**thinking_off, "nvext": {"guided_json": INTENT_JSON_SCHEMA}}},
        {"extra_body": {**thinking_off, "guided_json": INTENT_JSON_SCHEMA}},
    ]
    last_error: Exception | None = None
    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        for attempt in attempts:
            try:
                response = client.chat.completions.create(**common, **attempt)
            except BadRequestError as exc:
                last_error = exc
                continue
            except RateLimitError as exc:
                last_error = exc
                break
            if not response.choices:
                last_error = RuntimeError("réponse du modèle sans choix (choices vide)")
                continue
            content = _message_content(response)
            if _is_usable(content):
                return content
            last_error = RuntimeError(f"contenu inexploitable : {content[:80]!r}")
    raise RuntimeError(f"Aucune réponse exploitable après {len(RETRY_DELAYS)} tentatives : {last_error}")


def _parse_json_or_fallback(text: str) -> dict:
    """Parse le JSON de la réponse ; sinon extraction par regex des 2 champs."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    matches = {
        "depart": re.search(r'"depart"\s*:\s*"([^"]*)"', cleaned, re.IGNORECASE),
        "arrivee": re.search(r'"arrivee"\s*:\s*"([^"]*)"', cleaned, re.IGNORECASE),
    }
    return {key: (match.group(1) if match else "") for key, match in matches.items()}


def extract_intent(transcription: str, client=None) -> dict:
    """Extrait depart / arrivee d'une transcription wolof bruitée."""
    if not transcription or not transcription.strip():
        return {"depart": None, "arrivee": None, "erreur": "transcription vide"}

    try:
        llm_client = client if client is not None else get_client()
        content = _call_llm(llm_client, transcription)
    except Exception as exc:
        return {
            "depart": None,
            "arrivee": None,
            "erreur": f"requête LLM échouée : {exc}",
        }

    try:
        data = _parse_json_or_fallback(content)
    except Exception as exc:
        return {
            "depart": None,
            "arrivee": None,
            "erreur": f"réponse JSON illisible : {exc}",
        }

    return {
        "depart": str(data.get("depart", "")).strip(),
        "arrivee": str(data.get("arrivee", "")).strip(),
        "erreur": None,
    }


if __name__ == "__main__":
    examples = [
        "dem naa ci liberté five ba palais deu",
        "maa ngi Ouakam, bëgg naa dem Place Leclerc",
        "sant de santee gaspaar kamara",
        "rombon skoa, daldi dem Guédiawaye",
    ]
    print("=" * 64)
    print(f"Test extraction d'intent — modèle {MODEL_NAME}")
    print("=" * 64)
    for phrase in examples:
        print(f"\nPhrase : {phrase}")
        print(extract_intent(phrase))