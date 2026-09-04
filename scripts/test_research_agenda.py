"""QA estrutural do catálogo e da agenda de avanço do PREVINE.

O teste não avalia desempenho hidrológico nem substitui validação de campo.
Ele impede que a agenda publique referências quebradas, registros incompletos
ou páginas sem o mínimo de estrutura acessível.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
CATALOG = ROOT / "pesquisas.html"
AGENDA_PAGE = ROOT / "pesquisas" / "agenda-avanco.html"
AGENDA_JSON = ROOT / "assets" / "data" / "agenda_pesquisas.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_agenda_schema_and_inline_copy() -> None:
    data = load_json(AGENDA_JSON)
    page = AGENDA_PAGE.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="agenda-data" type="application/json">\s*(.*?)\s*</script>',
        page,
        flags=re.S,
    )
    assert match, "agenda-avanco.html sem snapshot JSON inline"
    inline = json.loads(match.group(1))
    assert inline == data, "snapshot inline diferente do JSON versionado"
    assert data["schema_version"] == 1
    assert len(data["studies"]) == 5
    assert len(data["phases"]) == 3
    assert data["operational_gate"]["status"] == "bloqueado"
    assert {item["id"] for item in data["maturity_legend"]} == {"pesquisa", "prototipo", "validado", "operacao"}
    assert len(data["participants"]) >= 8
    for key in ("responsible", "prior_communication", "scope", "stop_criteria", "observer", "data_protection", "real_world_block"):
        assert data["exercise_protocol"].get(key), f"protocolo sem {key}"

    ids = [item["id"] for item in data["studies"]]
    assert len(ids) == len(set(ids)), "IDs de pesquisa duplicados"
    primary_phases = []
    for item in data["studies"]:
        for key in ("title", "question", "human_impact", "current_evidence", "next_action"):
            assert item.get(key), f"{item['id']} sem {key}"
        assert item["track"] in {"ciencia", "pessoas"}
        assert item["primary_phase"] in {30, 90, 180}
        assert item["primary_phase"] in item["phase"]
        assert item["phase"] != [30, 90, 180] or item["primary_phase"] == 30
        assert item["maturity"] in {"pesquisa", "prototipo"}
        primary_phases.append(item["primary_phase"])
        for key in ("data_needed", "method", "metrics", "gate", "sources"):
            assert item.get(key), f"{item['id']} sem {key}"
    assert set(primary_phases) == {30, 90, 180}, "as três prioridades principais precisam ter pesquisa atribuída"
    assert "prefers-reduced-motion" in page
    assert "syncPhaseState" in page
    assert "aria-pressed" in page
    assert "Participantes necessários" in page
    assert "Protocolo mínimo para um exercício controlado" in page


def test_agenda_sources_exist() -> None:
    data = load_json(AGENDA_JSON)
    for item in data["studies"]:
        for source in item["sources"]:
            href = source["href"]
            if href.startswith(("http://", "https://")):
                continue
            target = (AGENDA_PAGE.parent / href).resolve()
            assert target.is_file(), f"Fonte quebrada em {item['id']}: {href}"


def test_catalog_entries_are_unique_and_local_links_exist() -> None:
    html = CATALOG.read_text(encoding="utf-8")
    entries = re.findall(r'\{title:"([^"]+)"[^{}]*?href:"([^"]+)"', html)
    assert len(entries) == 59, f"catálogo deveria ter 59 entradas, encontrou {len(entries)}"
    titles = [title for title, _ in entries]
    assert len(titles) == len(set(titles)), "títulos duplicados no catálogo"
    for title, href in entries:
        assert (ROOT / href).is_file(), f"Link local quebrado em {title}: {href}"
    catalog_hrefs = {href for _, href in entries if href.startswith("pesquisas/") and href.endswith(".html")}
    research_pages = {path.relative_to(ROOT).as_posix() for path in (ROOT / "pesquisas").glob("*.html")}
    assert research_pages <= catalog_hrefs, "há páginas HTML de pesquisa fora do catálogo"
    assert "pesquisas/agenda-avanco.html" in html
    assert "Produto validado" in html
    assert "Operação real" in html


def test_research_pages_have_minimum_document_metadata() -> None:
    missing: list[str] = []
    paths = [ROOT / "index.html", CATALOG, *sorted((ROOT / "pesquisas").glob("*.html"))]
    for path in paths:
        html = path.read_text(encoding="utf-8")
        checks = {
            "title": bool(re.search(r"<title\b", html, flags=re.I)),
            "h1": bool(re.search(r"<h1\b", html, flags=re.I)),
            "lang": bool(re.search(r"<html[^>]*\blang=", html, flags=re.I)),
            "viewport": bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, flags=re.I)),
        }
        absent = [key for key, ok in checks.items() if not ok]
        if absent:
            missing.append(f"{path.name}: {', '.join(absent)}")
    assert not missing, "Páginas sem metadados mínimos: " + "; ".join(missing)


def _chrome_executable() -> str | None:
    configured = os.environ.get("PREVINE_CHROME_PATH")
    candidates = [Path(configured)] if configured else []
    program_files = os.environ.get("ProgramFiles", r"C:\\Program Files")
    candidates.extend(
        [
            Path(program_files) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def test_rendered_responsive_interactions_and_accessibility() -> None:
    """QA renderizado local: larguras críticas, overflow, teclado, filtros e details."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the QA machine
        raise AssertionError("QA renderizado requer o pacote playwright") from exc

    with sync_playwright() as playwright:
        launch_kwargs = {"headless": True}
        executable = _chrome_executable()
        if executable:
            launch_kwargs["executable_path"] = executable
        try:
            browser = playwright.chromium.launch(**launch_kwargs)
        except Exception as exc:  # pragma: no cover - browser installation is external
            raise AssertionError("QA renderizado requer Chrome/Chromium disponível") from exc

        try:
            for width in (320, 360, 768, 1440):
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(AGENDA_PAGE.as_uri(), wait_until="domcontentloaded")
                page.locator("[data-study]").first.wait_for()
                dimensions = page.locator("body").evaluate(
                    "body => ({bodyWidth: body.scrollWidth, documentWidth: document.documentElement.scrollWidth, viewport: window.innerWidth})"
                )
                assert dimensions["viewport"] == width
                assert max(dimensions["bodyWidth"], dimensions["documentWidth"]) <= width + 1, (
                    f"overflow horizontal em {width}px: {dimensions}"
                )
                assert page.locator("[data-study]").count() == 5
                assert page.locator("#maturityLegend .maturity-item").count() == 4
                assert page.locator("#participants .person-tag").count() >= 8
                assert page.locator("#protocolGrid .protocol-item").count() == 7
                page.close()

            page = browser.new_page(viewport={"width": 768, "height": 900})
            page.goto(AGENDA_PAGE.as_uri(), wait_until="domcontentloaded")
            for phase, expected in ((30, "3 de 5 pesquisas"), (90, "1 de 5 pesquisas"), (180, "1 de 5 pesquisas")):
                page.locator("#phase").select_option(str(phase))
                assert expected in page.locator("#resultsMeta").inner_text()

            page.locator("#phase").select_option("30")
            page.locator('[data-track="pessoas"]').click()
            assert "1 de 5 pesquisas" in page.locator("#resultsMeta").inner_text()

            page.locator('[data-track="all"]').click()
            phase_button = page.locator('[data-phase-focus="90"]')
            phase_button.focus()
            phase_button.press("Enter")
            assert phase_button.get_attribute("aria-pressed") == "true"
            assert page.locator('[data-phase-card="90"].is-focused').count() == 1

            summary = page.locator("summary").first
            summary.focus()
            summary.press("Enter")
            assert page.locator("details[open]").count() >= 1

            page.emulate_media(reduced_motion="reduce")
            assert page.evaluate("window.matchMedia('(prefers-reduced-motion: reduce)').matches") is True
            assert "prefers-reduced-motion" in page.content()
            page.close()

            for width in (320, 360, 768, 1440):
                catalog_page = browser.new_page(viewport={"width": width, "height": 900})
                catalog_page.goto(CATALOG.as_uri(), wait_until="domcontentloaded")
                catalog_page.locator("#cards .card").first.wait_for()
                dimensions = catalog_page.locator("body").evaluate(
                    "body => ({bodyWidth: body.scrollWidth, documentWidth: document.documentElement.scrollWidth, viewport: window.innerWidth})"
                )
                assert dimensions["viewport"] == width
                assert max(dimensions["bodyWidth"], dimensions["documentWidth"]) <= width + 1, (
                    f"overflow horizontal no catálogo em {width}px: {dimensions}"
                )
                assert catalog_page.locator(".catalog-maturity-item").count() == 4
                catalog_page.close()

            for width in (320, 360, 768, 1440):
                index_page = browser.new_page(viewport={"width": width, "height": 900})
                index_page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
                index_page.locator("h1").first.wait_for()
                dimensions = index_page.locator("body").evaluate(
                    "body => ({bodyWidth: body.scrollWidth, documentWidth: document.documentElement.scrollWidth, viewport: window.innerWidth})"
                )
                assert dimensions["viewport"] == width
                assert max(dimensions["bodyWidth"], dimensions["documentWidth"]) <= width + 1, (
                    f"overflow horizontal no feed em {width}px: {dimensions}"
                )
                assert index_page.locator("h1").count() >= 1
                index_page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    for test in (
        test_agenda_schema_and_inline_copy,
        test_agenda_sources_exist,
        test_catalog_entries_are_unique_and_local_links_exist,
        test_research_pages_have_minimum_document_metadata,
        test_rendered_responsive_interactions_and_accessibility,
    ):
        test()
    print("RESEARCH_AGENDA_QA_OK")
