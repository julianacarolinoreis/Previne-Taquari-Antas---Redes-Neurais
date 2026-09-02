"""E2E smoke: plantão ST + camada exposição vulnerabilidade (screenshots)."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path("/opt/cursor/artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8765"


def test_mesa_st_plantao(page) -> dict:
    url = f"{BASE}/pesquisas/estudo-caso-resposta-santa-tereza.html"
    page.goto(url, wait_until="networkidle")
    page.locator("#eventBriefTitle").wait_for()
    page.locator('[data-operating-mode="live"]').click()
    page.wait_for_timeout(1500)
    freshness = page.locator("#freshnessStatus").inner_text()
    gate = page.locator("#gateStatus").inner_text()
    v001 = page.locator("#v001Level").inner_text()
    v002 = page.locator("#v002Level").inner_text()
    shot = ARTIFACTS / "mesa_st_plantao_live.png"
    page.screenshot(path=str(shot), full_page=False)
    return {
        "freshness": freshness,
        "gate": gate,
        "v001": v001,
        "v002": v002,
        "screenshot": str(shot),
    }


def test_vulnerabilidade_exposicao(page) -> dict:
    url = f"{BASE}/vulnerabilidade.html?municipio=4317251"
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(3000)
    welcome = page.locator("#welcomeDialog")
    if welcome.is_visible():
        page.locator("#welcomeSkip").click()
        page.wait_for_timeout(500)
    exposicao_btn = page.locator("#exposicao button")
    exposicao_btn.wait_for(state="visible", timeout=15000)
    page.evaluate("document.querySelector('#exposicao button')?.click()")
    page.wait_for_timeout(2500)
    shot = ARTIFACTS / "vulnerabilidade_exposicao_st.png"
    page.locator("#map").screenshot(path=str(shot))
    pressed = exposicao_btn.get_attribute("aria-pressed") == "true"
    leg_visible = page.locator("#exposicaoLeg").is_visible()
    return {"exposicao_active": pressed and leg_visible, "screenshot": str(shot)}


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        results["mesa_st"] = test_mesa_st_plantao(page)
        results["vulnerabilidade"] = test_vulnerabilidade_exposicao(page)
        results["console_errors"] = errors
        browser.close()

    assert results["mesa_st"]["freshness"] in {"ATENÇÃO", "UNKNOWN", "STALE"}, results
    assert results["vulnerabilidade"]["exposicao_active"] is True, results
    assert not results["console_errors"], results["console_errors"]
    (ARTIFACTS / "e2e_resposta_todos_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("E2E_RESPOSTA_TODOS_OK")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
