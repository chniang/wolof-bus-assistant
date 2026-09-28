"""Extraction départ/destination via LLM NVIDIA Build (GLM 5.3 Flash).

Entrée : transcription vocale wolof (sortie d'un ASR imparfait).
Sortie  : {"depart": str, "arrivee": str, "erreur": str | None}
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "arrets_lignes_dakar.csv"

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# La réponse tient en ~23 tokens : 120 laisse une marge large sans rien
# laisser trainer côté génération.
MAX_TOKENS = 120

# L'API NVIDIA est saturée pendant le hackathon. Devant le jury, mieux vaut une
# extraction locale approximative en 15 s qu'une attente qui s'étire : un seul
# appel, aucun retry, et le repli local prend le relais dès le timeout.
# En ligne (Hugging Face Space), on peut se permettre d'attendre plus longtemps :
# la variable LLM_TIMEOUT, réglée dans les Settings du Space, remplace les 15 s.
TIMEOUT_APPEL = int(os.getenv("LLM_TIMEOUT", "15"))
RETRY_DELAYS = (0,)  # pas de retry

# Un seul modèle : meta/llama-3.1-8b-instruct est retiré car NVIDIA le renvoie
# 410 Gone (fin de vie), ce qui ne le rendait de toute façon pas utilisable.
# La chaîne reste écrite pour en accepter plusieurs le jour où un second modèle
# redevient disponible.
MODELES = ("z-ai/glm-5.3-flash",)

# Plafond global sur la chaîne. Le budget est vérifié avant chaque appel, et il n'y
# a qu'un appel : le pire cas est donc un seul TIMEOUT_APPEL, soit 15 s.
BUDGET_CHAINE = TIMEOUT_APPEL

INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"depart": {"type": "string"}, "arrivee": {"type": "string"}},
    "required": ["depart", "arrivee"],
}

def _charger_lieux() -> list[str]:
    """Lieux uniques du CSV, triés : la seule référence de noms qu'on accepte du LLM."""
    with open(CSV_PATH, newline="", encoding="utf-8") as fichier:
        lieux = {
            str(ligne[column]).strip()
            for ligne in csv.DictReader(fichier)
            for column in ("depart", "arrivee")
            if ligne.get(column) and str(ligne[column]).strip()
        }
    return sorted(lieux)


LIEUX = _charger_lieux()


def _build_system_prompt() -> str:
    """Prompt système contraint par LIEUX, pour que le LLM n'invente pas de quartiers."""
    return (
        "Tu reçois la transcription d'une commande vocale en wolof, produite par un "
        "modèle ASR (whisper-small-wolof) imparfait : l'orthographe est phonétique, "
        "bruitée et peut contenir des erreurs. Tu dois extraire exactement 2 champs JSON : "
        "\"depart\" (le lieu de départ, d'où parle l'utilisateur) et \"arrivee\" (le lieu de "
        "destination).\n\n"
        "Voici la liste EXHAUSTIVE des lieux desservis par le réseau de bus :\n"
        + "\n".join(f"- {lieu}" for lieu in LIEUX)
        + "\n\n"
        "Règles de normalisation :\n"
        "- Si le lieu entendu ressemble phonétiquement à un lieu de la liste, renvoie "
        "EXACTEMENT le nom de la liste. Exemples : 'wakaam' -> 'Ouakam', 'géejawaay' ou "
        "'géej a waay' -> 'Guédiawaye', 'pale'/'palee'/'pali' -> 'Palais'.\n"
        "- Si 'Palais' est dit sans numéro, renvoie 'Palais' (sans 1 ni 2).\n"
        "- N'invente jamais un quartier qui n'est pas prononcé. Si aucun lieu de la liste "
        "ne correspond, renvoie le nom entendu, normalisé.\n"
        "- Renvoie une chaîne vide (\"\") pour un champ absent ou ambigu.\n"
        "Réponds avec uniquement le JSON attendu."
    )


