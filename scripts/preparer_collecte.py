r"""Prépare les voix collectées par WhatsApp pour le fine-tuning de Whisper wolof.

Utilisation :
    .\.venv\Scripts\python.exe scripts\preparer_collecte.py "chemin\fichier.zip"
    .\.venv\Scripts\python.exe scripts\preparer_collecte.py "chemin\fichier.zip" --depuis 09/10/2026
    .\.venv\Scripts\python.exe scripts\preparer_collecte.py "chemin\fichier.zip" --collecteur TIJAANI
    .\.venv\Scripts\python.exe scripts\preparer_collecte.py --reverifier

On part d'un export de discussion WhatsApp (« Exporter la discussion » +
« Inclure les médias »). Pour chaque note vocale, on récupère le premier texte
utile qui la suit, on convertit l'audio en wav 16 kHz mono et on remplit
data/collecte/metadata.csv. Le texte d'origine y est gardé dans
transcription_brute, et transcription porte la version uniformisée
(NORMALISATION). Jamais pris comme transcription : médias omis, pièces jointes
non audio (.jpg, .mp4...), messages supprimés. Sans lieu reconnu, statut =
sans_lieu : le contrôle passe par les formes de lieux.py (rue et réseau) et,
en complément, par l'extraction LOCALE de l'app (extract_local, jamais de LLM).

--depuis ignore les messages antérieurs à la date de la collecte.
--collecteur : c'est vous ; vos vocaux sont ignorés (et ne coupent pas
l'association), vos textes restent candidats.
--reverifier : sans zip, relit metadata.csv, réapplique NORMALISATION et le
contrôle « lieu » ; le statut ne change qu'entre « ok » et « sans_lieu ».

Vie privée : les noms réels et les numéros ne sortent jamais. Chaque personne
devient locuteur_01, locuteur_02... dans un dossier qui porte ce pseudo-nom.
"""

from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath

EXT_AUDIO = {".opus", ".ogg", ".m4a", ".mp3"}

# Petits messages sans rapport avec la phrase à transcrire.
FILLER = {
    "d'accord", "daccord", "accord", "ok", "okay", "oki", "ko", "merci",
    "merci beaucoup", "thanks", "thank you", "bien", "bien recu", "salam",
    "salaam", "salut", "bonjour", "bonsoir", "coucou", "cc", "oui", "non",
    "ouais", "waaw", "déedéet", "yep", "yes", "no", "reçu", "bien reçu",
}

# Uniformisation de l'orthographe des transcriptions. Les règles portent sur des
# mots entiers, insensibles à la casse ; un nom de lieu ne doit jamais y figurer.
# Clés en minuscules : facile à compléter. Le texte d'origine reste conservé dans
# la colonne transcription_brute de metadata.csv.
NORMALISATION = {
    "magui": "maa ngi",
    "maguii": "maa ngi",
    "mangi": "maa ngi",
    "maa ngui": "maa ngi",
    "man gui": "maa ngi",
    "beugg": "bëgg",
    "beug": "bëgg",
    "bueg": "bëgg",
    "beugue": "bëgg",
    "beuge": "bëgg",
    "begg": "bëgg",
    "dm": "dem",
    "deme": "dem",
    "déme": "dem",
    "démé": "dem",
}

# Colonnes de metadata.csv (transcription_brute ajoutée après coup).
CHAMPS_METADATA = ["file_name", "transcription", "transcription_brute", "locuteur", "duree_s", "statut"]

TAILLE_MAX_TEXTE = 200   # au-delà, ce n'est probablement pas la phrase du vocal
DUREE_MIN = 1.0          # secondes
DUREE_MAX = 30.0         # secondes
RMS_MIN_DBFS = -50.0     # en dessous : audio quasi silencieux

