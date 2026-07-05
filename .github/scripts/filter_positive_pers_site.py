import json
import re
from collections import Counter
from pathlib import Path


PERS_KEYS = ["PERS_geral", "PERS_treino", "PERS_validacao", "PERS_teste"]
CACHE_VERSION = "20260705-lazy-audit-v3"


def norm(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def has_all_positive_pers(model):
    return all(isinstance(model.get(key), (int, float)) and model.get(key) > 0 for key in PERS_KEYS)


def main_score(audit, main):
    score = 0
    family = norm(audit.get("family"))
    combo = norm(audit.get("combo"))
    rotation = norm(audit.get("rotation"))
    audit_name = norm(audit.get("name"))
    audit_id = norm(audit.get("id"))
    main_name = norm(main.get("modelo"))
    main_family = norm(main.get("familia"))
    main_combo = norm(main.get("combo_id"))
    main_rotation = norm(main.get("rotacao"))
    if audit_name and audit_name == main_name:
        return 999
    if audit_id and audit_id == main_name:
        return 999
    if family and family == main_family:
        score += 20
    if combo and (combo == main_combo or combo in main_name):
        score += 25
    if rotation and (rotation == main_rotation or rotation in main_name):
        score += 20
    if audit_name and main_name and (audit_name in main_name or main_name in audit_name):
        score += 40
    return score


def find_positive_main(audit, positive_models):
    best = None
    best_score = -1
    for main in positive_models:
        score = main_score(audit, main)
        if score > best_score:
            best = main
            best_score = score
    return best if best_score >= 40 else None


def filter_index():
    path = Path("index.html")
    html = path.read_text(encoding="utf-8")
    match = re.search(r'(<script id="data" type="application/json">)(.*?)(</script>)', html, re.S)
    if not match:
        raise SystemExit("Main data JSON block not found in index.html")

    data = json.loads(match.group(2))
    original = data.get("models", [])
    positive = [model for model in original if has_all_positive_pers(model)]
    data["models"] = positive
    data["positivePersFilter"] = {
        "rule": "PERS_geral, PERS_treino, PERS_validacao e PERS_teste precisam ser positivos.",
        "originalModelCount": len(original),
        "keptModelCount": len(positive),
        "removedModelCount": len(original) - len(positive),
    }

    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = html[: match.start(2)] + compact + html[match.end(2) :]
    html = re.sub(r'audit_charts\.css(?:\?v=[^"]*)?', f"audit_charts.css?v={CACHE_VERSION}", html)
    html = re.sub(r'audit_charts\.js(?:\?v=[^"]*)?', f"audit_charts.js?v={CACHE_VERSION}", html)
    html = re.sub(r"\n\s*setTimeout\(loadAudit,\s*1200\);", "\n  // Audit series are loaded on demand, not during page startup.", html)
    html = html.replace("239 modelos em 10 rodadas", "158 modelos com PERS positivos")
    html = html.replace("Exploração dos 239 modelos", "Exploração dos modelos com PERS positivos")
    html = html.replace("todos os 239 modelos", "os 158 modelos com todos os PERS positivos")
    html = html.replace("239 modelos", "158 modelos com PERS positivos")
    path.write_text(html, encoding="utf-8")
    return original, positive


def filter_audit_series(positive_main):
    path = Path("assets/data/auditaveis_series.json")
    audit = json.loads(path.read_text(encoding="utf-8"))
    original = audit.get("models", [])
    kept = []
    kept_names = set()

    for item in original:
        main = find_positive_main(item, positive_main)
        if main:
            item["positivePersMainModel"] = main.get("modelo")
            kept.append(item)
            kept_names.add(norm(item.get("id")))
            kept_names.add(norm(item.get("name")))

    audit["models"] = kept
    audit["eventRiseTop"] = [row for row in audit.get("eventRiseTop", []) if norm(row.get("model")) in kept_names]

    families = Counter(model.get("family") or "OUTROS" for model in kept)
    point_count = 0
    for model in kept:
        by_set = model.get("scatterBySet") or {}
        if by_set:
            point_count += sum(len(points) for points in by_set.values() if isinstance(points, list))
        elif isinstance(model.get("scatter"), list):
            point_count += len(model["scatter"])

    meta = dict(audit.get("meta") or {})
    meta.update(
        {
            "modelCount": len(kept),
            "pointCount": point_count,
            "families": dict(sorted(families.items())),
            "positivePersFilter": "Mantidos apenas modelos associados ao planilhao principal com PERS_geral, PERS_treino, PERS_validacao e PERS_teste positivos.",
            "originalAuditModelCount": len(original),
            "removedAuditModelCount": len(original) - len(kept),
        }
    )
    audit["meta"] = meta
    path.write_text(json.dumps(audit, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return original, kept


def main():
    original_main, positive_main = filter_index()
    original_audit, kept_audit = filter_audit_series(positive_main)

    if not positive_main:
        raise SystemExit("No positive-PERS models found")
    bad = [model.get("modelo") for model in positive_main if not has_all_positive_pers(model)]
    if bad:
        raise SystemExit(f"Found models with non-positive PERS after filtering: {bad[:5]}")

    print("Filtered main models:", len(original_main), "->", len(positive_main))
    print("Filtered audit series:", len(original_audit), "->", len(kept_audit))
    print("Positive family counts:", dict(Counter(model.get("familia") for model in positive_main)))
    print("Cache version:", CACHE_VERSION)


if __name__ == "__main__":
    main()
