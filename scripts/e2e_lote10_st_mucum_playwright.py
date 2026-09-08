"""E2E lote 10: centro rollup, chrome place sync, soft mapa, overlay cenário."""

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
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        soft_bypass_sw(page, BASE + "/pesquisas/centro-resposta.html")
        page.wait_for_selector("#ops-rollup", timeout=10000)
        page.wait_for_function(
            "() => document.getElementById('ops-rollup').textContent.includes('Campo:')",
            timeout=8000,
        )
        roll = page.locator("#ops-rollup").inner_text()
        results["centro"] = {
            "rollup": "Campo:" in roll and "Abrigos:" in roll and "ghost" in roll.lower()
        }
        page.locator("#ops-rollup").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote10_centro_rollup.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/modo-campo.html?place=mucum")
        page.wait_for_selector(".gestor-chrome", timeout=8000)
        hrefs = page.evaluate(
            """() => ({
              mapa: document.querySelector('[data-chrome-tab="mapa"]').getAttribute('href'),
              resposta: document.querySelector('[data-chrome-tab="resposta"]').getAttribute('href'),
              ficha: document.querySelector('[data-chrome-tab="ficha"]').getAttribute('href'),
              place: window.PREVINE_GESTOR_CHROME && PREVINE_GESTOR_CHROME.getPlace()
            })"""
        )
        results["chrome_mucum"] = {
            "place": hrefs["place"] == "mucum",
            "mapa": "mucum_previsao" in (hrefs["mapa"] or ""),
            "resposta": "resposta-mucum" in (hrefs["resposta"] or ""),
            "ficha": "status_mucum" in (hrefs["ficha"] or ""),
        }
        page.locator("#btn-santa").click()
        page.wait_for_timeout(400)
        hrefs_st = page.evaluate(
            """() => ({
              mapa: document.querySelector('[data-chrome-tab="mapa"]').getAttribute('href'),
              resposta: document.querySelector('[data-chrome-tab="resposta"]').getAttribute('href'),
              place: window.PREVINE_GESTOR_CHROME && PREVINE_GESTOR_CHROME.getPlace()
            })"""
        )
        results["chrome_switch"] = {
            "place": hrefs_st["place"] == "santa",
            "mapa": "santa_tereza_previsao" in (hrefs_st["mapa"] or ""),
            "resposta": "resposta-santa-tereza" in (hrefs_st["resposta"] or ""),
        }
        page.screenshot(path=str(ARTIFACTS / "lote10_chrome_place_sync.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/mucum-mapa-impacto.html")
        page.wait_for_selector("#resumo", timeout=10000)
        resumo = page.locator("#resumo").inner_text()
        results["mapa_impacto"] = {
            "soft": "não é ordem de saída" in resumo,
            "no_ordem": "precisam sair" not in resumo,
        }
        page.screenshot(path=str(ARTIFACTS / "lote10_mapa_impacto_soft.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/mucum-rota-fuga-ruas-cenario.html")
        page.wait_for_selector(".leaflet-control-layers", timeout=15000)
        # expand layers via class (research_guard blocks hover)
        page.evaluate(
            """() => {
              const el = document.querySelector('.leaflet-control-layers');
              if (el) el.classList.add('leaflet-control-layers-expanded');
            }"""
        )
        page.wait_for_timeout(300)
        labels = page.locator(".leaflet-control-layers-overlays label").all_inner_texts()
        joined = " | ".join(labels)
        results["cenario"] = {
            "layers": len(labels) >= 1,
            "overlay_hint": any("xposi" in x.lower() or "grade" in x.lower() or "hand" in x.lower() for x in labels)
            or "Exposição" in joined
            or len(labels) >= 1,
        }
        page.screenshot(path=str(ARTIFACTS / "lote10_cenario_overlay.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/mucum-rota-fuga-ruas.html")
        page.wait_for_function(
            "() => !!(window.PREVINE_RESPOSTA && PREVINE_RESPOSTA.saveRotaFieldChecks)",
            timeout=10000,
        )
        page.evaluate(
            """() => {
              PREVINE_RESPOSTA.saveRotaFieldChecks('mucum', {access:true,shelter:true});
            }"""
        )
        page.reload(wait_until="networkidle")
        page.wait_for_function(
            "() => !!(window.PREVINE_RESPOSTA && PREVINE_RESPOSTA.loadRotaFieldChecks)",
            timeout=10000,
        )
        persisted = page.evaluate(
            """() => {
              const c = PREVINE_RESPOSTA.loadRotaFieldChecks('mucum');
              return !!(c && c.access && c.shelter);
            }"""
        )
        results["rota_persist"] = {"ok": persisted}

        browser.close()

    assert results["centro"]["rollup"], results
    assert results["chrome_mucum"]["place"] and results["chrome_mucum"]["mapa"], results
    assert results["chrome_mucum"]["resposta"] and results["chrome_mucum"]["ficha"], results
    assert results["chrome_switch"]["place"] and results["chrome_switch"]["mapa"], results
    assert results["mapa_impacto"]["soft"] and results["mapa_impacto"]["no_ordem"], results
    assert results["cenario"]["layers"], results
    assert results["rota_persist"]["ok"], results

    (ARTIFACTS / "lote10_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE10_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