# Début de message Android : "09/10/2026 19:20 - Awa: ..."
LIGNE_ANDROID = re.compile(
    r"^[\u200e\u200f\ufeff]*(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),?\s+"
    r"(?P<heure>\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[APap][Mm])?\s*[-–—]\s*(?P<reste>.*)$"
)
# Début de message iOS : "[09/10/2026, 19:20:00] Awa: ..."
LIGNE_IOS = re.compile(
    r"^[\u200e\u200f\ufeff]*\[(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),?\s+"
    r"(?P<heure>\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[APap][Mm])?\]\s*(?P<reste>.*)$"
)
MEDIA_OMIS = re.compile(r"^<?\s*(?:médias?|medias?)\s+omis\s*>?$|^<?\s*media omitted\s*>?$", re.I)
FICHIER_JOINT = re.compile(r"\((?:fichier joint|file attached|pièce jointe)", re.I)
NOM_AUDIO = re.compile(r"([^\s/\\()]+\.(?:opus|ogg|m4a|mp3))", re.I)
# Messages supprimés : jamais pris comme transcription.
MESSAGE_SUPPRIME = re.compile(
    r"ce message a été supprimé|vous avez supprimé ce message|"
    r"this message was deleted|you deleted this message",
    re.I,
)

_FFMPEG: str | None = None


def _sans_invisibles(texte: str) -> str:
    """Retire les caractères de contrôle invisibles (U+200E, etc.)."""
    return "".join(c for c in texte if unicodedata.category(c) != "Cf")


def _texte_propre(contenu: str) -> str:
    """Texte affichable : invisibles retirés, espaces et retours normalisés."""
    texte = _sans_invisibles(contenu).replace("’", "'")
    return re.sub(r"\s+", " ", texte).strip()


def _uniformiser(texte: str) -> str:
    """Applique NORMALISATION aux mots entiers (casse ignorée), sans toucher au reste.

    Les clés peuvent contenir des espaces (« maa ngui ») : on les essaie par
    longueur décroissante pour que les locutions passent avant les mots seuls.
    """
    if not texte or not NORMALISATION:
        return texte
    alternatives = "|".join(re.escape(m) for m in sorted(NORMALISATION, key=len, reverse=True))
    motif = re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)", re.IGNORECASE)
    return motif.sub(lambda m: NORMALISATION[m.group(0).lower()], texte)


def _parse_date(brut: str | None):
    """« 09/10/2026 » (ou 09.10.2026) -> date(2026, 10, 9). None si illisible."""
    if not brut:
        return None
    morceaux = re.split(r"[/.]", brut)
    if len(morceaux) != 3:
        return None
    try:
        jour, mois, annee = (int(m) for m in morceaux)
    except ValueError:
        return None
    if annee < 100:
        annee += 2000
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def _est_ignorable(contenu: str) -> bool:
    """Vrai pour un message court sans rapport (ok, merci, emoji seul...)."""
    texte = _texte_propre(contenu).lower()
    sans_ponctuation = re.sub(r"[^\w\s']", "", texte).strip()
    if not sans_ponctuation:
        return True
    if sans_ponctuation in FILLER:
        return True
    # Aucune lettre : nombres, ponctuation ou emojis seuls.
    if not any(c.isalpha() for c in sans_ponctuation):
        return True
    return False


def _nom_audio(contenu: str) -> str | None:
    """Renvoie le nom de fichier audio si le message est une note vocale."""
    texte = _texte_propre(contenu)
    if MEDIA_OMIS.match(texte):
        return None
    correspondance = NOM_AUDIO.search(texte)
    if not correspondance:
        return None
    # Fichier joint explicite, ou message réduit au seul nom de fichier.
    if FICHIER_JOINT.search(texte):
        return correspondance.group(1)
    if re.fullmatch(r"[^\s/\\()]+\.(?:opus|ogg|m4a|mp3)", texte, re.I):
        return correspondance.group(1)
    return None


def _message_supprime(contenu: str) -> bool:
    """Vrai si le message a été supprimé (à sauter, comme un média omis)."""
    return bool(MESSAGE_SUPPRIME.search(_texte_propre(contenu)))


def _piece_jointe_non_audio(contenu: str) -> bool:
    """Vrai si c'est une pièce jointe qui n'est pas un audio (.jpg, .mp4, .pdf...).

    Un tel message ne doit jamais servir de transcription.
    """
    texte = _texte_propre(contenu)
    return bool(FICHIER_JOINT.search(texte)) and _nom_audio(texte) is None


def _est_collecteur(expediteur: str | None, collecteur: str | None) -> bool:
    """Vrai si l'expéditeur est celui qui collecte (--collecteur)."""
    if not collecteur:
        return False
    return (expediteur or "").strip().casefold() == collecteur.strip().casefold()


_FORMES_LIEUX: set[str] | None = None


