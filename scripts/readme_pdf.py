"""README.md als gesetztes PDF.

    python scripts/readme_pdf.py arena/README.md dist/PacmanArena/README.pdf

Der Weg fuehrt ueber HTML und Chromium statt ueber reportlab: Das README
lebt als Markdown weiter, und ein zweites Dokument, das man von Hand
nachpflegen muss, waere nach der ersten Aenderung veraltet. So ist das PDF
immer nur ein Aufruf entfernt.

Fuer den Druck zaehlen andere Dinge als fuer den Bildschirm, und genau die
stehen unten im CSS: Umbrueche duerfen nicht mitten in einen Codeblock oder
eine Tabelle fallen, eine Ueberschrift darf nicht allein am Seitenende
stehen, und die Schriften muessen im Container vorhanden sein - deshalb
DejaVu und Liberation statt einer Google-Schrift, die beim Rendern still
auf etwas anderes zurueckfaellt.
"""
from __future__ import annotations

import os
import re
import sys

import markdown

CSS = """
@page {
  size: A4;
  margin: 19mm 17mm 20mm 17mm;
}
:root {
  --ink: #1a1c18;
  --ink-2: #4a4f45;
  --muted: #767c6f;
  --line: #d8ddd0;
  --sunk: #f2f4ec;
  --akzent: #4a7c2f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  font: 10.5pt/1.5 "Liberation Serif", "DejaVu Serif", Georgia, serif;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
h1, h2, h3 {
  font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
  color: var(--ink);
  break-after: avoid;
  page-break-after: avoid;
}
h1 {
  font-size: 25pt; line-height: 1.1; letter-spacing: -.01em;
  margin: 0 0 2mm;
}
h2 {
  font-size: 14pt; margin: 9mm 0 2.5mm; padding-bottom: 1.5mm;
  border-bottom: .5pt solid var(--line);
  break-before: auto;
}
h3 {
  font-size: 11.5pt; margin: 6mm 0 1.5mm; color: var(--ink-2);
}
p, ul, ol { margin: 0 0 3mm; }
li { margin-bottom: 1mm; }
strong { font-weight: 700; }

/* Fliesstext schmal halten - im Druck liest sich alles ueber 90 Zeichen
   schlecht, und A4 ist breit. */
p, ul, ol, blockquote { max-width: 165mm; }

code, kbd {
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 9pt;
  background: var(--sunk);
  padding: .4mm 1.2mm;
  border-radius: 1mm;
}
pre {
  background: var(--sunk);
  border: .5pt solid var(--line);
  border-left: 2pt solid var(--akzent);
  border-radius: 1mm;
  padding: 2.5mm 3mm;
  margin: 0 0 3.5mm;
  overflow-x: auto;
  break-inside: avoid;
  page-break-inside: avoid;
}
pre code {
  background: none; padding: 0; font-size: 8.8pt; line-height: 1.45;
  white-space: pre-wrap; word-break: break-word;
}

table {
  border-collapse: collapse;
  width: 100%;
  margin: 0 0 4mm;
  font-size: 9.5pt;
  break-inside: avoid;
  page-break-inside: avoid;
}
th, td {
  border-bottom: .5pt solid var(--line);
  padding: 1.6mm 2mm;
  text-align: left;
  vertical-align: top;
}
th {
  font-family: "Liberation Sans", sans-serif;
  font-size: 8pt; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); border-bottom: .8pt solid var(--ink-2);
}
tbody tr:nth-child(even) { background: #fafbf6; }

blockquote {
  margin: 0 0 3.5mm;
  padding: 2mm 3mm;
  background: #fbf9ec;
  border-left: 2pt solid #c9a227;
  break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }

hr {
  border: 0; border-top: .5pt solid var(--line); margin: 6mm 0;
}

/* Der Kopf der ersten Seite */
.titelkopf {
  border-bottom: 1.2pt solid var(--ink);
  padding-bottom: 3mm; margin-bottom: 5mm;
}
.titelkopf .marke {
  font-family: "Liberation Sans", sans-serif;
  font-size: 7.5pt; letter-spacing: .16em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 1.5mm;
}
.titelkopf p { margin: 2mm 0 0; color: var(--ink-2); font-size: 10.5pt; }

/* Inhaltsverzeichnis */
.inhalt {
  break-after: page; page-break-after: always;
  margin-top: 4mm;
}
.inhalt h2 { margin-top: 0; }
.inhalt ol { list-style: none; padding: 0; counter-reset: eintrag; }
.inhalt li {
  font-family: "Liberation Sans", sans-serif;
  font-size: 10pt; padding: 1.4mm 0;
  border-bottom: .4pt dotted var(--line);
}
.inhalt li::before {
  counter-increment: eintrag; content: counter(eintrag) ".";
  color: var(--muted); display: inline-block; width: 8mm;
}
"""

