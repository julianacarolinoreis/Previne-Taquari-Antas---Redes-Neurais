"""E2E lote 4: roteiro 90 min, exposição v2, benchmark, checklist sync."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("/opt/cursor/artifacts")
BASE = "http://127.0.0.1:8765"


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        page.goto(BASE + "/pesquisas/briefing-gestores.html", wait_until="networkidle")
        page.locator("#roteiro-start").click()
        page.wait_for_timeout(1200)
        clock = page.locator("#roteiro-clock").inner_text()
        results["roteiro90"] = {"clock_running": clock != "00:00", "clock": clock}
        page.screenshot(path=str(ARTIFACTS / "briefing_roteiro_90_running.png"), full_page=False)

        page.goto(BASE + "/pesquisas/exposicao-cruzada.html", wait_until="networkidle")
        page.wait_for_selector("#v1v2-compare tr td", timeout=8000)
        compare = page.locator("#v1v2-compare").inner_text()
        results["exposicao_v2"] = {
            "has_mucum": "Muçum" in compare and "2.070" in compare.replace(",", ".").replace(".", "").replace("2070", "2070") or "2.070" in compare or "2070" in compare,
            "has_st": "Santa Tereza" in compare,
        }
        # normalize check
        text = compare.replace(".", "").replace(",", "")
        results["exposicao_v2"]["pop_v2_mucum"] = "2070" in text
        page.screenshot(path=str(ARTIFACTS / "exposicao_v1_v2_compare.png"), full_page=False)

        page.goto(BASE + "/pesquisas/benchmark-hand-hidrodinamica.html", wait_until="networkidle")
        page.wait_for_selector("#subarea-rows tr td", timeout=8000)
        sub = page.locator("#subarea-rows").inner_text()
        results["benchmark"] = {"subareas": "mucum-centro-baixa" in sub and "st-corredor-etapa2" in sub}
        page.screenshot(path=str(ARTIFACTS / "benchmark_hand_hidrodinamica.png"), full_page=False)

        page.goto(BASE + "/pesquisas/centro-resposta.html", wait_until="networkidle")
        sync_text = page.locator("#check-mesa-sync").inner_text()
        results["centro_sync"] = {"has_mesa_line": "Mesas V002" in sync_text}
        page.screenshot(path=str(ARTIFACTS / "centro_checklist_mesa_sync.png"), full_page=False)

        browser.close()

    assert results["roteiro90"]["clock_running"], results
    assert results["exposicao_v2"]["pop_v2_mucum"], results
    assert results["benchmark"]["subareas"], results
    assert results["centro_sync"]["has_mesa_line"], results

    (ARTIFACTS / "lote4_todos_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE4_TODOS_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