def _formes_lieux() -> set[str]:
    """Formes normalisées des lieux du réseau, comme dans scripts/finetune_whisper.py."""
    global _FORMES_LIEUX
    if _FORMES_LIEUX is not None:
        return _FORMES_LIEUX
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine / "src"))
    from matching.lieux import forme, lieux_reconnaissables

    arrets: set[str] = set()
    csv_itineraires = racine / "data" / "itineraires_dakar.csv"
    if csv_itineraires.exists():
        with open(csv_itineraires, newline="", encoding="utf-8") as fichier:
            for rangee in csv.DictReader(fichier):
                if rangee.get("arret"):
                    arrets.add(rangee["arret"])
    formes = {forme(lieu) for lieu in lieux_reconnaissables(sorted(arrets))}
    formes.add(forme("Palais"))  # terminologie employée par les voyageurs
    _FORMES_LIEUX = {f for f in formes if f}
    return _FORMES_LIEUX


def _contient_lieu(texte: str, formes: set[str]) -> bool:
    """Vrai si le texte mentionne au moins un lieu du réseau (mots entiers).

    formes vide (données absentes) : on ne déclare pas tout « sans lieu », donc True.
    """
    if not formes:
        return True
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine / "src"))
    from matching.lieux import forme

    phrase = forme(texte)
    return any(re.search(r"(?:^| )" + re.escape(f) + r"(?: |$)", phrase) for f in formes)


def _extraction_locale(texte: str) -> bool:
    """Vrai si l'extraction LOCALE de l'app trouve un départ OU une arrivée.

    Seule la partie locale de src/intent/extract_intent.py (extract_local) est
    appelée : jamais de LLM, jamais de réseau.
    """
    if not texte or not texte.strip():
        return False
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine / "src"))
    from intent.extract_intent import extract_local

    resultat = extract_local(texte)
    return bool(resultat.get("depart") or resultat.get("arrivee"))


def _a_un_lieu(texte: str, formes: set[str]) -> bool:
    """Vrai si la phrase porte au moins un lieu de départ ou d'arrivée.

    L'ancien contrôle (formes de lieux.py) reste en complément de l'extraction
    LOCALE de l'app : la phrase est « ok » si l'une ou l'autre trouve un lieu.
    """
    return _contient_lieu(texte, formes) or _extraction_locale(texte)


def _extraire_zip(zip_path: Path, destination: Path) -> list[str]:
    """Extrait seulement les .txt et les audios, après contrôle des chemins."""
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    extraits: list[str] = []

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            nom = info.filename
            normalise = nom.replace("\\", "/")
            morceaux = PurePosixPath(normalise).parts
            # Sécurité : pas de chemin absolu ni de remontée "..".
            if (
                normalise.startswith("/")
                or re.match(r"^[A-Za-z]:", normalise)
                or ".." in morceaux
            ):
                raise ValueError(f"chemin non sûr refusé dans le zip : {nom!r}")
            if info.is_dir():
                continue

            suffixe = PurePosixPath(normalise).suffix.lower()
            if suffixe != ".txt" and suffixe not in EXT_AUDIO:
                continue

            cible = (destination / normalise).resolve()
            if cible != destination and destination not in cible.parents:
                raise ValueError(f"chemin sort du dossier cible : {nom!r}")
            cible.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(cible, "wb") as sortie:
                shutil.copyfileobj(source, sortie)
            extraits.append(str(cible))
    return extraits


def _lire_messages(txt_path: Path) -> list[dict]:
    """Transforme le .txt d'export en liste de messages, multi-lignes compris."""
    messages: list[dict] = []
    courant: dict | None = None
    with open(txt_path, "r", encoding="utf-8-sig", errors="replace") as fichier:
        for brute in fichier:
            ligne = brute.rstrip("\r\n")
            debut = LIGNE_ANDROID.match(ligne) or LIGNE_IOS.match(ligne)
            if debut:
                reste = debut.group("reste")
                entete = re.match(r"([^:\n]{1,60}?):\s?(.*)$", reste, re.S)
                if entete:
                    expediteur, contenu = entete.group(1).strip(), entete.group(2)
                else:
                    expediteur, contenu = None, reste  # message système
                courant = {"expediteur": expediteur, "contenu": contenu, "date": _parse_date(debut.group("date"))}
                messages.append(courant)
            elif courant is not None:
                # Suite d'un message sur plusieurs lignes.
                courant["contenu"] += "\n" + ligne
    return messages


