#!/usr/bin/env python3
"""Télécharge les itinéraires AFTU et Dem Dikk depuis les sites officiels."""

from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path
from typing import List, Tuple

try:
    import requests
    from bs4 import BeautifulSoup
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Dépendances manquantes : {exc}") from exc

RACINE = Path(__file__).resolve().parents[2]
DATA_SOURCES = RACINE / "data" / "sources"

AFTU_LISTE_URL = "https://aftu-senegal.org/infos-pratiques/"
AFTU_LIGNE_BASE = "https://aftu-senegal.org/map/dakar-urbain-ligne-{n}/"

DDD_LISTE_URL = "https://demdikk.sn/info-voyageurs/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _extraire_texte_apres_itineraire(page_text: str) -> str:
    """Retourne le texte brut entre 'ITINERAIRE' et un marqueur suivant."""
    texte = page_text.upper()
    if "ITINERAIRE" not in texte:
        return ""
    idx = texte.find("ITINERAIRE")
    suite = page_text[idx + len("ITINERAIRE") :]
    for marqueur in ["HORAIRES", "TARIFS", "PLAN", "CARTE", "RETARD", "CONTACT", "DOWNLOAD", "\n\n\n"]:
        m = suite.upper().find(marqueur)
        if m != -1 and m < 800:
            suite = suite[:m]
    return suite.strip()


def _nettoyer_itineraire(texte_brut: str) -> str:
    """Nettoie les espaces, tirets, sauts de ligne."""
    if not texte_brut:
        return ""
    texte = re.sub(r"[–—]", "-", texte_brut)
    texte = re.sub(r"\s*\n+\s*", " - ", texte)
    texte = re.sub(r"\s*-\s*", " - ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte


def _extraire_itineraire_page(html: str) -> str:
    """Retourne le texte de l'itinéraire dans le corps de la page (div waymark)."""
    soup = BeautifulSoup(html, "html.parser")
    conteneur = soup.find("div", class_="waymark-meta-item waymark-meta-map_description")
    if conteneur is not None:
        contenu = conteneur.find("div", class_="waymark-meta-content")
        if contenu is not None:
            texte = " ".join(contenu.get_text(" ", strip=True).split())
            texte = re.sub(r"^ITINERAIRE\s*", "", texte, flags=re.IGNORECASE)
            return texte.strip()
    return _extraire_texte_apres_itineraire(html)


def _ligne_carte(a) -> Tuple[str, str, str] | None:
    """Depuis le lien 'Voir itinéraire', renvoie (numero, terminus, url)."""
    if a.get_text(" ", strip=True) != "Voir itinéraire":
        return None
    href = (a.get("href") or "").strip()
    if "aftu-senegal.org" not in href:
        return None
    carte = a.find_parent("div", class_="e-con-full")
    if carte is None:
        return None
    h2 = carte.find("h2", class_="lte-header")
    h6 = carte.find("h6", class_="lte-subheader")
    if h2 is None or h6 is None:
        return None
    m = re.search(r"LIGNE\s*(\d+)", h2.get_text(" ", strip=True), flags=re.IGNORECASE)
    if not m:
        return None
    url = href if href.startswith("http") else f"https://aftu-senegal.org{href}"
    return m.group(1), h6.get_text(" ", strip=True).strip(), url


def telecharger_aftu() -> List[Tuple[str, str, str, str]]:
    """Récupère itinéraires AFTU. Retourne (numero, terminus, url, itineraire)."""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        resp = session.get(AFTU_LISTE_URL, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise SystemExit(f"Impossible d'accéder à {AFTU_LISTE_URL}: {exc}") from exc

    soup = BeautifulSoup(resp.content.decode("utf-8"), "html.parser")
    resultats = []
    vus = set()

    for a in soup.find_all("a", href=True):
        carte = _ligne_carte(a)
        if carte is None:
            continue
        numero, terminus, url = carte
        if numero in vus:
            continue
        vus.add(numero)
        try:
            time.sleep(1)
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except Exception as exc:
            print(f"[AFTU] Échec {url}: {exc}")
            continue
        itin = _nettoyer_itineraire(_extraire_itineraire_page(r.content.decode("utf-8")))
        resultats.append((numero, terminus, url, itin))
        print(f"[AFTU] Ligne {numero} ({terminus}): {len(itin)} car.")

    return sorted(resultats, key=lambda x: int(x[0]))


def telecharger_ddd() -> List[Tuple[str, str, str]]:
    """Récupère itinéraires Dem Dikk."""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        resp = session.get(DDD_LISTE_URL, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise SystemExit(f"Impossible d'accéder à {DDD_LISTE_URL}: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    resultats = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip().lower()
        if "ligne" not in href:
            continue
        if href.startswith("#"):
            continue
        if "demdikk.sn" not in href and not href.startswith("/"):
            continue
        url = href if href.startswith("http") else f"https://demdikk.sn{href}"
        try:
            time.sleep(1)
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except Exception as exc:
            print(f"[DDD] Échec {url}: {exc}")
            continue
        m = re.search(r"ligne\s*(\d+)", r.text.lower())
        if not m:
            m = re.search(r"ligne-(\d+)", url)
        if not m:
            continue
        numero = m.group(1)
        itin = _nettoyer_itineraire(_extraire_texte_apres_itineraire(r.text))
        resultats.append((numero, url, itin))
        print(f"[DDD] Ligne {numero}: {len(itin)} car.")

    return sorted({(n, u, i) for n, u, i in resultats}, key=lambda x: int(x[0]))


def sauvegarder(nom_base: str, donnees: list) -> None:
    DATA_SOURCES.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    chemin = DATA_SOURCES / f"{nom_base}_{date}.txt"
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(f"# Source: {nom_base.upper()} - {date}\n")
        for info in donnees:
            if len(info) == 4:
                numero, terminus, url, itin = info
                f.write(f"{numero} | {terminus} | {url} | {itin}\n")
            else:
                numero, url, itin = info
                f.write(f"\n=== LIGNE {numero} ===\n")
                f.write(f"URL: {url}\n")
                f.write(f"ITINERAIRE_BRUT: {itin}\n")
    print(f"Écrit: {chemin}")


def main():
    print("=== Téléchargement itinéraires ===")
    aftu = telecharger_aftu()
    sauvegarder("aftu_itineraires", aftu)
    ddd = telecharger_ddd()
    sauvegarder("ddd_itineraires", ddd)


if __name__ == "__main__":
    main()
