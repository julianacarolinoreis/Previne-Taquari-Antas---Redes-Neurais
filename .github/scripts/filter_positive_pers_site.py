import json
import re
from collections import Counter
from pathlib import Path


PERS_KEYS = ["PERS_geral", "PERS_treino", "PERS_validacao", "PERS_teste"]


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


def replace_once(text, pattern, replacement, label):
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count == 0:
        print(f"Warning: static patch not applied ({label})")
    return updated


def patch_static_copy(html):
    step3 = """      <div class="step">
        <div class="s-num">Passo 3 · A varredura dos cenários</div>
        <div class="s-title">Cenários, inputs e rotações</div>
        <div class="s-text">A pesquisa não compara <strong>ALT</strong> e <strong>CONV</strong> como se fossem duas equações de
          saída diferentes. Cada rodada precisa ser lida pela própria ficha auditável: horizonte de antecedência,
          conjunto de inputs, defasagens, número de neurônios, rotação dos eventos de cheia, planilha, arquivo
          <span style="font-variant-numeric:tabular-nums">.mat</span>, logs e métricas calculadas. Assim, o resultado
          não é só o nome da família; é o pacote completo que acompanha aquele modelo.</div>
      </div>"""
    html = replace_once(
        html,
        r'\s*<div class="step">\s*<div class="s-num">Passo 3 .*?</div>\s*<div class="s-title">.*?</div>\s*<div class="s-text">.*?</div>\s*</div>',
        "\n" + step3,
        "passo 3",
    )
    html = replace_once(
        html,
        r'(<h2>Onde ficam.*?</h2>\s*)<p class="sec-sub">.*?</p>',
        r'\1<p class="sec-sub">A estação-alvo em Santa Tereza, a estação de montante e as estações/municípios de apoio usados nas rodadas de modelagem. Quando a identificação ou a coordenada ainda precisa ser confirmada, o cartão indica isso e abre o HidroWeb para conferência.</p>',
        "subtitulo estacoes",
    )
    html = replace_once(
        html,
        r'(<h2>Desempenho por fam.*?</h2>\s*)<p class="sec-sub">.*?</p>',
        r'\1<p class="sec-sub">Todos os modelos de cada família com a métrica escolhida <strong>acima de 0,500</strong> (até dez por quadro). Use como leitura comparativa por horizonte e rodada; a conferência final fica na ficha auditável de cada modelo. <strong>Clique em qualquer modelo</strong> para abrir tudo dele.</p>',
        "subtitulo desempenho",
    )
    if "<dt>CONV / ALT</dt>" not in html:
        html = replace_once(
            html,
            r'<dt>CONV</dt><dd>.*?</dd>\s*<dt>ALT</dt><dd>.*?</dd>',
            '<dt>CONV / ALT</dt><dd>Siglas de famílias/rodadas no planilhão. Elas não devem ser lidas isoladamente como equações de saída diferentes; a interpretação correta vem da ficha auditável de cada modelo: inputs, defasagens, horizonte, eventos, planilha, .mat, logs e métricas.</dd>',
            "glossario conv alt",
        )
    stations = """    {name:'Estação 86298000', code:'86298000', papel:'Identificação e coordenada a confirmar', grp:'conv', lat:null, lon:null,
     extra:'Estação usada nas rodadas; confirmar ficha oficial no HidroWeb/ANA'},
    {name:'Antônio Prado', code:'—', papel:'Identificação e coordenada a confirmar no HidroWeb/ANA', grp:'conv', lat:-28.858, lon:-51.283, hidro:true,
     extra:'Município de apoio usado nas rodadas; conferir código e coordenada oficial'},
    {name:'Nova Roma do Sul', code:'—', papel:'Identificação e coordenada a confirmar no HidroWeb/ANA', grp:'conv', lat:-28.988, lon:-51.410, hidro:true,
     extra:'Município de apoio usado nas rodadas; conferir código e coordenada oficial'},
    {name:'Caxias do Sul', code:'—', papel:'Identificação e coordenada a confirmar no HidroWeb/ANA', grp:'conv', lat:-29.168, lon:-51.179, hidro:true,
     extra:'Município de apoio usado nas rodadas; conferir código e coordenada oficial'},
    {name:'Muitos Capões', code:'—', papel:'Identificação e coordenada a confirmar no HidroWeb/ANA', grp:'conv', lat:-28.317, lon:-51.184, hidro:true,
     extra:'Município de apoio usado nas rodadas; conferir código e coordenada oficial'},
    {name:'Cotiporã', code:'—', papel:'Identificação e coordenada a confirmar no HidroWeb/ANA', grp:'conv', lat:-28.987, lon:-51.697, hidro:true,
     extra:'Município de apoio usado nas rodadas; conferir código e coordenada oficial'}"""
    html = replace_once(
        html,
        r"    \{name:'Estação 86298000'.*?    \{name:'Cotiporã'.*?\}",
        stations,
        "estacoes hidroweb",
    )
    html = html.replace("if(st.code!=='—'){", "if(st.code!=='—' || st.hidro){")
    html = html.replace(
        "lk.textContent='consultar no Hidroweb/ANA (buscar pelo código '+st.code+') ↗';",
        "lk.textContent=st.code!=='—'\n          ? 'consultar no HidroWeb/ANA (buscar pelo código '+st.code+') ↗'\n          : 'consultar no HidroWeb/ANA (confirmar identificação e coordenada) ↗';",
    )
    ev_label = """function fmtEventoData(value){
    if(!value) return '';
    const m=String(value).match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : '';
  }
  function evLabel(ev){
    const ini=fmtEventoData(ev.start), fim=fmtEventoData(ev.end);
    const periodo=ini && fim ? ini+' a '+fim : ini;
    return 'Evento '+ev.evento+(periodo?' · '+periodo:'');
  }"""
    html, count = re.subn(
        r"function evLabel\(ev\)\{.*?return 'Evento '\+ev\.evento.*?\n  \}",
        lambda _match: ev_label,
        html,
        count=1,
        flags=re.S,
    )
    if count == 0:
        print("Warning: static patch not applied (datas eventos modal)")
    return html


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
    html = re.sub(r'audit_charts\.css(?:\?v=[^"]*)?', "audit_charts.css?v=20260705-pers-positive-v1", html)
    html = re.sub(r'audit_charts\.js(?:\?v=[^"]*)?', "audit_charts.js?v=20260705-pers-positive-v1", html)
    html = html.replace("239 modelos em 10 rodadas", "158 modelos com PERS positivos")
    html = html.replace("Exploração dos 239 modelos", "Exploração dos modelos com PERS positivos")
    html = html.replace("todos os 239 modelos", "os 158 modelos com todos os PERS positivos")
    html = html.replace("239 modelos", "158 modelos com PERS positivos")
    html = patch_static_copy(html)
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