def _indexer_audios(dossier: Path) -> dict[str, Path]:
    """Associe chaque nom de fichier audio présent dans le zip à son chemin."""
    index: dict[str, Path] = {}
    for chemin in dossier.rglob("*"):
        if chemin.is_file() and chemin.suffix.lower() in EXT_AUDIO:
            index.setdefault(chemin.name.lower(), chemin)
    return index


def _ffmpeg(installer_si_besoin: bool = True) -> str:
    """Chemin de ffmpeg : imageio-ffmpeg, puis ffmpeg du PATH, puis installation."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    try:
        import imageio_ffmpeg

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG
    except ImportError:
        pass

    # Un ffmpeg déjà présent sur le système évite une installation réseau.
    chemin = shutil.which("ffmpeg")
    if chemin:
        _FFMPEG = chemin
        return chemin

    if installer_si_besoin:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
                timeout=180,
                check=True,
                capture_output=True,
            )
        except Exception:
            pass
        try:
            import imageio_ffmpeg

            _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
            return _FFMPEG
        except ImportError:
            pass

    raise RuntimeError("ffmpeg introuvable : installe imageio-ffmpeg ou ffmpeg.")


def _convertir_wav(source: Path, destination: Path, ffmpeg: str) -> None:
    """Convertit un audio en wav 16 kHz mono (PCM 16 bits)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    commande = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(destination),
    ]
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0 or not destination.exists():
        raise RuntimeError(resultat.stderr.strip() or "conversion ffmpeg échouée")


def _analyser_wav(chemin: Path) -> tuple[float, float]:
    """Renvoie (durée en secondes, niveau RMS en dBFS)."""
    import numpy as np
    import soundfile as sf

    info = sf.info(str(chemin))
    duree = info.frames / info.samplerate
    donnees, _ = sf.read(str(chemin), dtype="float32", always_2d=False)
    if getattr(donnees, "ndim", 1) > 1:
        donnees = donnees.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(donnees)))) if donnees.size else 0.0
    dbfs = 20 * math.log10(rms) if rms > 0 else float("-inf")
    return duree, dbfs


def _statut_qualite(duree: float, dbfs: float) -> str:
    if duree < DUREE_MIN:
        return "trop_court"
    if duree > DUREE_MAX:
        return "trop_long"
    if dbfs < RMS_MIN_DBFS:
        return "volume_faible"
    return "ok"


def _locuteurs_existants(collecte_dir: Path) -> int:
    """Plus grand numéro de locuteur déjà présent (dossiers et metadata.csv)."""
    plus_grand = 0
    if collecte_dir.exists():
        for enfant in collecte_dir.iterdir():
            trouve = re.fullmatch(r"locuteur_(\d+)", enfant.name)
            if trouve:
                plus_grand = max(plus_grand, int(trouve.group(1)))
        meta = collecte_dir / "metadata.csv"
        if meta.exists():
            with open(meta, "r", encoding="utf-8", newline="") as fichier:
                for ligne in csv.DictReader(fichier):
                    trouve = re.fullmatch(r"locuteur_(\d+)", (ligne.get("locuteur") or "").strip())
                    if trouve:
                        plus_grand = max(plus_grand, int(trouve.group(1)))
    return plus_grand


def _noms_deja_presents(collecte_dir: Path) -> set[str]:
    """file_name déjà écrits, pour ne pas ajouter deux fois le même audio."""
    meta = collecte_dir / "metadata.csv"
    noms: set[str] = set()
    if meta.exists():
        with open(meta, "r", encoding="utf-8", newline="") as fichier:
            for ligne in csv.DictReader(fichier):
                noms.add((ligne.get("file_name") or "").strip())
    return noms