KOPF_UND_FUSS = {
    "kopf": """
      <div style="font-family:Liberation Sans,sans-serif;font-size:7pt;
                  color:#767c6f;width:100%;padding:0 17mm;
                  display:flex;justify-content:space-between;">
        <span>{titel}</span><span></span>
      </div>""",
    # Links stand hier zuerst der Untertitel, abgeschnitten auf 70 Zeichen -
    # das sah auf jeder Seite nach einem Fehler aus. Eine Fusszeile darf
    # leer sein; sie darf nur nicht kaputt aussehen.
    "fuss": """
      <div style="font-family:Liberation Sans,sans-serif;font-size:7.5pt;
                  color:#767c6f;width:100%;padding:0 17mm;
                  display:flex;justify-content:flex-end;">
        <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
      </div>""",
}


def nach_html(md_text: str) -> tuple:
    """Markdown zu HTML, plus Titel, Untertitel und Kapitelliste."""
    zeilen = md_text.split("\n")
    titel = "Dokument"
    untertitel = ""
    for i, z in enumerate(zeilen):
        if z.startswith("# "):
            titel = z[2:].strip()
            # Den *ganzen* ersten Absatz nehmen, nicht die ersten zwei
            # Zeilen: Markdown bricht Absaetze mitten im Satz um, und ein
            # abgeschnittener Untertitel sieht nach Fehler aus.
            absatz = []
            for x in zeilen[i + 1:]:
                if not x.strip():
                    if absatz:
                        break
                    continue
                if x.startswith(("#", "-", ">")):
                    break
                absatz.append(x.strip())
            # Durch Markdown schicken, sonst steht **warum** woertlich im
            # Untertitel - der Kopf ist HTML, kein Markdown.
            untertitel = markdown.markdown(" ".join(absatz))
            untertitel = re.sub(r"^<p>|</p>$", "", untertitel).strip()
            # Titel und Vorspann aus dem Fliesstext nehmen, sie kommen in
            # den eigenen Kopf.
            ende = i + 1
            while ende < len(zeilen) and not zeilen[ende].startswith("---"):
                ende += 1
            zeilen = zeilen[ende + 1:]
            break
    kapitel = [z[3:].strip() for z in zeilen if z.startswith("## ")]

    koerper = markdown.markdown(
        "\n".join(zeilen),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    return titel, untertitel, kapitel, koerper


def baue_html(pfad: str) -> tuple:
    with open(pfad, encoding="utf-8") as datei:
        titel, untertitel, kapitel, koerper = nach_html(datei.read())

    inhalt = "".join(f"<li>{k}</li>" for k in kapitel)
    html = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>{titel}</title><style>{CSS}</style></head><body>
<div class="titelkopf">
  <div class="marke">Anleitung</div>
  <h1>{titel}</h1>
  <p>{untertitel}</p>
</div>
<nav class="inhalt"><h2>Inhalt</h2><ol>{inhalt}</ol></nav>
{koerper}
</body></html>"""
    return titel, untertitel, html


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "arena/README.md"
    ziel = sys.argv[2] if len(sys.argv) > 2 else "dist/PacmanArena/README.pdf"

    titel, untertitel, html = baue_html(quelle)
    zwischen = os.path.splitext(ziel)[0] + "_zwischenschritt.html"
    with open(zwischen, "w", encoding="utf-8") as datei:
        datei.write(html)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        seite = browser.new_page()
        seite.goto("file://" + os.path.abspath(zwischen))
        seite.wait_for_timeout(600)
        seite.pdf(
            path=ziel, format="A4", print_background=True,
            display_header_footer=True,
            header_template=KOPF_UND_FUSS["kopf"].replace("{titel}", titel),
            footer_template=KOPF_UND_FUSS["fuss"],
            margin={"top": "19mm", "bottom": "20mm",
                    "left": "17mm", "right": "17mm"})
        browser.close()
    os.remove(zwischen)
    print(f"{ziel}: {os.path.getsize(ziel) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
