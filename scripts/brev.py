r"""Adapte les notebooks voix « Colab » pour une machine GPU NVIDIA Brev.

Chez Brev, c'est du Jupyter tout court : pas de Google Drive à monter, pas de
secrets « userdata », et le redémarrage forcé du kernel (`os.kill`) n'a pas
lieu d'être. Ce module reprend les notebooks Colab déposés dans notebooks/
et réécrit, cellule par cellule, les quatre endroits qui dépendent de Colab :

  - l'intro (markdown) : mode d'emploi Brev (machine, dossier, zip) ;
  - le pip : `%pip` sans redémarrage forcé, plus une note de redémarrage ;
  - la cellule Drive : remplacée par un dossier local ./sortie_voix/ ;
  - la cellule Whisper : jeton HF lu caché (getpass / variable HF_TOKEN) ;
  - la cellule finale : zip dans sortie_voix/, pas de téléchargement auto.

Toutes les autres cellules (plan, outils de vérification, Oolel, génération)
ne bougent pas d'un octet : mêmes réglages (graine 1234, 3 essais, Whisper
garde le meilleur, reprise dans le dossier de sortie).

Usage :
    .\.venv\Scripts\python.exe scripts\brev.py
    → écrit notebooks/voix_test_prononciation_brev.ipynb
      et notebooks/voix_oolel_complete_brev.ipynb
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
NOTEBOOKS = RACINE / "notebooks"

TEST_COLAB = NOTEBOOKS / "voix_test_prononciation_colab.ipynb"
COMPLET_COLAB = NOTEBOOKS / "voix_oolel_complete.ipynb"

# Ce qui ne doit PLUS apparaître dans un notebook Brev (ce sont des choses
# propres à Colab). La moindre trace = bug de transformation.
RESTES_COLAB = ("google.colab", "drive.mount", "userdata", "os.kill", "files.download")

PIPS_PREFIXE = "!pip -q install "

NOTE_PIP = """\
> **Après la cellule pip :** si Jupyter demande un **redémarrage du noyau**
> (Kernel → Restart Kernel), accepte-le puis relance tout depuis le début :
> la reprise saute les audios déjà écrits dans `sortie_voix/`. Sans demande
> de Jupyter, rien à faire, continue normalement.
"""

DOSSIER_TEST = """\
# Tout atterrit ici, à côté du notebook : audios, rapport, voix de référence.
import os, glob, shutil

BASE = './sortie_voix'
SORTIE = f'{BASE}/audios'
RAPPORT = f'{BASE}/rapport_test_prononciation.csv'
REF = f'{BASE}/8_1_c.wav'
os.makedirs(SORTIE, exist_ok=True)
if not os.path.exists(REF):
    from huggingface_hub import hf_hub_download
    telecharge = hf_hub_download(
        repo_id='soynade-research/Oolel-Voices-Demo',
        repo_type='space',
        filename='8_1_c.wav',
    )
    shutil.copy(telecharge, REF)
print('voix de référence :', REF)
print('déjà faits :', len(glob.glob(f'{SORTIE}/*.wav')), '/ 12')
"""

DOSSIER_COMPLETE = """\
# Tout atterrit ici, à côté du notebook : audios, rapport, voix de référence.
# La reprise après coupure relit ce dossier : chaque audio fait n'est plus refait.
import os, glob, shutil

BASE = './sortie_voix'
SORTIE = f'{BASE}/tts_cache_oolel'
RAPPORT = f'{BASE}/rapport_voix_complete.csv'
REF = f'{BASE}/8_1_c.wav'
os.makedirs(SORTIE, exist_ok=True)
if not os.path.exists(REF):
    from huggingface_hub import hf_hub_download
    telecharge = hf_hub_download(
        repo_id='soynade-research/Oolel-Voices-Demo',
        repo_type='space',
        filename='8_1_c.wav',
    )
    shutil.copy(telecharge, REF)
