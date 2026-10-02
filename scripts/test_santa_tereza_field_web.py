"""Real JavaScript regression checks and field-raster sync, without browser mocks.

Node executes the functions extracted from the actual published HTML. Layer
stubs record the exact geometry passed to Leaflet, not a substitute selector.
This checks software contracts, not inundation or route safety in the field.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "santa_tereza_lidar_campo_rio_principal_zero160_v1"
PAGES = ("santa_tereza_previsao_inundacao.html", "santa_tereza_inundacao.html")


def function_code(text: str, name: str) -> str:
    ending = r"[\s\S]*?contornos=null;\}\);}" if name == "loadContornos" else r"[^\n]*?\{[\s\S]*?^\}"
    match = re.search(r"^function " + name + r"\(" + ending, text, re.M)
    if not match:
        raise AssertionError(f"real function not found: {name}")
    return match.group(0)


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.current = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            values = dict(attrs)
            self.active = not values.get("src") and values.get("type", "") != "application/json"
            self.current = []

    def handle_data(self, data):
        if self.active:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.blocks.append("".join(self.current))
            self.active = False


class FieldWebTests(unittest.TestCase):
    def node(self, code):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the real JS checks")
        result = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_actual_html_functions_use_upper_level_without_clamp_and_keep_all_rings(self):
        for page in PAGES:
            with self.subTest(page=page):
                text = (ROOT / page).read_text(encoding="utf-8")
                functions = function_code(text, "achaFeature") + "\n" + function_code(text, "setLayer")
                if page == PAGES[1]:
                    functions += "\n" + function_code(text, "maxNivelContorno")
                code = """
const vm=require('node:vm');
const features=Array.from({length:251},(_,i)=>({type:'Feature',properties:{nivel_m:i/10,area_ha:i},
geometry:{type:'Polygon',coordinates:[[[0,0],[3,0],[3,3],[0,3],[0,0]],[[1,1],[1,2],[2,2],[2,1],[1,1]]]}}));
const context={contornos:{features:features}};
vm.createContext(context);
vm.runInContext(FUNCTIONS,context);
const inputs=[-1,0,0.04,0.1,0.10000000000000002,0.11,24.99,25,25.01];
const selected=inputs.map(n=>{const f=context.achaFeature(n);return f?f.properties.nivel_m:null;});
let received=null;const layer={clearLayers(){received=null;},addData(f){received=f;}};
const area=context.setLayer(layer,0.04);const identity=received===features[1];
const holes=received.geometry.coordinates.length;
const outside=context.setLayer(layer,25.01);const cleared=received===null;
console.log(JSON.stringify({selected,area,identity,holes,outside,cleared}));
""".replace("FUNCTIONS", json.dumps(functions))
                result = self.node(code)
                expected = [None, None if page == PAGES[0] else 0, 0.1, 0.1, 0.1, 0.2, 25, 25, None]
                self.assertEqual(result["selected"], expected)
                self.assertEqual(result["area"], 1)
                self.assertTrue(result["identity"])
                self.assertEqual(result["holes"], 2)
                self.assertIsNone(result["outside"])
                self.assertTrue(result["cleared"])

    def test_actual_loaders_reject_wrong_source_zero_scope_and_incomplete_simulation(self):
        for page in PAGES:
            text = (ROOT / page).read_text(encoding="utf-8")
            functions = function_code(text, "loadContornos")
            metadata = {"cidade": "santa_tereza", "hand_zero_cm": 160, "rio": "somente rio principal"}
            metadata.update({"hand_source": {"source_id": SOURCE_ID}} if page == PAGES[0] else {"source_id": SOURCE_ID})
            document = {"metadata": metadata, "features": [{"properties": {"nivel_m": i / 10}} for i in range(251)]}
            cases = [("valid", document, True)]
            for key, value in (("hand_zero_cm", 400), ("rio", "tributarios")):
                changed = copy.deepcopy(document)
                changed["metadata"][key] = value
                cases.append((key, changed, False))
            changed = copy.deepcopy(document)
            source = changed["metadata"].get("hand_source", changed["metadata"])
            source["source_id"] = "legacy"
            cases.append(("source_id", changed, False))
            if page == PAGES[1]:
                changed = copy.deepcopy(document)
                changed["features"].pop()
                cases.append(("missing_level", changed, False))
            for label, document, accepted in cases:
                with self.subTest(page=page, case=label):
                    code = """
const vm=require('node:vm');const document=DOCUMENT;
const context={HAND:{source_id:SOURCE},CONTORNOS_URL:'fixture',contornos:null,
 console:{info(){},error(){}},fetch:async()=>({ok:true,json:async()=>document})};
vm.createContext(context);vm.runInContext(FUNCTIONS,context);
context.loadContornos().then(()=>console.log(JSON.stringify(context.contornos!==null)));
""".replace("DOCUMENT", json.dumps(document)).replace("SOURCE", json.dumps(SOURCE_ID)).replace("FUNCTIONS", json.dumps(functions))
                    self.assertIs(self.node(code), accepted)

    def test_real_sync_rejects_invalid_raster_before_replacing_target(self):
        with tempfile.TemporaryDirectory(prefix="stz-sync-contract-") as directory:
            root = Path(directory)
            sync = Path("codigo_python/01_previsao_ao_vivo/atualizar_hand_previsao_santa_tereza.py")
            for relative in (sync, Path("scripts/santa_tereza_hand_field_contract.py")):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, root / relative)
            text = (ROOT / PAGES[0]).read_text(encoding="utf-8")
            payload = json.loads(re.search(r'<script id="hand-data" type="application/json">(.*?)</script>', text, re.S).group(1))
            for key, value in (("hand_zero_cm", 400), ("hand_png_sha256", "0" * 64), ("source_id", "legacy")):
                with self.subTest(key=key):
                    changed = copy.deepcopy(payload)
                    changed[key] = value
                    (root / PAGES[0]).write_text('<script id="hand-data" type="application/json">' + json.dumps(changed) + '</script>', encoding="utf-8")
                    target = root / PAGES[1]
                    target.write_text("sentinel: do not replace", encoding="utf-8")
                    result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(root / sync)], capture_output=True, text=True, encoding="utf-8")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_text(encoding="utf-8"), "sentinel: do not replace")

    def test_changed_html_javascript_parses_and_labels_research_coverage(self):
        pages = (*PAGES, "santa_tereza_rota_fuga.html", "santa_tereza_rota_fuga_ruas_cenario.html",
                 "pesquisas/santa-tereza-rota-fuga-ruas-cenario.html", "pesquisas/santa-tereza-rota-fuga-ruas.html")
        node = shutil.which("node")
        self.assertIsNotNone(node)
        for page in pages:
            with self.subTest(page=page):
                text = (ROOT / page).read_text(encoding="utf-8")
                parser = Scripts()
                parser.feed(text)
                for block in parser.blocks:
                    result = subprocess.run([node, "--check"], input=block, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stderr)
                if page in PAGES:
                    self.assertIn("sem cobertura HAND no intervalo", text)
                    self.assertNotIn("MIN_VISUAL_HOLE_M2", text)
                    self.assertIn("Comparação entre proxies HAND", text)


if __name__ == "__main__":
    unittest.main()
