"""E2E lote 9: abrigo seeds, modo campo place, ST ata unificada."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("/opt/cursor/artifacts")
BASE = "http://127.0.0.1:8765"


def soft_bypass_sw(page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    page.evaluate(
        """async () => {
          if (!navigator.serviceWorker) return;
          const regs = await navigator.serviceWorker.getRegistrations();
          for (const r of regs) await r.unregister();
          const keys = await caches.keys();
          await Promise.all(keys.map((k) => caches.delete(k)));
        }"""
    )
    page.reload(wait_until="networkidle")


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        soft_bypass_sw(page, BASE + "/pesquisas/modo-campo.html?place=mucum")
        page.wait_for_selector('#abrigo-cap-form [name="municipio"]', timeout=10000)
        page.wait_for_function(
            "() => document.querySelector('#abrigo-seed-list option') && document.querySelectorAll('#abrigo-seed-list option').length >= 5",
            timeout=12000,
        )
        mun = page.locator('#abrigo-cap-form [name="municipio"]').input_value()
        n_seeds = page.locator("#abrigo-seed-list option").count()
        results["modo_campo"] = {"municipio": mun, "seeds": n_seeds, "url_place": "place=mucum" in page.url}
        page.locator("#abrigo-capacidade-mount").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote9_modo_campo_abrigo_seeds.png"), full_page=False)

        page.locator("#btn-santa").click()
        page.wait_for_timeout(400)
        mun_st = page.locator('#abrigo-cap-form [name="municipio"]').input_value()
        results["modo_campo"]["switch_st"] = mun_st == "Santa Tereza"
        page.wait_for_function(
            "() => [...document.querySelectorAll('#abrigo-seed-list option')].some(o => o.value.includes('Ginásio'))",
            timeout=5000,
        )
        results["modo_campo"]["ginasio"] = True

        soft_bypass_sw(page, BASE + "/pesquisas/estudo-caso-resposta-santa-tereza.html")
        page.wait_for_selector("#exportUnified", timeout=10000)
        results["st_mesa"] = {"ata": page.locator("#exportUnified").count() == 1}
        page.locator("#exportUnified").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote9_st_ata_unificada.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/briefing-gestores.html")
        page.wait_for_selector("#briefing-resposta-status", timeout=8000)
        status = page.locator("#briefing-resposta-status").inner_text()
        results["briefing"] = {"dual": "Muçum V002" in status and "ST V002" in status}
        page.locator("#briefing-resposta-status").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote9_briefing_dual.png"), full_page=False)

        browser.close()

    assert results["modo_campo"]["municipio"] == "Muçum", results
    assert results["modo_campo"]["seeds"] >= 5, results
    assert results["modo_campo"]["switch_st"], results
    assert results["modo_campo"]["ginasio"], results
    assert results["st_mesa"]["ata"], results
    assert results["briefing"]["dual"], results

    (ARTIFACTS / "lote9_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE9_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
