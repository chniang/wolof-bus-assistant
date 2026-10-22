"""Prépare une fois pour toutes les audios de la démo.

Synthétiser coûte environ 4x le temps réel sur ce portable : le faire en direct
devant un jury, c'est prendre un risque. Ce script génère donc tous les cas
possibles — une voix par ligne du jeu de données, plus les phrases de service
(« walla », « Walla, », « Ci ginnaaw, ») — et l'app se contente ensuite de coller
les bons morceaux, sans même charger le modèle.

    python src/tts/pregenerer.py

Les fichiers déjà présents sont sautés, on peut donc relancer sans rien casser.
Une fois le cache complet, il n'est plus nécessaire de garder le TTS en mémoire,
et l'app ne le charge plus au démarrage.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
CSV_LIGNES = RACINE / "data" / "lignes_dakar.csv"

sys.path.insert(0, str(RACINE / "src"))

from tts.speak import (  # noqa: E402  (après l'ajout au sys.path)
    AUCUNE_LIGNE,
    CACHE_DIR,
    LIAISON_CORRESPONDANCE,
    MARQUEUR,
    WALLA,
    WALLA_AUTRE,
    load_tts,
    nom_cache_match,
    phrase_reponse,
    synthetiser,
)

# Les phrases de service, absentes du CSV.
PHRASES_SERVICE = [
    (AUCUNE_LIGNE, "Baal ma, gisuma bus bu dem fa."),
    (WALLA, "walla"),
    (WALLA_AUTRE, "Walla,"),
    (LIAISON_CORRESPONDANCE, "Ci ginnaaw,"),
]


def lignes_du_csv() -> list[tuple[str, str]]:
    """Tous les couples (compagnie, ligne) du jeu de données, sans doublon.

    On garde aussi les lignes sans numéro (« TAF TAF ») : elles s'affichent et
    doivent donc s'entendre, avec leur propre audio.
    """
    import csv

    couples = set()
    with open(CSV_LIGNES, newline="", encoding="utf-8") as fichier:
        records = list(csv.DictReader(fichier))
    for record in records:
        ligne = str(record.get("ligne", "")).strip()
        if ligne:
            couples.add((str(record.get("compagnie", "")).strip(), ligne))
    return sorted(couples)


def cibles() -> list[tuple[str, str]]:
    """Chaque audio à produire : nom de fichier et phrase à dire, sans doublon."""
    liste = []
    vus = set()
    for compagnie, ligne in lignes_du_csv():
        match = {"compagnie": compagnie, "ligne": ligne}
        nom = nom_cache_match(match)
        if nom in vus:
            continue
        vus.add(nom)
        liste.append((nom, phrase_reponse([match])))
    return liste + [(nom, phrase) for nom, phrase in PHRASES_SERVICE if nom not in vus]


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    a_produire = cibles()
    print(f"{len(a_produire)} audios à préparer dans {CACHE_DIR}")

    modele = None
    debut_global = time.perf_counter()
    produits = 0

    for nom, phrase in a_produire:
        chemin = CACHE_DIR / nom
        if chemin.is_file():
            print(f"  déjà présent  {nom}")
            continue
        if modele is None:
            print("Chargement du modèle TTS …")
            modele = load_tts()
        debut = time.perf_counter()
        chemin.write_bytes(synthetiser(modele, phrase))
        produits += 1
        print(f"  {nom:26s} {time.perf_counter() - debut:5.1f}s  {phrase!r}")

    total = time.perf_counter() - debut_global
    manquants = [nom for nom, _ in a_produire if not (CACHE_DIR / nom).is_file()]

    if manquants:
        # Sans marqueur, l'app considère que le cache est incomplet et garde le
        # modèle TTS sous la main, donc on prévient de ce qui a échoué.
        print(f"\n{len(manquants)} audio(s) manquant(s) : {', '.join(manquants)}")
        return 1

    MARQUEUR.write_text(
        f"{len(a_produire)} audios prêts, préparés en {total:.0f}s le "
        f"{time.strftime('%Y-%m-%d')}\n",
        encoding="utf-8",
    )
    volume = sum((CACHE_DIR / nom).stat().st_size for nom, _ in a_produire)
    print(f"\n{produits} fichier(s) créé(s) en {total:.1f}s")
    print(f"cache complet : {len(a_produire)} audios, {volume / 1024 / 1024:.1f} Mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
