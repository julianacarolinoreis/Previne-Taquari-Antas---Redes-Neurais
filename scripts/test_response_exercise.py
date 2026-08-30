"""QA estrutural e renderizado da sala de decisão V002.

O teste verifica contrato, proveniência, estados de segurança e interação em
larguras críticas. Ele não valida rota de campo, capacidade de abrigo ou
desempenho hidrológico; esses continuam sendo gates externos ao protótipo.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "pesquisas" / "estudo-caso-resposta-santa-tereza.html"
CONTRACT = ROOT / "assets" / "data" / "estudo_caso_resposta_v002.json"
ROUTE = ROOT / "assets" / "data" / "rota_fuga_santa_tereza_cenario.json"
SHELTERS = ROOT / "assets" / "data" / "servicos" / "abrigos.geojson"
LIVE = ROOT / "previsao_ao_vivo.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_and_sources() -> None:
    contract = load_json(CONTRACT)
    route = load_json(ROUTE)
    shelter = load_json(SHELTERS)["features"][0]
    live = load_json(LIVE)

    assert contract["schema_version"] == 2
    assert contract["mode"] == "exercise"
    assert contract["operational_gate"]["status"] == "blocked"
    assert set(contract["operational_gate"]["disallowed"]) >= {
        "official_alert",
        "evacuation_order",
        "public_dispatch",
        "route_navigation",
    }
    assert contract["event"]["timezone"] == "America/Sao_Paulo"
    assert contract["event"]["issued_at"] is None
    assert contract["event"]["valid_until"] is None

    spatial = contract["spatial"]
    assert spatial["cell_count"] == len(route["quadras"]) == 258
    assert spatial["level_cm"] == route["meta"]["nivel_atual_cm"]
    assert spatial["grid_m"] == route["meta"]["bloco_m"]
    assert spatial["summary"] == route["resumo"]
    assert spatial["crs"] == "unknown"
    assert spatial["generated_at_iso"].endswith("-03:00")
    assert spatial["timezone"] == "America/Sao_Paulo"
    assert spatial["route_status"] == "synthetic_unvalidated"
    assert spatial["safe_point_confirmed"] is False

    route_points = {(round(point["lat"], 6), round(point["lon"], 6)): point for point in route["quadras"]}
    assert len(contract["zones"]) == 4
    for zone in contract["zones"]:
        point = route_points[(round(zone["latitude"], 6), round(zone["longitude"], 6))]
        assert zone["arrival_min"] == point["min_ate_agua"]
        assert zone["hand_m"] == point["hand_m"]
        assert zone["flood_cota_m"] == point["cota_alaga_m"]
        assert zone["people_status"] == "aggregate_estimate"
        assert zone["route_status"] == "synthetic_unvalidated"

    shelter_properties = shelter["properties"]
    shelter_contract = contract["shelter"]
    assert shelter_contract["id"] == shelter_properties["id"]
    assert shelter_contract["name"] == shelter_properties["nome"]
    assert shelter_contract["capacity"] is None
    assert shelter_contract["occupancy"] is None
    assert shelter_contract["status"] == "unknown"
    assert shelter_contract["safe_point_confirmed"] is False
    assert shelter["geometry"]["coordinates"] == [shelter_contract["longitude"], shelter_contract["latitude"]]

    assert live["modo"] == "ao_vivo"
    assert live["input_contract_version"] == "hourly_exact_v1"
    assert live["estacao"] == contract["forecast"]["station"]
    assert live["bankfull_cm"] == contract["forecast"]["bankfull_cm"]
    assert live["gerado_em"] == contract["forecast"]["source_snapshot_raw"] == "2026-08-28T20:00:00"
    assert contract["forecast"]["source_snapshot"] == "2026-08-28T20:00:00-03:00"
    assert contract["forecast"]["source_snapshot"].endswith("-03:00")
    assert "não declara offset" in contract["forecast"]["timestamp_note"]
    assert contract["forecast"]["round_base_level_cm"] == 222
    assert contract["forecast"]["observed_level_cm"] == 276
    assert contract["forecast"]["observed_at"].endswith("-03:00")
    assert contract["forecast"]["consulted_at"].endswith("-03:00")
    assert contract["forecast"]["observed_age_at_consult_min"] == 48
    assert contract["forecast"]["status"] == "snapshot_only"
    assert contract["forecast"]["freshness_policy"] == {
        "missing": "unknown",
        "outside_validity": "stale",
        "max_observation_age_min": 60,
        "interpolation": False,
        "nearest_neighbor": False,
        "timezone": "America/Sao_Paulo",
    }
    assert len(contract["forecast"]["horizons"]) == 2
    for item in contract["forecast"]["horizons"]:
        source_key = "8h" if item["id"] == "8h_v001" else "8h_v002"
        source = live["horizontes"][source_key]
        assert item["model"] == source["modelo"]
        assert item["forecast_cm"] == source["nivel_previsto_cm"]
        assert item["publication"] == source["status_publicacao"]
        assert item["shadow"] is bool(source["shadow_only"])

    source_paths = [item["path"] for item in contract["sources"]]
    assert "previsao_ao_vivo.json" in source_paths
    assert "assets/data/rota_fuga_santa_tereza_cenario.json" in source_paths
    assert "assets/data/servicos/abrigos.geojson" in source_paths
    for source_path in source_paths:
        if source_path == "pesquisas/estudo-caso-resposta-santa-tereza.html":
            target = ROOT / source_path
        else:
            target = ROOT / source_path
        assert target.is_file(), f"fonte quebrada: {source_path}"

    assert len(contract["validation_checklist"]) == 7
    assert {item["status"] for item in contract["validation_checklist"]} == {"unknown"}
    assert len(contract["exercise_metrics"]) == 9
    assert {item["id"] for item in contract["exercise_metrics"]} == {
        "time_to_first_decision_min",
        "time_to_route_confirmation_min",
        "unlocated_count",
        "shelter_capacity_gap",
        "message_comprehension",
        "critical_failures",
        "communication_ready",
        "resource_task_ready",
        "contingency_result",
    }
    assert all(item["value"] is None for item in contract["exercise_metrics"])
    assert [item["offset_min"] for item in contract["timeline"] if "offset_min" in item][2] == 54
    assert {item["id"] for item in contract["contingencies"]} == {"route", "shelter", "comms", "night"}
    assert "unknown" in contract["state_vocabulary"]
    assert "stale" in contract["state_vocabulary"]
    assert len(contract["stop_criteria"]) >= 5


def test_page_embeds_the_audited_snapshot_and_guardrails() -> None:
    html = CASE.read_text(encoding="utf-8")
    live_match = re.search(r"const LIVE = (\{.*?\});\s*\n", html, flags=re.S)
    assert live_match, "snapshot LIVE ausente da página"
    embedded = json.loads(live_match.group(1))
    contract = load_json(CONTRACT)
    assert embedded["snapshot"] == contract["forecast"]["source_snapshot"]
    assert embedded["snapshot_raw"] == contract["forecast"]["source_snapshot_raw"]
    assert embedded["observed_cm"] == contract["forecast"]["observed_level_cm"]
    assert embedded["v001"]["forecast_cm"] == 284.0
    assert embedded["v002"]["forecast_cm"] == 320.0
    assert "V002 · exercício" in html
    assert "estudo_caso_resposta_v002.json" in html
    assert "UNKNOWN" in html and "STALE" in html
    assert "nenhum despacho real será enviado" in html
    assert "navigator.geolocation" not in html
    assert "fetch(" not in html


def _chrome_executable() -> str | None:
    configured = os.environ.get("PREVINE_CHROME_PATH")
    candidates = [Path(configured)] if configured else []
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.extend(
        [
            Path(program_files) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def test_rendered_responsive_interactions() -> None:
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
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append("pageerror: " + str(error)))
                page.on("console", lambda message: errors.append("console: " + message.text) if message.type == "error" else None)
                page.goto(CASE.as_uri(), wait_until="domcontentloaded")
                page.locator("#eventBriefTitle").wait_for()
                dimensions = page.locator("body").evaluate(
                    "body => ({bodyWidth: body.scrollWidth, documentWidth: document.documentElement.scrollWidth, viewport: window.innerWidth})"
                )
                assert dimensions["viewport"] == width
                assert max(dimensions["bodyWidth"], dimensions["documentWidth"]) <= width + 1, (
                    f"overflow horizontal em {width}px: {dimensions}"
                )
                assert page.locator("#validationChecklist [data-validation]").count() == 7
                assert page.locator("#scoreboard .score-item").count() == 9
                assert page.locator("#gateStatus").inner_text().lower() == "bloqueado"
                if page.locator("#freshnessStatus").inner_text() in {"UNKNOWN", "STALE"}:
                    assert "sinal" in page.locator("#gateNote").inner_text().lower()
                assert page.locator("#metricFirstDecision").inner_text() == "—"
                assert page.locator("#metricShelterGap").inner_text() == "—"
                assert page.locator("#metricMessageComprehension").inner_text() == "—"
                assert page.locator("#metricCommunicationReady").inner_text() == "—"
                assert page.locator("#metricResourceReady").inner_text() == "—"
                assert page.locator("#metricContingencyResult").inner_text() == "—"
                assert page.locator("#mapReadableSummary").is_visible()
                assert "Z-01" in page.locator("#mapReadableZone").inner_text()
                assert "Ginásio" in page.locator("#mapReadableDestination").inner_text()
                assert "UNKNOWN" in page.locator("#mapReadableDestination").inner_text()
                assert page.locator("#freshnessStatus").inner_text() in {"UNKNOWN", "STALE", "ATENÇÃO"}
                assert page.locator("#teaserAction").is_disabled()
                if width <= 780:
                    class_name = page.locator("#eventMap").get_attribute("class") or ""
                    assert "map-focus-mode" in class_name
                    font_size = page.locator("#mapZones .zone-map-code").first.evaluate("element => parseFloat(getComputedStyle(element).fontSize)")
                    assert font_size >= 20, f"rótulo do mapa pequeno em {width}px: {font_size}px"
                assert not errors, f"erros no console em {width}px: {errors}"
                page.close()

            page = browser.new_page(viewport={"width": 768, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append("pageerror: " + str(error)))
            page.on("console", lambda message: errors.append("console: " + message.text) if message.type == "error" else None)
            page.goto(CASE.as_uri(), wait_until="domcontentloaded")
            page.locator("#nextStep").click()
            assert page.locator("#eventClock").inner_text() == "T+00:30"
            page.locator('[data-validation="forecast"]').check()
            assert "1/7" in page.locator("#validationProgress").inner_text()
            page.locator(".measurement-panel summary").click()
            page.locator("#observer").fill("observador da mesa")
            page.locator("#messageComprehension").select_option("partial")
            page.locator("#criticalFailures").fill("1")
            assert page.locator("#metricCriticalFailures").inner_text() == "1"
            page.locator("#evacAction").click()
            assert page.locator("#metricFirstDecision").inner_text() == "30 min"
            page.locator(".contingency-panel summary").click()
            page.locator("#contingencySelect").select_option("route")
            page.locator("#contingencyApply").click()
            assert "rota principal fechada" in page.locator("#contingencyStatus").inner_text()
            assert page.locator("#metricContingencyResult").inner_text() == "pendente"
            with page.expect_download(timeout=5000) as download_info:
                page.locator("#exportLog").click()
            download = download_info.value
            assert "previne-exercicio-z-01" in download.suggested_filename
            exported = json.loads(Path(download.path()).read_text(encoding="utf-8"))
            assert exported["artifact"]["operational_gate"] == "blocked"
            assert exported["event"]["zone"] == "Z-01"
            assert exported["validation_checklist"]["forecast"] is True
            assert exported["exercise_metrics"]["criticalFailures"] == 1
            assert exported["exercise_metrics"]["derived"]["critical_failures"] == 1
            assert exported["exercise_metrics"]["derived"]["contingency_state"] == "pendente"
            assert not errors, f"erros no console durante interação: {errors}"
            page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    for test in (test_contract_and_sources, test_page_embeds_the_audited_snapshot_and_guardrails, test_rendered_responsive_interactions):
        test()
    print("RESPONSE_EXERCISE_QA_OK")
