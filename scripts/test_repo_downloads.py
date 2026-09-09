"""Checks the public workbook download helper and live GitHub Pages mirror."""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
XLSX = (
    "assets/audit_workbooks/"
    "4H_ALT__020_alt_MUC_H04_V30_LJJ_CA_CHUVA_AUDITADO_SEM32_R05_T33_V18-20-21.xlsx"
)
PAGES = (
    "https://julianacarolinoreis.github.io/"
    f"Previne-Taquari-Antas---Redes-Neurais/{XLSX}"
)


class RepoDownloadTests(unittest.TestCase):
    def test_node_download_helper(self) -> None:
        result = subprocess.run(
            ["node", "--test", str(ROOT / "scripts" / "test_repo_downloads.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=result.stdout + "\n" + result.stderr,
        )

    def test_github_pages_serves_the_reported_workbook(self) -> None:
        request = urllib.request.Request(
            PAGES,
            method="GET",
            headers={"User-Agent": "previne-download-test"},
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            body = response.read(8)
            content_type = response.headers.get("Content-Type", "")
            self.assertEqual(response.status, 200)
        self.assertTrue(content_type.startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        self.assertEqual(body[:2], b"PK")

    def test_mucum_panel_keeps_relative_workbook_urls(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        start = html.index('<script id="data-mucum" type="application/json">')
        start = html.index(">", start) + 1
        end = html.index("</script>", start)
        payload = json.loads(html[start:end])
        urls = [model.get("wb_url") or "" for model in payload.get("models", [])]
        self.assertTrue(urls)
        self.assertTrue(any(XLSX in url for url in urls))
        self.assertTrue(all(not url.startswith("https://raw.githubusercontent.com/") for url in urls if url))


if __name__ == "__main__":
    unittest.main()
