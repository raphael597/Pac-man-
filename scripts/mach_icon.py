"""Erzeugt ein Bot-Bild fuer den PacmanRenderer.

    python scripts/mach_icon.py icons/ClaudeEndboss.png

Drei Dinge gibt der Renderer vor, und alle drei haben wir aus
``PacmanRenderer.py`` abgelesen statt geraten:

**Osten ist die Grundstellung.** ``DIRECTION_ANGLES`` bildet Osten auf 0
Grad ab, alle anderen Richtungen werden daraus gedreht. Ein Bild, das nach
oben schaut, laeuft im Spiel also seitwaerts.

**Es wird starr gedreht, nicht gespiegelt.** Bei Westen steht das ganze
Bild auf dem Kopf. Alles, was ein Oben und Unten hat - eine Krone, ein
einzelnes Auge - sieht dann falsch aus. Deshalb ist diese Figur zur
Waagerechten symmetrisch: nur das Maul zeigt die Richtung an, und das
bleibt in jeder Drehung richtig.

**32 Pixel sind die Endgroesse.** ``smoothscale`` rechnet jedes Bild auf
CELL_SIZE herunter. Feine Linien verschwinden dort; was zaehlt, ist die
Silhouette. Gezeichnet wird deshalb gross und dann verkleinert, damit die
Kanten sauber werden.

Faellt das Laden fehl, liefert ``_load_icon`` still ``None`` und der
Renderer malt den farbigen Kreis - ein falscher Pfad faellt also nicht als
Fehler auf, sondern nur daran, dass kein Bild erscheint.
"""
from __future__ import annotations

import math
import sys

from PIL import Image, ImageDraw

#: Gross zeichnen, klein ausgeben - das ist die ganze Kantenglaettung.
GROSS = 512
#: Dieselbe Kantenlaenge wie die mitgelieferten Bilder des Lehrers.
AUSGABE = 40

KOERPER = (107, 63, 160, 255)      # Violett - Gelbgruen, Rot und Gruen sind
RAND = (58, 30, 96, 255)           # von den anderen Figuren schon belegt
GLANZ = (150, 108, 205, 255)
AUGE = (255, 233, 130, 255)
PUPILLE = (30, 12, 56, 255)

#: Halber Oeffnungswinkel des Mauls, in Grad.
MAUL = 26


def zeichne(groesse: int = GROSS) -> Image.Image:
    bild = Image.new("RGBA", (groesse, groesse), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)
    mitte = groesse / 2
    radius = groesse * 0.42

    # --- Stacheln, rundherum gleichmaessig ---------------------------
    # Gleichmaessig, damit die Figur in jeder Drehung gleich aussieht.
    zacken = 12
    for i in range(zacken):
        a = 2 * math.pi * i / zacken
        # Die beiden Stacheln, die ins Maul fallen wuerden, auslassen.
        grad = (math.degrees(a) + 360) % 360
        if grad < MAUL + 6 or grad > 360 - MAUL - 6:
            continue
        spitze = radius * 1.22
        breite = 2 * math.pi / zacken * 0.34
        stift.polygon(
            [(mitte + spitze * math.cos(a), mitte + spitze * math.sin(a)),
             (mitte + radius * math.cos(a - breite),
              mitte + radius * math.sin(a - breite)),
             (mitte + radius * math.cos(a + breite),
              mitte + radius * math.sin(a + breite))],
            fill=RAND)

    # --- Koerper mit Maul nach Osten ---------------------------------
    kasten = [mitte - radius, mitte - radius, mitte + radius, mitte + radius]
    stift.pieslice(kasten, MAUL, 360 - MAUL, fill=KOERPER, outline=RAND,
                   width=int(groesse * 0.035))
    # Ein Lichtrand oben links, damit die Silhouette nicht flach wirkt.
    stift.arc([kasten[0] + groesse * 0.06, kasten[1] + groesse * 0.06,
               kasten[2] - groesse * 0.06, kasten[3] - groesse * 0.06],
              MAUL + 100, 300, fill=GLANZ, width=int(groesse * 0.03))

    # --- Zwei Augen, gespiegelt zur Waagerechten ----------------------
    # Ein einzelnes Auge saehe bei Westen (180 Grad) auf dem Kopf aus.
    for vorzeichen in (-1, 1):
        ax = mitte - radius * 0.18
        ay = mitte + vorzeichen * radius * 0.42
        r = radius * 0.17
        stift.ellipse([ax - r, ay - r, ax + r, ay + r], fill=AUGE)
        pr = r * 0.52
        stift.ellipse([ax + r * 0.25 - pr, ay - pr,
                       ax + r * 0.25 + pr, ay + pr], fill=PUPILLE)
    return bild


def main() -> int:
    ziel = sys.argv[1] if len(sys.argv) > 1 else "icons/ClaudeEndboss.png"
    gross = zeichne()
    klein = gross.resize((AUSGABE, AUSGABE), Image.LANCZOS)
    klein.save(ziel)
    print(f"{ziel}: {klein.size[0]}x{klein.size[1]}, "
          f"{len(open(ziel, 'rb').read())} Bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
