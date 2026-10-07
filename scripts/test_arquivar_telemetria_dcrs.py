#!/usr/bin/env python3
"""Testes do arquivador de telemetria DCRS (sem rede)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arquivar_telemetria_dcrs as A

XML = """<root><DadosHidrometereologicos diffgr:id="1">
<DataHora>2026-09-30 23:55:00</DataHora><Nivel>120</Nivel><Chuva>0.2</Chuva></DadosHidrometereologicos>
<DadosHidrometereologicos diffgr:id="2"><DataHora>2026-10-01 00:05:00</DataHora><Nivel></Nivel><Chuva>0.4</Chuva></DadosHidrometereologicos>
</root>"""


class ArquivoDcrsTests(unittest.TestCase):
    def test_parse_and_split_by_month(self):
        r = A.parse(XML)
        self.assertEqual(r["2026-09-30 23:55:00"], ("120", "0.2"))
        self.assertEqual(r["2026-10-01 00:05:00"], ("", "0.4"))
        with tempfile.TemporaryDirectory() as d:
            n = A.mesclar("86329001", r, Path(d))
            self.assertEqual(n, 2)
            self.assertTrue((Path(d) / "2026-09" / "86329001.csv").exists())
            self.assertTrue((Path(d) / "2026-10" / "86329001.csv").exists())

    def test_merge_never_overwrites_and_fills_blanks(self):
        with tempfile.TemporaryDirectory() as d:
            A.mesclar("X", {"2026-10-01 00:05:00": ("", "0.4")}, Path(d))
            n = A.mesclar("X", {"2026-10-01 00:05:00": ("130", "9.9"), "2026-10-01 00:20:00": ("131", "0")}, Path(d))
            self.assertEqual(n, 1)                      # só a linha nova conta
            linhas = (Path(d) / "2026-10" / "X.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(linhas[1], "2026-10-01 00:05:00;130;0.4")   # completou o nível, manteve a chuva já gravada
            self.assertEqual(linhas[2], "2026-10-01 00:20:00;131;0")


if __name__ == "__main__":
    unittest.main()