SYSTEM_PROMPT = _build_system_prompt()


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
    # max_retries=0 est indispensable : le SDK retente deux fois de lui-même et
    # triple le délai (mesuré, 65 s pour un timeout réglé à 20 s). Nos tentatives
    # sont gérées dans _call_llm, qui respecte l'ordre des modèles.
    return OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=api_key,
        timeout=TIMEOUT_APPEL,
        max_retries=0,
    )


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


def _call_modele(client, modele: str, transcription: str) -> str:
    """Interroge un seul modèle et renvoie son contenu JSON exploitable.

    Lève dès que le modèle ne livre rien d'utile : c'est l'appelant qui décide de
    repasser ou non. On tente d'abord `json_object` avec le reasoning coupé via
    `chat_template_kwargs.enable_thinking = False`, puis on retombe sur `guided_json`
    (nvext puis plateau) si la plateforme refuse la syntaxe.
    """
    from openai import BadRequestError

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": transcription},
    ]
    common = {
        "model": modele,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "stream": False,
    }
    thinking_off = {"chat_template_kwargs": {"enable_thinking": False}}
    variantes = [
        {"response_format": {"type": "json_object"}, "extra_body": thinking_off},
        {"extra_body": {**thinking_off, "nvext": {"guided_json": INTENT_JSON_SCHEMA}}},
        {"extra_body": {**thinking_off, "guided_json": INTENT_JSON_SCHEMA}},
    ]

    last_error: Exception | None = None
    for variante in variantes:
        try:
            response = client.chat.completions.create(**common, **variante)
        except BadRequestError as exc:
            # Syntaxe refusée : seule une autre variante peut sauver cet appel.
            # Un timeout, lui, doit remonter tout de suite au modèle suivant.
            last_error = exc
            continue
        if not response.choices:
            last_error = RuntimeError("réponse du modèle sans choix (choices vide)")
            break
        content = _message_content(response)
        if _is_usable(content):
            return content
        last_error = RuntimeError(f"contenu inexploitable : {content[:80]!r}")
        break

    raise RuntimeError(f"{modele} : {last_error}")


def _call_llm(client, transcription: str) -> tuple[str, str]:
    """Parcourt la chaîne de modèles et renvoie (contenu, modèle ayant répondu).

    Aujourd'hui un seul modèle et une seule tentative : l'attente est plafonnée par
    TIMEOUT_APPEL, après quoi l'extraction locale prend le relais. Le budget global
    protège le jour où un second modèle est réintroduit dans MODELES, pour ne pas
    enchaîner les temps d'attente : mieux vaut une extraction locale approximative
    qu'une minute devant un écran vide.
    """
    echecs: list[str] = []
    debut_chaine = time.monotonic()

    for modele in MODELES:
        for delay in RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            if time.monotonic() - debut_chaine > BUDGET_CHAINE:
                echecs.append(f"budget de {BUDGET_CHAINE}s atteint, API abandonnée")
                raise RuntimeError(" ; ".join(echecs))
            try:
                return _call_modele(client, modele, transcription), modele
            except Exception as exc:
                echecs.append(str(exc))

    raise RuntimeError(" ; ".join(echecs))


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


# --------------------------------------------------------------------------- #
# Extraction locale : le filet de sécurité quand l'API ne répond pas.
# --------------------------------------------------------------------------- #

# L'ASR écrit ce qu'il entend, et il colle les mots entre eux : « wakaam » arrive
# souvent collé à ce qui le précède (« yewakaam ») et « pale » collé à « dem »
# (« dempale »). Les règles ci-dessous sont donc ancrées à droite seulement : la
# forme phonétique doit finir un mot, mais elle peut en commencer un autre.
#
# « medina » et « grand mbao » sont déjà dans leur forme canonique, ils n'ont besoin
# d'aucune règle de réécriture.
REPLACEMENTS_PHRASE = (
    (r"(?:geej\s*a\s*waay|geejawaay)\b", " guediawaye "),
    # (?<!ou) protège la graphie canonique : sans lui « ouakam » deviendrait
    # « ou ouakam », la règle réécrivant son propre suffixe.
    (r"(?<!ou)(?:wakaam|wakam)\b", " ouakam "),
    (r"(?:palee|pale|pali)\b", " palais "),
    (r"meddina\b", " medina "),
)