def patch_audit_js():
    path = Path("assets/js/audit_charts.js")
    js = path.read_text(encoding="utf-8")
    if "POSITIVE_PERS_KEYS" not in js:
        js = js.replace(
            "  const FAMILY_ORDER = ['2H_ALT', '2H_CONV', '4H_ALT', '4H_CONV', '8H_ALT', '8H_CONV', '12H_ALT', '12H_CONV'];\n  const nf = new Intl.NumberFormat('pt-BR');",
            "  const FAMILY_ORDER = ['2H_ALT', '2H_CONV', '4H_ALT', '4H_CONV', '8H_ALT', '8H_CONV', '12H_ALT', '12H_CONV'];\n  const POSITIVE_PERS_KEYS = ['PERS_geral', 'PERS_treino', 'PERS_validacao', 'PERS_teste'];\n  const nf = new Intl.NumberFormat('pt-BR');",
        )
        js = js.replace(
            "        payload = data;\n        rewriteIntroForResults();",
            "        payload = data;\n        applyPositivePersFilterToAuditPayload();\n        rewriteIntroForResults();",
        )
        js = js.replace(
            "      return Array.isArray(data.models) ? data.models : [];",
            "      return Array.isArray(data.models) ? data.models.filter(hasAllPositivePers) : [];",
        )
        helpers = """

  function hasAllPositivePers(model) {
    return !!model && POSITIVE_PERS_KEYS.every(key => typeof model[key] === 'number' && model[key] > 0);
  }

  function applyPositivePersFilterToAuditPayload() {
    if (!payload || !Array.isArray(payload.models) || !mainModels.length) return;
    payload.models = payload.models.filter(model => !!findMainForAudit(model));
    const keptNames = new Set(payload.models.flatMap(model => [norm(model.id), norm(model.name)]).filter(Boolean));
    payload.eventRiseTop = (payload.eventRiseTop || []).filter(row => keptNames.has(norm(row.model)));
    const families = {};
    let pointCount = 0;
    payload.models.forEach(model => {
      const family = model.family || 'OUTROS';
      families[family] = (families[family] || 0) + 1;
      if (model.scatterBySet) {
        Object.values(model.scatterBySet).forEach(points => { pointCount += Array.isArray(points) ? points.length : 0; });
      } else if (Array.isArray(model.scatter)) {
        pointCount += model.scatter.length;
      }
    });
    payload.meta = Object.assign({}, payload.meta || {}, {
      modelCount: payload.models.length,
      pointCount: pointCount || (payload.meta && payload.meta.pointCount) || 0,
      families,
      positivePersFilter: 'Mantidos apenas modelos associados a registros do planilhão com PERS_geral, PERS_treino, PERS_validacao e PERS_teste positivos.'
    });
  }
"""
        js = js.replace("\n  function setupControls() {", helpers + "\n  function setupControls() {")

    js = re.sub(
        r"stamp\.textContent = 'Pesquisa em desenvolvimento.*?base atualizada em 04/07/2026';",
        "stamp.textContent = 'Pesquisa em desenvolvimento · ' + nf.format(mainModels.length || 158) + ' modelos com todos os PERS positivos no planilhão principal' + (payload && payload.meta ? ' + ' + nf.format(payload.meta.modelCount) + ' séries auditáveis filtradas' : '') + ' · base atualizada em 05/07/2026';",
        js,
        flags=re.S,
    )
    js = js.replace(
        "setSectionTitle('Exploração dos 239 modelos', 'Exploração do planilhão principal');",
        "setSectionTitle('Exploração dos 239 modelos', 'Exploração dos modelos com PERS positivos');",
    )
    if "const refs = sectionByHeading('Referências')" not in js:
        js = js.replace(
            "    if (notes && notes.parentNode) notes.parentNode.insertBefore(section, notes);\n    else wrap.appendChild(section);",
            "    const refs = sectionByHeading('Referências') || [...document.querySelectorAll('section.sec')].find(sec => {\n      const h = sec.querySelector('h2');\n      return h && norm(h.textContent) === 'REFERENCIAS';\n    });\n    if (refs && refs.parentNode) refs.parentNode.insertBefore(section, refs);\n    else if (notes && notes.parentNode) notes.parentNode.insertBefore(section, notes);\n    else wrap.appendChild(section);",
        )
    js = re.sub(
        r"rewriteStep\('PASSO_3', \{.*?\n    \}\);",
        "rewriteStep('PASSO_3', {\n      title: 'Cenários, inputs e rotações',\n      text: 'A pesquisa não compara ALT e CONV como se fossem duas equações de saída diferentes. Cada rodada precisa ser lida pela própria ficha auditável: horizonte de antecedência, conjunto de inputs, defasagens, número de neurônios, rotação dos eventos de cheia, planilha, arquivo .mat, logs e métricas calculadas. Assim, o resultado não é só o nome da família; é o pacote completo que acompanha aquele modelo.'\n    });",
        js,
        flags=re.S,
    )
    js = js.replace(
        "? 'Evento ' + ev.evento + ' - ' + ev.conjunto + ' | subida ' + fmtCm(ev.riseObs) + ' | MAE ' + fmtCm(ev.mae)",
        "? eventLabel(ev, true) + ' - ' + ev.conjunto + ' | subida ' + fmtCm(ev.riseObs) + ' | MAE ' + fmtCm(ev.mae)",
    )
    js = js.replace(
        "const W = 620, rowH = 22, H = 34 + rows.length * rowH + 28, pad = { l: 112, r: 46, t: 14, b: 22 };",
        "const W = 620, rowH = 22, H = 34 + rows.length * rowH + 28, pad = { l: 150, r: 46, t: 14, b: 22 };",
    )
    js = js.replace(
        "svgText(svg, pad.l - 9, y + 11, 'Evento ' + r.evento, 'audit-label', 'end');",
        "svgText(svg, pad.l - 9, y + 11, eventLabel(r, false), 'audit-label', 'end');",
    )
    js = js.replace(
        "box.append(svg);\n  }\n\n  function renderAuditMetrics(model) {",
        "const note = document.createElement('div');\n    note.className = 'audit-event-note';\n    note.textContent = '* A data exibida é o início da onda na planilha auditável; quando há fim registrado, o seletor mostra o período completo.';\n    box.append(svg, note);\n  }\n\n  function renderAuditMetrics(model) {",
    )
    if "function eventLabel(ev, full)" not in js:
        helpers = """

  function fmtDate(value) {
    const match = String(value || '').match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
    return match ? match[3] + '/' + match[2] + '/' + match[1] : '';
  }

  function fmtMonthYear(value) {
    const months = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    const match = String(value || '').match(/^(\\d{4})-(\\d{2})-/);
    if (!match) return '';
    const index = Number(match[2]) - 1;
    return months[index] ? months[index] + '/' + match[1].slice(2) : '';
  }

  function eventLabel(ev, full) {
    const base = 'Evento ' + (ev && ev.evento != null ? ev.evento : '-');
    if (!ev) return base;
    if (!full) {
      const month = fmtMonthYear(ev.start);
      return base + (month ? ' · ' + month : '');
    }
    const start = fmtDate(ev.start);
    const end = fmtDate(ev.end);
    const period = start && end ? start + ' a ' + end : start;
    return base + (period ? ' · ' + period : '');
  }
"""
        js = js.replace("\n  function scale(a, b, x0, x1) {", helpers + "\n  function scale(a, b, x0, x1) {")
    path.write_text(js, encoding="utf-8")


def main():
    original_main, positive_main = filter_index()
    original_audit, kept_audit = filter_audit_series(positive_main)
    patch_audit_js()

    if len(positive_main) != 158:
        raise SystemExit(f"Expected 158 positive main models, found {len(positive_main)}")
    if any(any(model.get(key) is None or model.get(key) <= 0 for key in PERS_KEYS) for model in positive_main):
        raise SystemExit("Found a model with non-positive PERS after filtering")
    if len(kept_audit) != 313:
        raise SystemExit(f"Expected 313 filtered audit series, found {len(kept_audit)}")

    print("Filtered main models:", len(original_main), "->", len(positive_main))
    print("Filtered audit series:", len(original_audit), "->", len(kept_audit))
    print("Positive family counts:", dict(Counter(model.get("familia") for model in positive_main)))


if __name__ == "__main__":
    main()
