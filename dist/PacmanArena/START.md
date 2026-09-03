# Freundschaftsarena — starten

Entpacken, in den Ordner wechseln, loslegen:

```bash
cd PacmanArena
python arena/freundschaftsarena.py --partien 20 --fueller 3
```

Mehr braucht es nicht — kein `pip install`, keine Einrichtung, Python 3.8+.

## Eigene Bots

Legt eure `.py`-Dateien in **`arena/bots/`**. Jede Klasse darin, die von
`Pacman` erbt, tritt automatisch an. Zwei liegen schon drin:

* `beispiel_gerader_fresser.py` — die Kopiervorlage
* `ClaudeEndboss.py` — der Bot aus dem anderen ZIP, als Maßstab

## Die vier Befehle, die ihr wirklich braucht

```bash
# Turnier auf Turniergröße (15 Spieler)
python arena/freundschaftsarena.py --partien 200 --fueller 14

# Eine Partie zum Anschauen, als HTML-Datei
python arena/freundschaftsarena.py --partien 1 --replay partie.html

# Bericht für die Fehlersuche — klein genug für eine KI-Anfrage
python arena/freundschaftsarena.py --partien 1 --warum bericht.md

# Prüfen, dass die Arena richtig mitzählt
python -m unittest arena.tests.test_arena
```

Alles Weitere steht in `arena/ANLEITUNG.md`.