# En dessous de ce ratio, on préfère ne rien trouver plutôt qu'inventer un quartier.
# « palais » vs « palais 1 » vaut 0.9 (préfixe), un n-gramme exact vaut 1.0.
SEUIL_FUZZY = 0.72
TAILLE_NGRAMMES = 3
# En dessous, un mot trop court (« de », « naa ») produirait des scores parasites.
LONGUEUR_MIN = 4

# Le CSV distingue « Palais 1 » et « Palais 2 » : quand le numéro n'est pas prononcé,
# « Palais » seul doit rester acceptable, exactement comme le fait le LLM.
LIEUX_SUPPLEMENTAIRES = ("Palais",)


def _sans_accents(texte: str) -> str:
    """Minuscules et accents retirés : la comparaison ignore l'orthographe."""
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texte.lower())
        if unicodedata.category(caractere) != "Mn"
    )


# Construit après _sans_accents : une liste comprehendue au niveau du module est
# évaluée immédiatement, elle a besoin de la fonction déjà définie.
_CIBLES = [(_sans_accents(lieu), lieu) for lieu in LIEUX] + [
    (_sans_accents(lieu), lieu) for lieu in LIEUX_SUPPLEMENTAIRES
]


def _normaliser_phrase(phrase: str) -> str:
    """Forme de travail : minuscules, sans accents, graphies phonétiques corrigées.

    Les espaces sont resserrés en fin de fonction : les remplacements ci-dessus en
    injectent, et la ponctuation en transforme d'autres en espaces.
    """
    texte = _sans_accents(phrase)
    for motif, remplacement in REPLACEMENTS_PHRASE:
        texte = re.sub(motif, remplacement, texte)
    # L'ASR colle la préposition au mot suivant (« dempale ») : on la rouvre pour que
    # la répartition départ / arrivée reste possible grâce à la position de « dem ».
    texte = re.sub(r"\bdem(?=[a-z])", "dem ", texte)
    texte = re.sub(r"[^a-z0-9\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def _score(gramme: str, lieu: str) -> float:
    """Similarité d'un n-gramme avec un lieu du CSV, entre 0 et 1."""
    if gramme == lieu:
        return 1.0
    if min(len(gramme), len(lieu)) < LONGUEUR_MIN:
        return 0.0
    # Un préfixe commun (« palais » dans « palais 1 ») vaut mieux qu'une simple
    # proximité de caractères, mais moins bien qu'une égalité.
    if lieu.startswith(gramme) or gramme.startswith(lieu):
        return 0.9
    return SequenceMatcher(None, gramme, lieu).ratio()


def _chercher_lieux(mots: list[str]) -> list[tuple[int, int, str]]:
    """Lieux du CSV repérés dans la phrase, par n-grammes de 1 à 3 mots.

    Renvoie (début, fin, nom exact du CSV) triés par position dans la phrase.
    """
    candidats: list[tuple[float, int, int, str]] = []
    for taille in range(1, TAILLE_NGRAMMES + 1):
        for debut in range(len(mots) - taille + 1):
            gramme = " ".join(mots[debut : debut + taille])
            if len(gramme) < LONGUEUR_MIN:
                continue
            for lieu_normalise, lieu_exact in _CIBLES:
                score = _score(gramme, lieu_normalise)
                if score >= SEUIL_FUZZY:
                    candidats.append((score, debut, debut + taille, lieu_exact))

    # Meilleur score d'abord, puis le plus long span : à score égal, « palais 2 »
    # doit l'emporter sur le « palais » du même endroit.
    candidats.sort(key=lambda c: (-c[0], -(c[2] - c[1]), c[1]))

    retenus: list[tuple[int, int, str]] = []
    for _, debut, fin, lieu_exact in candidats:
        # Deux n-grammes qui se chevauchent ne peuvent pas viser deux lieux distincts.
        if any(debut < r_fin and r_debut < fin for r_debut, r_fin, _ in retenus):
            continue
        retenus.append((debut, fin, lieu_exact))

    retenus.sort(key=lambda r: r[0])
    return retenus


def extract_local(phrase: str) -> dict:
    """Extrait départ et arrivée sans LLM, par correspondance floue sur le CSV.

    Renvoie le même format que extract_intent, avec source="local" : l'application
    n'a pas à savoir par quel étage la réponse est passée.
    """
    if not phrase or not phrase.strip():
        return {"depart": None, "arrivee": None, "erreur": "transcription vide", "source": "local"}

    mots = _normaliser_phrase(phrase).split()
    trouves = _chercher_lieux(mots)
    if not trouves:
        return {"depart": "", "arrivee": "", "erreur": None, "source": "local"}

    # « bëgg naa dem Palais 2 » : ce qui précède « dem » est le départ, ce qui suit
    # est l'arrivée. Sans « dem », ou sans répartition propre, on garde l'ordre
    # d'apparition dans la phrase.
    position_dem = mots.index("dem") if "dem" in mots else -1
    if position_dem >= 0 and len(trouves) >= 2:
        avant = [t for t in trouves if t[1] <= position_dem]
        apres = [t for t in trouves if t[0] >= position_dem]
        if avant and apres:
            return {
                "depart": avant[0][2],
                "arrivee": apres[0][2],
                "erreur": None,
                "source": "local",
            }

    return {
        "depart": trouves[0][2],
        "arrivee": trouves[1][2] if len(trouves) > 1 else "",
        "erreur": None,
        "source": "local",
    }


def _repli_local(transcription: str, raison: str) -> dict:
    """Bascule sur l'extraction locale, et n'alerte que si un des deux lieux manque."""
    # On garde une trace de la vraie cause dans les logs (ceux du Space en ligne) :
    # sans elle, impossible de savoir si l'API a expiré, refusé la clé ou autre.
    print(f"[repli local] {raison}", flush=True)
    resultat = extract_local(transcription)
    if resultat.get("depart") and resultat.get("arrivee"):
        return resultat
    return {**resultat, "erreur": raison}


def extract_intent(transcription: str, client=None) -> dict:
    """Extrait depart / arrivee d'une transcription wolof bruitée.

    Trois étages : l'API NVIDIA (deux modèles, un retry chacun), puis
    l'extraction locale. L'échec de l'API n'est jamais remonté comme une erreur tant
    que la phrase porte ses deux lieux : pendant un hackathon, une démo qui
    répond à moitié vaut mieux qu'un écran d'erreur.
    """
    if not transcription or not transcription.strip():
        return {"depart": None, "arrivee": None, "erreur": "transcription vide", "source": "local"}

    try:
        llm_client = client if client is not None else get_client()
        content, _modele = _call_llm(llm_client, transcription)
    except Exception as exc:
        return _repli_local(transcription, f"requête LLM échouée : {exc}")

    try:
        data = _parse_json_or_fallback(content)
    except Exception as exc:
        return _repli_local(transcription, f"réponse JSON illisible : {exc}")

    return {
        "depart": str(data.get("depart", "")).strip(),
        "arrivee": str(data.get("arrivee", "")).strip(),
        "erreur": None,
        "source": "llm",
    }


if __name__ == "__main__":
    examples = [
        "dem naa ci liberté five ba palais deu",
        "maa ngi Ouakam, bëgg naa dem Place Leclerc",
        "sant de santee gaspaar kamara",
        "rombon skoa, daldi dem Guédiawaye",
    ]
    print("=" * 64)
    print(f"Test extraction d'intent — chaîne {' puis '.join(MODELES)}")
    print("=" * 64)
    for phrase in examples:
        print(f"\nPhrase : {phrase}")
        print(extract_intent(phrase))