def _migrer_metadata(meta: Path) -> None:
    """Ajoute transcription_brute à un metadata.csv écrit avant cette colonne.

    Les anciennes lignes n'ont que transcription : on la garde telle quelle dans
    transcription_brute et on met la version uniformisée dans transcription.
    """
    if not meta.exists():
        return
    with open(meta, "r", encoding="utf-8", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        champs = lecteur.fieldnames or []
        lignes = list(lecteur)
    if "transcription_brute" in champs:
        return
    for ligne in lignes:
        brute = ligne.get("transcription") or ""
        ligne["transcription_brute"] = brute
        ligne["transcription"] = _uniformiser(brute)
    with open(meta, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=CHAMPS_METADATA, extrasaction="ignore")
        redacteur.writeheader()
        redacteur.writerows(lignes)


def _nom_fichier_sur(nom: str) -> str:
    """Nom de fichier wav sûr à partir du nom d'origine."""
    base = PurePosixPath(nom.replace("\\", "/")).stem
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return base or "vocal"


def traiter_zip(
    zip_path: str | Path,
    brut_dir: str | Path | None = None,
    collecte_dir: str | Path | None = None,
    installer_si_besoin: bool = True,
    depuis: date | None = None,
    collecteur: str | None = None,
) -> dict:
    """Traite un export WhatsApp et renvoie un rapport. Ne rien afficher ici."""
    racine = Path(__file__).resolve().parents[1]
    brut_dir = Path(brut_dir) if brut_dir else racine / "data" / "collecte_brut"
    collecte_dir = Path(collecte_dir) if collecte_dir else racine / "data" / "collecte"
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip introuvable : {zip_path}")

    dossier_brut = brut_dir / zip_path.stem
    if dossier_brut.exists():
        raise FileExistsError(
            f"Ce zip a déjà été traité. Supprime data/collecte_brut/{dossier_brut.name}/ "
            "et les lignes correspondantes de metadata.csv si tu veux le refaire."
        )
    extraits = _extraire_zip(zip_path, dossier_brut)

    textes_export = [Path(p) for p in extraits if Path(p).suffix.lower() == ".txt"]
    messages: list[dict] = []
    for txt in textes_export:
        messages.extend(_lire_messages(txt))

    # --depuis : on jette tout ce qui est antérieur à la date de collecte
    # (vocaux ET textes), puisqu'un export WhatsApp contient tout l'historique.
    ignores_date = 0
    if depuis is not None:
        gardes: list[dict] = []
        for message in messages:
            quand = message.get("date")
            if quand is not None and quand < depuis:
                ignores_date += 1
                continue
            gardes.append(message)
        messages = gardes

    # Repère les notes vocales, les messages système et tout ce qu'on ne prend
    # jamais comme transcription : médias omis, pièces jointes non audio, messages
    # supprimés, et les vocaux du collecteur (--collecteur).
    infos = []
    for message in messages:
        systeme = message.get("expediteur") is None
        nom = _nom_audio(message["contenu"]) if not systeme else None
        texte = _texte_propre(message["contenu"])
        media = bool(
            MEDIA_OMIS.match(texte)
            or _message_supprime(texte)
            or _piece_jointe_non_audio(message["contenu"])
        )
        infos.append(
            {
                "nom_audio": nom,
                "systeme": systeme,
                "media": media,
                "vocal_collecteur": bool(nom) and _est_collecteur(message.get("expediteur"), collecteur),
            }
        )

    index_audio = _indexer_audios(dossier_brut)

    # Les vocaux du collecteur ne comptent pas et ne coupent pas l'association :
    # le vocal d'un participant peut être associé au texte qui suit, même si le
    # collecteur a envoyé un vocal entre les deux.
    positions_vocaux = [i for i, info in enumerate(infos) if info["nom_audio"] and not info["vocal_collecteur"]]
    collecteur_vocaux = sum(1 for info in infos if info["vocal_collecteur"])
    associations: dict[int, int] = {}

    for position in positions_vocaux:
        suivante = next((p for p in positions_vocaux if p > position), len(infos))
        for j in range(position + 1, suivante):
            info = infos[j]
            if info["nom_audio"] or info["systeme"] or info["media"]:
                continue
            texte = _texte_propre(messages[j]["contenu"])
            if not texte or len(texte) > TAILLE_MAX_TEXTE or _est_ignorable(texte):
                continue
            associations[position] = j
            break

    consommes = set(associations.values())

    # Numérotation anonyme, à la suite de ce qui existe déjà.
    base_numero = _locuteurs_existants(Path(collecte_dir))
    suivant = base_numero + 1
    pseudos: dict[str, str] = {}
    for position in positions_vocaux:
        exp = messages[position].get("expediteur") or "inconnu"
        if exp not in pseudos:
            pseudos[exp] = f"locuteur_{suivant:02d}"
            suivant += 1

    ffmpeg = _ffmpeg(installer_si_besoin) if associations else None
    deja_presents = _noms_deja_presents(Path(collecte_dir))
    lignes: list[dict] = []
    rejets: dict[str, int] = {}
    compte_sans_lieu = 0
    formes = _formes_lieux()

    def _rejet(raison: str) -> None:
        rejets[raison] = rejets.get(raison, 0) + 1

    for position in positions_vocaux:
        nom_audio = infos[position]["nom_audio"]
        if position not in associations:
            _rejet("vocal sans texte")
            continue

        source = index_audio.get(nom_audio.lower())
        if source is None:
            _rejet("fichier audio introuvable")
            continue

        transcription = _texte_propre(messages[associations[position]]["contenu"])
        pseudo = pseudos[messages[position].get("expediteur") or "inconnu"]
        nom_wav = f"{_nom_fichier_sur(nom_audio)}.wav"
        relatif = f"{pseudo}/{nom_wav}"
        destination = Path(collecte_dir) / pseudo / nom_wav

        if relatif in deja_presents:
            continue

        try:
            _convertir_wav(Path(source), destination, ffmpeg)
            duree, dbfs = _analyser_wav(destination)
        except Exception:
            _rejet("conversion impossible")
            continue

        statut = _statut_qualite(duree, dbfs)
        if statut == "ok" and not _a_un_lieu(_uniformiser(transcription), formes):
            statut = "sans_lieu"
        if statut == "sans_lieu":
            compte_sans_lieu += 1
        elif statut != "ok":
            _rejet(statut.replace("_", " "))
        lignes.append(
            {
                "file_name": relatif,
                "transcription": _uniformiser(transcription),
                "transcription_brute": transcription,
                "locuteur": pseudo,
                "duree_s": f"{duree:.2f}",
                "statut": statut,
            }
        )

    # Textes utiles qui n'ont servi à aucun vocal.
    textes_sans_vocal = 0
    for i, info in enumerate(infos):
        if i in consommes or info["nom_audio"] or info["systeme"] or info["media"]:
            continue
        texte = _texte_propre(messages[i]["contenu"])
        if texte and len(texte) <= TAILLE_MAX_TEXTE and not _est_ignorable(texte):
            textes_sans_vocal += 1

    meta = Path(collecte_dir) / "metadata.csv"
    _migrer_metadata(meta)
    if lignes:
        Path(collecte_dir).mkdir(parents=True, exist_ok=True)
        nouveau = not meta.exists()
        with open(meta, "a", encoding="utf-8", newline="") as fichier:
            redacteur = csv.DictWriter(fichier, fieldnames=CHAMPS_METADATA)
            if nouveau:
                redacteur.writeheader()
            redacteur.writerows(lignes)

    return {
        "zip": str(zip_path),
        "trouves": len(positions_vocaux),
        "associes": len(associations),
        "sans_texte": len(positions_vocaux) - len(associations),
        "ignores_date": ignores_date,
        "sans_lieu": compte_sans_lieu,
        "collecteur_vocaux_ignores": collecteur_vocaux,
        "textes_sans_vocal": textes_sans_vocal,
        "rejets": rejets,
        "ecrits": len(lignes),
        "locuteurs": sorted(set(pseudos.values())),
    }


def reverifier(meta: Path | None = None) -> int:
    """Relit metadata.csv, réapplique NORMALISATION et refait le contrôle « lieu ».

    Le statut ne change qu'entre « ok » et « sans_lieu » ; trop_court, trop_long
    et volume_faible restent intacts. Aucun fichier audio n'est touché. Le
    fichier est réécrit en UTF-8 sans BOM, avec les mêmes colonnes. Affiche les
    lignes dont la transcription ou le statut change.
    """
    racine = Path(__file__).resolve().parents[1]
    meta = Path(meta) if meta else racine / "data" / "collecte" / "metadata.csv"
    if not meta.exists():
        print(f"metadata.csv introuvable : {meta}")
        return 1

    with open(meta, "r", encoding="utf-8", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        champs = lecteur.fieldnames or []
        lignes = list(lecteur)
    if "transcription_brute" not in champs:
        _migrer_metadata(meta)
        with open(meta, "r", encoding="utf-8", newline="") as fichier:
            lecteur = csv.DictReader(fichier)
            champs = lecteur.fieldnames or []
            lignes = list(lecteur)

    formes = _formes_lieux()
    modifiees = 0
    for ligne in lignes:
        brute = (ligne.get("transcription_brute") or ligne.get("transcription") or "").strip()
        nouveau_texte = _uniformiser(brute)
        ancien_texte = ligne.get("transcription")
        ancien_statut = ligne.get("statut")
        nouveau_statut = ancien_statut

        if ancien_statut in ("ok", "sans_lieu"):
            nouveau_statut = "ok" if _a_un_lieu(nouveau_texte, formes) else "sans_lieu"

        if nouveau_texte != ancien_texte or nouveau_statut != ancien_statut:
            modifiees += 1
            nom = ligne.get("file_name") or "?"
            if nouveau_statut != ancien_statut:
                print(f"  {nom} : statut {ancien_statut} -> {nouveau_statut}")
            if nouveau_texte != ancien_texte:
                print(f"  {nom} : transcription {ancien_texte!r} -> {nouveau_texte!r}")

        ligne["transcription"] = nouveau_texte
        ligne["statut"] = nouveau_statut

    champs_sortie = champs if champs else CHAMPS_METADATA
    with open(meta, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=champs_sortie, extrasaction="ignore")
        redacteur.writeheader()
        redacteur.writerows(lignes)

    print(f"\n{modifiees} ligne(s) modifiée(s) sur {len(lignes)}.")
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    analyseur = argparse.ArgumentParser(
        description="Prépare les voix collectées par WhatsApp pour le fine-tuning."
    )
    analyseur.add_argument("zip", nargs="?", help="export WhatsApp (.zip)")
    analyseur.add_argument(
        "--depuis",
        metavar="JJ/MM/AAAA",
        help="ignore les messages antérieurs à cette date (vocaux ET textes).",
    )
    analyseur.add_argument(
        "--collecteur",
        metavar="NOM",
        help="votre nom dans la discussion : vos vocaux sont ignorés, vos textes restent.",
    )
    analyseur.add_argument(
        "--reverifier",
        action="store_true",
        help="relit data/collecte/metadata.csv : réapplique NORMALISATION et le "
             "contrôle « lieu », sans toucher aux fichiers audio.",
    )
    args = analyseur.parse_args(argv[1:])

    if args.reverifier:
        if args.zip:
            print("--reverifier ne prend pas de chemin de zip.")
            return 2
        return reverifier()

    if not args.zip:
        print(analyseur.format_usage().strip())
        print("preparer_collecte.py : erreur : chemin du zip manquant (ou utilisez --reverifier)")
        return 2

    depuis = _parse_date(args.depuis) if args.depuis else None
    if args.depuis and depuis is None:
        print(f"Date invalide pour --depuis : {args.depuis!r} (attendu JJ/MM/AAAA)")
        return 2

    try:
        rapport = traiter_zip(args.zip, depuis=depuis, collecteur=args.collecteur)
    except FileExistsError as erreur:
        # Erreur attendue (zip déjà traité) : message clair, pas de traceback.
        print(f"\n{erreur}")
        return 1

    print(f"\n=== Rapport - {Path(rapport['zip']).name} ===\n")
    print(f"Vocaux trouvés          : {rapport['trouves']}")
    print(f"Associés à un texte     : {rapport['associes']}")
    print(f"Vocaux sans texte       : {rapport['sans_texte']}")
    print(f"Textes sans vocal       : {rapport['textes_sans_vocal']}")
    if depuis is not None:
        print(f"Messages ignorés (date) : {rapport['ignores_date']}")
    print(f"Sans lieu reconnu        : {rapport['sans_lieu']}")
    if args.collecteur:
        print(f"Vocaux du collecteur    : {rapport['collecteur_vocaux_ignores']} (ignorés)")
    total_rejets = sum(rapport["rejets"].values())
    print(f"Rejetés                 : {total_rejets}")
    for raison, nombre in sorted(rapport["rejets"].items()):
        print(f"   - {raison} : {nombre}")
    print(f"Lignes ajoutées         : {rapport['ecrits']}")
    if rapport["locuteurs"]:
        print(f"Locuteurs anonymisés     : {', '.join(rapport['locuteurs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