print('voix de référence :', REF)
print('déjà faits :', len(glob.glob(f'{SORTIE}/*.wav')), '/ 869')
"""

# Le bloc « Secret Colab » de la cellule Whisper est remplacé entre les lignes
# « try: ... google.colab » et « print("Secret HF_TOKEN ... » : on ne réécrit
# que le jeton, le reste de la cellule (chargement du modèle public de repli)
# reste identique.
TOKEN_NOUVEAU = """\
# Jeton caché : variable d'environnement d'abord, saisie masquée ensuite.
# Jamais affiché, jamais écrit dans le notebook.
import getpass

HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
if not HF_TOKEN:
    HF_TOKEN = getpass.getpass(
        'Jeton Hugging Face (saisie cachée, vide pour passer) : '
    ).strip()
HF_TOKEN = HF_TOKEN or None

if HF_TOKEN is None:
    print('Jeton absent : repli sur le modèle public', WHISPER_SECOURS)
"""

GPU_ANCIEN = "assert torch.cuda.is_available(), 'Active le GPU T4'"
GPU_NOUVEAU = (
    "assert torch.cuda.is_available(), 'Pas de GPU visible : choisis une "
    "machine T4 ou L4 (voir notebooks/BREV_LIRE_MOI.md)'"
)

FIN_TEST = """\
# Vérifier le dossier et préparer le zip à télécharger depuis Jupyter
manquants = [p['fichier'] for p in PHRASES if not os.path.exists(f"{SORTIE}/{p['fichier']}")]
assert not manquants, f"{len(manquants)} audios manquants : relance la cellule de génération."
shutil.copy(RAPPORT, f'{SORTIE}/rapport_test_prononciation.csv')
archive = shutil.make_archive('./sortie_voix/voix_test', 'zip', SORTIE)
print('12 variantes OK — zip prêt (panneau de gauche de Jupyter) :', archive)
"""

FIN_COMPLETE = """\
# Vérifier le dossier et préparer le zip pour installer_voix_oolel.py
manquants = [p['fichier'] for p in PHRASES if not os.path.exists(f"{SORTIE}/{p['fichier']}")]
assert not manquants, f"{len(manquants)} audios manquants (ex. {manquants[:5]}) : relance la cellule de génération."
shutil.copy(RAPPORT, f'{SORTIE}/rapport_voix_complete.csv')
archive = shutil.make_archive('./sortie_voix/tts_cache_oolel', 'zip', SORTIE)
print(
    '869 audios OK — sur ton PC : python scripts/installer_voix_oolel.py --zip sortie_voix/tts_cache_oolel.zip'
)
"""

INTRO_TEST = """\
# GuindiMa — test de prononciation de la voix Oolel native (sur Brev)

