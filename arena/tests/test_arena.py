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
