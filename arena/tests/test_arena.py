"""Prueft, dass die Arena richtig mitzaehlt.

Der ganze Wert des Werkzeugs haengt daran, dass seine Zahlen stimmen. Die
Arena liest die Zuege von aussen ab, statt die Bots anzufassen - also muss
belegt werden, dass diese Ableitung aufgeht. Die Buchhaltung muss sich
schliessen: jeder Tote hat genau eine Ursache, und jeder verlorene Angriff
ist fuer genau einen anderen eine erfolgreiche Verteidigung.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from arena.freundschaftsarena import (WAENDE, baue_fueller, lade_bots,  # noqa: E402
                                      spiele, turnier)


def _feld(n: int = 5):
    return [(baue_fueller((i + 1) / (n + 1), 100 + i), f"F{i}")
            for i in range(n)]


class TestBuchhaltung(unittest.TestCase):
    def test_jeder_tote_hat_genau_eine_ursache(self):
        for saat in range(1, 9):
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400)
            tote = sum(1 for p in protokolle.values() if not p.lebt)
            selbst = sum(p.kaempfe_verloren for p in protokolle.values())
            gefressen = sum(len(p.getoetet) for p in protokolle.values())
            self.assertEqual(tote, selbst + gefressen,
                             f"Saat {saat}: {tote} tot, aber "
                             f"{selbst} verlorene Angriffe + "
                             f"{gefressen} Opfer")

    def test_jeder_verlorene_angriff_ist_eine_verteidigung(self):
        for saat in range(1, 9):
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400)
            self.assertEqual(
                sum(p.kaempfe_verloren for p in protokolle.values()),
                sum(p.verteidigt for p in protokolle.values()))

    def test_jeder_tote_kennt_seinen_bezwinger(self):
        for saat in range(1, 9):
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400)
            for p in protokolle.values():
                if not p.lebt:
                    self.assertIsNotNone(p.gestorben_gegen, f"{p.name}")
                    self.assertIn(p.gestorben_gegen, protokolle)
                    self.assertNotEqual(p.gestorben_gegen, p.name)

    def test_zuege_gehen_auf(self):
        """Jeder Zug ist gezogen, gedreht, wirkungslos oder toedlich."""
        for saat in range(1, 6):
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400)
            for p in protokolle.values():
                self.assertEqual(
                    p.zuege,
                    p.gezogen + p.gedreht + p.blockiert + p.kaempfe_verloren,
                    f"{p.name} bei Saat {saat}")

    def test_staerke_kommt_aus_kohl_oder_kaempfen(self):
        """Startstaerke 1, alles darueber ist Kohl, Beute oder Erbe.

        Der dritte Posten ist der, den man vergisst: wer einen Angriff
        ueberlebt, bekommt die volle Staerke des Angreifers - aber in
        dessen Zug. Die erste Fassung der Arena hat ihn nicht verbucht,
        und dieser Test hat es gemerkt.
        """
        for saat in range(1, 6):
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400)
            for p in protokolle.values():
                if p.lebt:
                    self.assertAlmostEqual(
                        p.endstaerke,
                        1 + p.kohl + p.beute + p.verteidigungsbeute,
                        places=6, msg=p.name)


class TestBotsLaden(unittest.TestCase):
    def test_beispielbot_wird_gefunden(self):
        ordner = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "bots")
        namen = [n for n, _ in lade_bots(ordner)]
        self.assertIn("GeraderFresser", namen)

    def test_kaputte_datei_stoppt_das_turnier_nicht(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ordner:
            with open(os.path.join(ordner, "kaputt.py"), "w") as f:
                f.write("das ist kein gueltiges Python (((\n")
            with open(os.path.join(ordner, "heil.py"), "w") as f:
                f.write("from Pacman import Pacman\n"
                        "class Heil(Pacman):\n"
                        "    def TurnOrMoveOrStill(self):\n"
                        "        self._Move()\n")
            namen = [n for n, _ in lade_bots(ordner)]
            self.assertEqual(namen, ["Heil"])

    def test_ein_bot_der_wirft_toetet_die_arena_nicht(self):
        from Pacman import Pacman as Basis

        class Explodiert(Basis):
            def TurnOrMoveOrStill(self):
                raise RuntimeError("absichtlich")

        aufstellung = [(Explodiert, "Bombe")] + _feld(3)
        bilanzen, _ = turnier(aufstellung, partien=2, saat=1, groesse=15,
                              waende=WAENDE, grenze=200)
        self.assertGreater(bilanzen["Bombe"].fehler, 0)
        self.assertEqual(bilanzen["F0"].fehler, 0)


if __name__ == "__main__":
    unittest.main()


class TestProtokoll(unittest.TestCase):
    """Das Protokoll ist nur so viel wert wie seine Kampfrechnung."""

    def test_verteidigungsfaktor_stimmt_mit_der_engine_ueberein(self):
        """Nicht gegen eine Abschrift pruefen, sondern gegen Pacman.py.

        Die Engine rechnet den Faktor aus der *Summe* der beiden
        Richtungsvektoren aus. Wer das von Hand nachbaut, dreht leicht ein
        Vorzeichen um - und dann steht im Bericht bei jedem Todesfall die
        falsche Wahrscheinlichkeit.
        """
        from Pacman import Direction
        from arena.protokoll import verteidigungsfaktor

        richtungen = {"N": Direction.north, "S": Direction.south,
                      "W": Direction.west, "O": Direction.east}
        for a_name, a in richtungen.items():
            for v_name, v in richtungen.items():
                z = a + v
                if z._x == 0 and z._y == 0:
                    erwartet = 1.0
                elif abs(z._x) == 1 and abs(z._y) == 1:
                    erwartet = 1 / 5.0
                else:
                    erwartet = 1 / 10.0
                self.assertAlmostEqual(
                    verteidigungsfaktor(a_name, v_name), erwartet, places=9,
                    msg=f"Angreifer {a_name} gegen Verteidiger {v_name}")

    def test_von_hinten_ist_besser_als_von_vorn(self):
        from arena.protokoll import siegchance
        vorn = siegchance(10, 10, "N", "S")
        seite = siegchance(10, 10, "N", "W")
        hinten = siegchance(10, 10, "N", "N")
        self.assertAlmostEqual(vorn, 0.5, places=6)
        self.assertLess(vorn, seite)
        self.assertLess(seite, hinten)
        self.assertGreater(hinten, 0.9)

    def test_jeder_tote_taucht_im_protokoll_auf(self):
        """Die meisten Bots sterben nicht am eigenen Angriff, sondern
        werden im Zug eines anderen gefressen. Die erste Fassung hat nur
        den ersten Fall markiert - im Bericht fehlten dadurch die
        haeufigsten Todesfaelle vollstaendig."""
        from arena.freundschaftsarena import spiele
        from arena.protokoll import Mitschrift

        for saat in range(1, 7):
            mit = Mitschrift()
            protokolle, _ = spiele(_feld(), saat=saat, grenze=400,
                                   mitschrift=mit)
            tote = {p.name for p in protokolle.values() if not p.lebt}
            markiert = {z["bot"] for z in mit.zeilen if "tod" in z}
            self.assertEqual(tote, markiert, f"Saat {saat}")

    def test_bericht_nennt_jeden_todesfall(self):
        import tempfile
        from arena.freundschaftsarena import spiele
        from arena.protokoll import Mitschrift

        mit = Mitschrift()
        protokolle, _ = spiele(_feld(), saat=4, grenze=400, mitschrift=mit)
        with tempfile.NamedTemporaryFile("r+", suffix=".md") as datei:
            mit.bericht(datei.name)
            text = open(datei.name).read()
        for p in protokolle.values():
            if not p.lebt:
                self.assertIn(p.name, text)
                self.assertIn(f"Tot in Zug {p.gestorben_in_zug}", text)


class TestGrafisch(unittest.TestCase):
    """Die Fensteransicht ohne Fenster pruefen.

    pygame ist auf Testrechnern selten installiert, und ein Pfad, den
    niemand ausfuehrt, ist ein Pfad, der irgendwann kaputt ist. Der Stub
    ersetzt nur pygame und den Renderer - geprueft wird die Schleife
    selbst: Ereignisse, Pause, Zugreihenfolge und Buchhaltung.
    """

    def _stub(self, bilder_bis_ende=200):
        import types
        stand = {"n": 0, "gezeichnet": 0}

        def get():
            stand["n"] += 1
            if stand["n"] == 5:      # Leertaste: Pause an
                return [types.SimpleNamespace(type=2, key=32)]
            if stand["n"] == 8:      # Leertaste: Pause aus
                return [types.SimpleNamespace(type=2, key=32)]
            if stand["n"] > bilder_bis_ende:
                return [types.SimpleNamespace(type=1)]
            return []

        pg = types.ModuleType("pygame")
        pg.init = lambda: None
        pg.quit = lambda: None
        pg.event = types.SimpleNamespace(get=get)
        pg.time = types.SimpleNamespace(
            Clock=lambda: types.SimpleNamespace(tick=lambda f: None))
        pg.display = types.SimpleNamespace(set_caption=lambda t: None)
        pg.QUIT, pg.KEYDOWN, pg.K_ESCAPE, pg.K_SPACE = 1, 2, 27, 32
        pg.K_PLUS, pg.K_EQUALS, pg.K_MINUS = 43, 61, 45

        rend = types.ModuleType("PacmanRenderer")

        class _R:
            def __init__(self, field):
                self.field = field

            def draw_field(self):
                stand["gezeichnet"] += 1

        rend.Renderer = _R
        return pg, rend, stand

    def test_fensterlauf_zaehlt_richtig(self):
        import sys
        from arena.freundschaftsarena import WAENDE, zeige_partie

        pg, rend, stand = self._stub()
        alt = (sys.modules.get("pygame"), sys.modules.get("PacmanRenderer"))
        sys.modules["pygame"], sys.modules["PacmanRenderer"] = pg, rend
        try:
            protokolle = zeige_partie(_feld(), saat=3, groesse=15,
                                      waende=WAENDE, grenze=1500, fps=12)
        finally:
            for name, modul in zip(("pygame", "PacmanRenderer"), alt):
                if modul is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = modul

        self.assertIsNotNone(protokolle)
        self.assertGreater(stand["gezeichnet"], 0)
        for p in protokolle.values():
            self.assertEqual(p.fehler, 0, p.name)
            self.assertEqual(
                p.zuege,
                p.gezogen + p.gedreht + p.blockiert + p.kaempfe_verloren,
                f"{p.name}: die Buchhaltung des Fensterlaufs geht nicht auf")

    def test_ohne_pygame_kommt_eine_hilfreiche_meldung(self):
        import builtins
        import sys
        from arena.freundschaftsarena import WAENDE, zeige_partie

        echter_import = builtins.__import__

        def blockiert(name, *rest, **kw):
            if name == "pygame":
                raise ImportError("No module named 'pygame'")
            return echter_import(name, *rest, **kw)

        gemerkt = sys.modules.pop("pygame", None)
        builtins.__import__ = blockiert
        try:
            ergebnis = zeige_partie(_feld(), saat=1, groesse=15,
                                    waende=WAENDE, grenze=50, fps=12)
        finally:
            builtins.__import__ = echter_import
            if gemerkt is not None:
                sys.modules["pygame"] = gemerkt
        self.assertIsNone(ergebnis,
                          "ohne pygame darf nichts zurueckkommen, aber auch "
                          "nichts fliegen - der Nutzer braucht einen Rat")