Voix : celle du **Space soynade-research/Oolel-Voices-Demo**, fichier `8_1_c.wav`
(la voix de référence conseillée par la documentation d'Oolel-Voices). Aucune
voix Adia : tout se télécharge, rien à importer.

Un seul fichier par variante (3 essais, Whisper wolof garde le meilleur,
graine 1234) — les mêmes réglages que les autres séries.

**Machine :** GPU NVIDIA (T4 ou L4) chez Brev — pas de Google Drive : tout est
écrit dans `sortie_voix/`, à côté du notebook. Voir `notebooks/BREV_LIRE_MOI.md`.

**Jeton 🔑 :** la cellule Whisper demande le jeton `HF_TOKEN` en saisie cachée
(getpass), ou le lit dans la variable d'environnement `HF_TOKEN`. Rien ne
s'affiche, rien n'est écrit dans le notebook. Jeton vide → repli sur le
Whisper wolof public.

**Lancer :** Run All. La cellule pip installe les paquets sans redémarrer le
noyau ; si Jupyter demande malgré tout un redémarrage (note sous la cellule),
accepte-le et refais Run All : la reprise saute ce qui est déjà fait.

**À l'écoute :** les audios arrivent dans `sortie_voix/audios/`, le zip final
est `sortie_voix/voix_test.zip` (téléchargeable depuis le panneau de gauche
de Jupyter).
- « biis / bis », « Taaf Taaf / Taf Taf / Tafe Tafe », « Akapes / Akaapes »,
  « Albeer Saróo / Alber Saroo », « Aseknaa / Asekna » : noter la lecture de
  « ee », « aa », la forme de Wakaam…
- Puis remplir le lexique `src/tts/lexique_prononciation.py` (clé = écran,
  valeur = orthographe que la voix sait dire), regénérer la liste complète
  (`scripts/preparer_regen_oolel.py`) et le notebook des 869 audios
  (`scripts/preparer_notebook_oolel.py`).
"""

INTRO_COMPLETE = """\
# GuindiMa AI — les 869 audios avec la voix native d'Oolel (sur Brev)

La voix est celle du **Space soynade-research/Oolel-Voices-Demo** (`8_1_c.wav`).
Mêmes réglages que les 637 et les 232 ajouts : graine 1234, 3 essais par audio,
Whisper wolof garde le meilleur. Liste : `data/audit/voix_complete.csv`
(texte final du lexique `src/tts/lexique_prononciation.py`).

**Machine :** GPU NVIDIA (T4 ou L4) chez Brev — pas de Google Drive : les
audios s'écrivent dans `sortie_voix/tts_cache_oolel/`, à côté du notebook.
Voir `notebooks/BREV_LIRE_MOI.md`.

**Jeton 🔑 :** la cellule Whisper demande le jeton `HF_TOKEN` en saisie cachée
(getpass), ou le lit dans la variable d'environnement `HF_TOKEN`. Rien ne
s'affiche, rien n'est écrit dans le notebook. Jeton vide → repli sur le
Whisper wolof public.

**Lancer :** Run All. La cellule pip installe les paquets sans redémarrer le
noyau ; si Jupyter demande malgré tout un redémarrage (note sous la cellule),
accepte-le et refais Run All : la reprise saute les audios déjà dans
`sortie_voix/tts_cache_oolel/`.

Durée : environ 2 h 30 à 3 h 30 (869 audios × 3 essais, Whisper écoute).
À la fin, télécharge `sortie_voix/tts_cache_oolel.zip` (panneau de gauche de
Jupyter), puis sur ton PC :
`python scripts/installer_voix_oolel.py --zip sortie_voix/tts_cache_oolel.zip`.
Éteins la machine Brev une fois le zip téléchargé.
"""


def _source(cellule: dict) -> str:
    return "".join(cellule["source"])


def _cel(cells, marker, what):
    hits = [i for i, c in enumerate(cells) if c["cell_type"] == "code" and marker in _source(c)]
    if len(hits) != 1:
        raise ValueError(f"{what} : cellule {marker!r} attendue une fois, trouvée {len(hits)} fois")
    return hits[0]


def _md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _remplace_token(src: str) -> str:
    """Remplace le bloc « Secret Colab » dans le texte brut de la cellule Whisper.

    Bornage sans deviner : on part de « try: / from google.colab import
    userdata » et on résère jusqu'à la fin du print « … WHISPER_SECOURS) ».
    La ligne de commentaire juste avant (propre aux secrets Colab) est
    enlevée si elle est là ; tout ce qui suit (chargement du modèle, repli
    public) reste tel quel.
    """
    try_anchor = "try:\n    from google.colab import userdata\n"
    i = src.index(try_anchor)
    commentaire = "# Secret Colab ; hors Colab, on accepte aussi la variable d'environnement.\n"
    if src[:i].endswith(commentaire):
        i -= len(commentaire)
    suivi = "WHISPER_SECOURS)\n"
    k = src.index(suivi, i) + len(suivi)
    return src[:i] + TOKEN_NOUVEAU + src[k:]


def _adapter(nb: dict, intro: str, dossier: str, fin: str) -> dict:
    # 1) intro markdown : mode d'emploi Brev
    cells = nb["cells"]
    for c in cells:
        if c["cell_type"] == "markdown":
            c["source"] = intro.splitlines(keepends=True)
            break
    else:
        raise ValueError("notebook : cellule markdown d'intro introuvable")

    # 2) pip : %pip, sans os.kill ; on garde la liste de paquets telle quelle
    i_pip = _cel(cells, "!pip -q install", "pip")
    old_pip = _source(cells[i_pip])
    if "os.kill" not in old_pip:
        raise ValueError("pip : la version Colab devrait redémarrer (os.kill)")
    paquets = old_pip.splitlines()[0][len(PIPS_PREFIXE):]
    cells[i_pip]["source"] = (
        "# Les paquets des versions Colab, à l'identique. %pip installe dans le\n"
        "# noyau courant : pas de redémarrage lancé ici — si Jupyter en demande\n"
        "# un malgré tout, voir la note juste en dessous.\n"
        f"{PIPS_PREFIXE}{paquets}\n".replace("!pip", "%pip")
    ).splitlines(keepends=True)
    cells.insert(i_pip + 1, _md(NOTE_PIP))

    # 3) la cellule Drive devient un dossier local ./sortie_voix/
    i_dos = _cel(cells, "from google.colab import drive", "dossier")
    cells[i_dos]["source"] = dossier.splitlines(keepends=True)

    # 4) la cellule Whisper : jeton caché + message GPU Brev
    i_tok = _cel(cells, "from google.colab import userdata", "jeton")
    nouveau = _remplace_token(_source(cells[i_tok]))
    if GPU_ANCIEN not in nouveau:
        raise ValueError("cellule Whisper : assert GPU T4 introuvable")
    nouveau = nouveau.replace(GPU_ANCIEN, GPU_NOUVEAU)
    cells[i_tok]["source"] = nouveau.splitlines(keepends=True)

    # 5) la cellule finale : zip local, pas de files.download
    i_fin = _cel(cells, "files.download(", "cellule finale")
    cells[i_fin]["source"] = fin.splitlines(keepends=True)

    # filet de sécurité : plus aucun mot propre à Colab ne doit rester
    for i, c in enumerate(cells):
        reste = [mot for mot in RESTES_COLAB if mot in _source(c)]
        if reste:
            raise ValueError(f"cellule {i} : restes Colab {reste}")
    return nb


def adapter_test(nb: dict) -> dict:
    """Notebook des 12 variantes de test, en version Brev."""
    return _adapter(nb, INTRO_TEST, DOSSIER_TEST, FIN_TEST)


def adapter_complet(nb: dict) -> dict:
    """Notebook des 869 audios, en version Brev."""
    return _adapter(nb, INTRO_COMPLETE, DOSSIER_COMPLETE, FIN_COMPLETE)


def _ecrire(nb: dict, cible: Path) -> None:
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dossier = Path(args[args.index("--dossier") + 1]) if "--dossier" in args else NOTEBOOKS

    # La version complète est régénérée à partir de la même source que Colab
    # (contruire() du preparer) : une seule définition du plan 869 dans le dépôt.
    sys.path.insert(0, str(RACINE / "scripts"))
    import preparer_notebook_oolel as preparer

    complet = adapter_complet(preparer.construire())
    _ecrire(complet, dossier / "voix_oolel_complete_brev.ipynb")
    print(f"{dossier / 'voix_oolel_complete_brev.ipynb'} : écrit")

    test = adapter_test(json.loads(TEST_COLAB.read_text(encoding="utf-8")))
    _ecrire(test, dossier / "voix_test_prononciation_brev.ipynb")
    print(f"{dossier / 'voix_test_prononciation_brev.ipynb'} : écrit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
