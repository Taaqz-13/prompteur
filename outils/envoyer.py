"""Envoie un texte dans la boîte de réception du prompteur iPhone.

Le texte est déposé dans un Gist secret (fichier inbox.json, liste de
{id, title, text, updated}) ; l'app le va chercher toute seule à l'ouverture
et avec son bouton « Recevoir ». Même id = mise à jour du texte.

    py envoyer.py script.txt --titre "Façade - hook A"     envoyer / mettre à jour
    py envoyer.py - --titre "..." --id pc-essai             lire le texte sur l'entrée standard
    py envoyer.py --liste                                    voir ce qui est dans la boîte
    py envoyer.py --retirer pc-essai                         retirer un texte de la boîte
    py envoyer.py --init --compte Taaqz-13                   créer la boîte (une seule fois)

L'adresse du Gist vit dans boite.local.json, à côté de ce script, jamais
committé (dépôt public). L'accès en écriture passe par le jeton de `gh`.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

CONFIG = Path(__file__).with_name("boite.local.json")
FICHIER = "inbox.json"
API = "https://api.github.com"


def stop(msg):
    print("ERREUR : " + msg, file=sys.stderr)
    sys.exit(1)


def charger_config():
    if not CONFIG.exists():
        stop(f"boîte pas encore créée ({CONFIG.name} absent). Lance : py envoyer.py --init --compte Taaqz-13")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def jeton(compte):
    r = subprocess.run(["gh", "auth", "token", "--user", compte], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        stop(f"pas de jeton gh pour le compte {compte} : {r.stderr.strip()}")
    return r.stdout.strip()


def appel(methode, chemin, tok, corps=None):
    req = urllib.request.Request(
        API + chemin,
        method=methode,
        data=json.dumps(corps, ensure_ascii=False).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": "Bearer " + tok,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "prompteur-envoyer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        stop(f"GitHub a répondu {e.code} sur {methode} {chemin} : {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        stop(f"GitHub injoignable ({e.reason}). Rien n'a été envoyé.")


def lire_boite(cfg, tok):
    g = appel("GET", "/gists/" + cfg["gist"], tok)
    f = (g.get("files") or {}).get(FICHIER)
    if not f:
        stop(f"{FICHIER} absent du Gist {cfg['gist']}")
    contenu = f.get("content", "")
    if f.get("truncated"):
        req = urllib.request.Request(f["raw_url"], headers={"Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=30) as r:
            contenu = r.read().decode("utf-8")
    return json.loads(contenu or "[]"), g


def ecrire_boite(cfg, tok, items):
    contenu = json.dumps(items, ensure_ascii=False, indent=1)
    return appel("PATCH", "/gists/" + cfg["gist"], tok, {"files": {FICHIER: {"content": contenu}}})


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]


def lire_texte(chemin):
    """UTF-8 strict, rien n'est réécrit : accents, ponctuation, lignes vides, espaces restent tels quels.
    Seuls le BOM éventuel (marque invisible, pas du texte) et les fins de ligne Windows (CRLF,
    ramenées à LF : mêmes sauts de ligne, aux mêmes endroits) sont normalisés."""
    brut = sys.stdin.buffer.read() if chemin == "-" else Path(chemin).read_bytes()
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError as e:
        stop(f"le fichier n'est pas en UTF-8 (octet illisible en position {e.start}). "
             "Réenregistre-le en UTF-8 : sinon les accents arriveraient cassés.")
    if texte.startswith("﻿"):
        texte = texte[1:]
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    if not texte.strip():
        stop("le texte est vide, rien n'a été envoyé.")
    return texte


def date_envoi(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%d/%m/%Y %H:%M") if ms else "?"


def adresse(cfg):
    return f"https://gist.github.com/{cfg['compte']}/{cfg['gist']}"


def cmd_init(compte):
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        stop(f"la boîte existe déjà : {adresse(cfg)} (supprime {CONFIG.name} pour en recréer une)")
    tok = jeton(compte)
    g = appel("POST", "/gists", tok, {
        "description": "Prompteur : boite de reception",
        "public": False,
        "files": {FICHIER: {"content": "[]"}},
    })
    cfg = {"compte": compte, "gist": g["id"]}
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("Boîte créée (Gist secret, non listé).")
    print("Adresse à coller une fois dans l'app (bibliothèque, en bas : « Réception PC ») :")
    print("  " + adresse(cfg))


def cmd_liste():
    cfg = charger_config()
    items, _ = lire_boite(cfg, jeton(cfg["compte"]))
    print(f"Boîte : {adresse(cfg)}")
    if not items:
        print("  (vide)")
    for it in items:
        mots = len(it.get("text", "").split())
        print(f"  {it['id']:<32} {date_envoi(it.get('updated')):<17} {mots:>5} mots  {it.get('title', '')}")


def cmd_retirer(ident):
    cfg = charger_config()
    tok = jeton(cfg["compte"])
    items, _ = lire_boite(cfg, tok)
    reste = [it for it in items if it.get("id") != ident]
    if len(reste) == len(items):
        stop(f"aucun texte d'id {ident} dans la boîte (voir --liste).")
    ecrire_boite(cfg, tok, reste)
    print(f"Retiré de la boîte : {ident}. Le texte reste sur l'iPhone s'il y était déjà arrivé.")


def cmd_envoyer(chemin, titre, ident, forcer):
    cfg = charger_config()
    texte = lire_texte(chemin)
    if chemin != "-" and not titre:
        titre = Path(chemin).stem.replace("-", " ").replace("_", " ").strip()
    if not titre:
        stop("donne un titre avec --titre.")
    if not ident:
        base = slug(Path(chemin).stem) if chemin != "-" else slug(titre)
        if not base:
            stop("impossible de déduire un id, donne-le avec --id.")
        ident = "pc-" + base
    tok = jeton(cfg["compte"])
    items, _ = lire_boite(cfg, tok)
    ancien = next((it for it in items if it.get("id") == ident), None)
    if ancien and ancien.get("text") == texte and ancien.get("title") == titre and not forcer:
        print(f"Déjà dans la boîte à l'identique (envoyé le {date_envoi(ancien.get('updated'))}) : rien envoyé.")
        print("Pour le renvoyer quand même (texte supprimé sur l'iPhone) : ajoute --forcer.")
        return
    entree = {"id": ident, "title": titre, "text": texte, "updated": int(time.time() * 1000)}
    if ancien:
        items[items.index(ancien)] = entree
    else:
        items.append(entree)
    ecrire_boite(cfg, tok, items)

    # Relecture : on ne dit « envoyé » que si le Gist rend exactement le texte parti.
    relu, _ = lire_boite(cfg, tok)
    verif = next((it for it in relu if it.get("id") == ident), None)
    if not verif or verif.get("text") != texte or verif.get("title") != titre:
        stop("le Gist ne rend pas le texte envoyé à l'identique. Relance la commande.")

    lignes = texte.split("\n")
    debut = next((l.strip() for l in lignes if l.strip()), "")
    print("Envoyé dans la boîte du prompteur :")
    print(f"  Titre   : {titre}")
    print(f"  Id      : {ident}")
    print(f"  Statut  : {'mis à jour (remplace la version du ' + date_envoi(ancien.get('updated')) + ')' if ancien else 'nouveau texte'}")
    print(f"  Texte   : {len(texte)} caractères, {len(texte.split())} mots, {len(lignes)} lignes")
    print(f"  Début   : « {debut[:90]}{'…' if len(debut) > 90 else ''} »")
    print("  Vérifié : relu dans la boîte, identique caractère pour caractère")
    print("Sur l'iPhone : ouvre le prompteur (ou touche Recevoir dans la bibliothèque).")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Envoie un texte dans la boîte de réception du prompteur iPhone.")
    p.add_argument("fichier", nargs="?", help="fichier texte UTF-8, ou - pour l'entrée standard")
    p.add_argument("--titre", help="titre affiché dans l'app (défaut : nom du fichier)")
    p.add_argument("--id", help="identifiant stable ; même id = mise à jour (défaut : pc-<nom du fichier>)")
    p.add_argument("--forcer", action="store_true", help="renvoyer même si le texte est identique")
    p.add_argument("--liste", action="store_true", help="lister les textes de la boîte")
    p.add_argument("--retirer", metavar="ID", help="retirer un texte de la boîte")
    p.add_argument("--init", action="store_true", help="créer la boîte (Gist secret)")
    p.add_argument("--compte", default="Taaqz-13", help="compte GitHub qui porte la boîte (avec --init)")
    a = p.parse_args()
    if a.init:
        cmd_init(a.compte)
    elif a.liste:
        cmd_liste()
    elif a.retirer:
        cmd_retirer(a.retirer)
    elif a.fichier:
        cmd_envoyer(a.fichier, a.titre, a.id, a.forcer)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
