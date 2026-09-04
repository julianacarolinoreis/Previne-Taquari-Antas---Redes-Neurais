#!/usr/bin/env python3
"""Gera HTML do relatório comparativo MIMO multi-horizonte."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_IN = ROOT / "assets/data/research_mimo_multihorizon_latest.json"
HTML_OUT = ROOT / "pesquisas/rna-multi-horizonte-relatorio.html"


def fmt(x, nd=4):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}".replace(".", ",")
    return str(x)


def verdict(delta_nash, delta_e95):
    if delta_e95 is None:
        return "empate"
    if delta_nash > 0.002 and delta_e95 <= 0:
        return "ganho"
    if delta_nash < -0.002 or delta_e95 > 1.0:
        return "perda"
    return "empate"


def render_table(summary, title="", footnote=""):
    rows = summary.get("ganhos", []) + summary.get("empates", []) + summary.get("perdas", [])
    html = [f"<h3>{title}</h3>" if title else ""]
    if footnote:
        html.append(f"<p class='meta'>{footnote}</p>")
    if not rows:
        html.append("<p>Sem comparações disponíveis.</p>")
        return "\n".join(html)
    html.append(
        "<table><thead><tr><th>Horizonte</th><th>NASH base</th><th>NASH MIMO</th><th>Δ NASH</th>"
        "<th>PERS base</th><th>PERS MIMO</th><th>E95 base</th><th>E95 MIMO</th><th>Δ E95</th><th>Leitura</th></tr></thead><tbody>"
    )
    for row in rows:
        v = verdict(row["delta_nash"], row.get("delta_e95_cm"))
        cls = {"ganho": "good", "perda": "bad", "empate": "neutral"}[v]
        base = row.get("direct") or {}
        mimo = row["mimo"]
        html.append(
            f"<tr class='{cls}'><td>{row['horizonte']}</td>"
            f"<td>{fmt(base.get('nash'))}</td><td>{fmt(mimo.get('nash'))}</td><td>{fmt(row['delta_nash'])}</td>"
            f"<td>{fmt(base.get('pers'))}</td><td>{fmt(mimo.get('pers'))}</td>"
            f"<td>{fmt(base.get('e95'),1)}</td><td>{fmt(mimo.get('e95'),1)}</td><td>{fmt(row.get('delta_e95_cm'),1)}</td>"
            f"<td>{v}</td></tr>"
        )
    html.append("</tbody></table>")
    return "\n".join(html)


def main():
    data = json.loads(JSON_IN.read_text(encoding="utf-8"))
    exp1 = data["experiments"]["exp1_2h4h_15in"]
    exp3 = data["experiments"]["exp3_2h4h8h_31in"]
    loo = data["experiments"]["exp5_leave_one_event_out_2h4h"]
    round3 = data["experiments"].get("exp6_close_mat_gap_2h4h") or {}
    round4 = data["experiments"].get("exp7_mat_scale_warmstart_fix") or {}
    ds = data["datasets"]
    ref = data["mat_reference_metrics_teste"]
    cons = data["trajectory_consistency"]
    repair_summary = exp1.get("summary_scratch_vs_mimo_repair") or {"ganhos": [], "empates": [], "perdas": []}
    repair_cons = cons.get("mimo_15in_repair_2h4h") or {}

    loo_rows = ""
    if loo.get("status") == "ok":
        for hz, payload in loo.get("pooled", {}).items():
            wins = loo.get("wins_by_event", {}).get(hz, {})
            loo_rows += (
                f"<tr><td>{hz}</td><td>{fmt(payload['direct_scratch']['nash'])}</td>"
                f"<td>{fmt(payload['mimo']['nash'])}</td><td>{fmt(payload['delta_nash'])}</td>"
                f"<td>{fmt(payload['delta_e95_cm'],1)}</td>"
                f"<td>{wins.get('mimo',0)} / {wins.get('direct',0)} / {wins.get('tie',0)}</td>"
                f"<td>{payload['n']}</td></tr>"
            )

    def _round_table(round_payload):
        rows_html = ""
        for item in round_payload.get("ranking") or []:
            v = round_payload["variants"][item["key"]]["splits"]["teste"]
            flag = "ok" if item["ok_2h_vs_scratch"] else "no"
            rows_html += (
                f"<tr><td>{item['key']}</td>"
                f"<td>{fmt(v['2h']['nash'])}</td><td>{fmt(v['4h']['nash'])}</td>"
                f"<td>{fmt(item['delta_scratch_4h'])}</td>"
                f"<td>{fmt(item['gap_mat_4h'])}</td>"
                f"<td>{flag}</td></tr>"
            )
        return rows_html

    round3_rows = _round_table(round3)
    round4_rows = _round_table(round4)
    round3_box = ""
    if round3:
        verd = round3.get("verdict", {})
        best = round3.get("best_variant", "—")
        round3_box = f"""
<h2>6b. Rodada 3 — fechar gap ao teto .mat</h2>
<p>Pergunta: {round3.get('question','')}</p>
<p><strong>Melhor variante:</strong> {best} · fecha gap&lt;0,10? {'sim' if verd.get('closes_mat_gap') else 'não'} ·
bate scratch no 4h? {'sim' if verd.get('beats_scratch_4h') else 'não'}</p>
<table><thead><tr><th>Variante</th><th>NASH 2h</th><th>NASH 4h</th><th>Δ scratch 4h</th><th>gap teto 4h</th><th>2h ok</th></tr></thead>
<tbody>{round3_rows or '<tr><td colspan="6">sem ranking</td></tr>'}</tbody></table>
<p class='meta'>{verd.get('note','')}</p>
<ul>
<li><strong>Peso em subidas</strong> foi a única alavanca Python estável (leve ganho no 4h).</li>
<li><strong>Warm-start full</strong> (ws+au/bu) colapsou — escala y sobrescrita no fit.</li>
<li><strong>Peso forte no 4h</strong> [1,2] piorou o 2h além do limiar.</li>
<li>Gap ao teto .mat no 4h ≈0,14 NASH.</li>
</ul>
"""
    round4_box = ""
    if round4:
        verd = round4.get("verdict", {})
        best = round4.get("best_variant", "—")
        r3ref = round4.get("round3_best_ref") or {}
        round4_box = f"""
<h2>6c. Rodada 4 — escala ae/be + warm-start corrigido</h2>
<p>Pergunta: {round4.get('question','')}</p>
<p class='meta'>Hipótese: {round4.get('hypothesis','')}</p>
<p><strong>Melhor variante:</strong> {best} · fecha gap&lt;0,10? {'sim' if verd.get('closes_mat_gap') else 'não'} ·
melhora r3 no 4h? {'sim' if verd.get('improves_vs_round3_4h') else 'não'}
{f" · r3 ref 4h NASH {fmt((r3ref.get('teste') or {}).get('4h', {}).get('nash'))}" if r3ref else ""}</p>
<table><thead><tr><th>Variante</th><th>NASH 2h</th><th>NASH 4h</th><th>Δ scratch 4h</th><th>gap teto 4h</th><th>2h ok</th></tr></thead>
<tbody>{round4_rows or '<tr><td colspan="6">sem ranking</td></tr>'}</tbody></table>
<p class='meta'>{verd.get('note','')}</p>
<ul>
<li><strong>warm_hidden_rising</strong> (Wh/bh do Direct + ae/be + peso em subidas) é estável e ligeiramente acima da r3 no 4h.</li>
<li><strong>mat_input_only</strong> (só congelar ae/be) já recupera quase o mesmo 4h — a escala de entrada importa mais que copiar ws.</li>
<li><strong>full_freeze_y</strong> ainda destrói o 2h; copiar a cabeça Direct não transferiu bem.</li>
<li><strong>stitch</strong> Direct2h+MIMO4h: no recorte alinhado o 2h dá NASH≈1 (replay), mas o 4h não sobe além do MIMO — não fecha o teto operacional.</li>
<li>Gap 4h permanece ≈0,12–0,13 → próximo passo: MATLAB nativo, não mais buscas ad-hoc em Python.</li>
</ul>
"""

    html = f"""<!doctype html>
<html lang='pt-BR'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Relatório RNA multi-horizonte (MIMO)</title>
<style>
body{{font-family:Georgia,serif;line-height:1.5;margin:24px auto;max-width:980px;color:#1a1a1a}}
h1,h2{{line-height:1.2}}
.good td:last-child{{color:#0f6b4a;font-weight:700}}
.bad td:last-child{{color:#a11919;font-weight:700}}
.neutral td:last-child{{color:#6a5a00;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin:12px 0 24px;font-size:14px}}
th,td{{border:1px solid #ccc;padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
.meta{{color:#555;font-size:13px}}
.box{{background:#f7f7f2;border:1px solid #ddd;padding:12px 14px;margin:16px 0}}
ul{{padding-left:20px}}
</style>
</head>
<body>
<h1>Relatório comparativo — RNA multi-horizonte (MIMO)</h1>
<p class='meta'>Gerado em {data['generated_at_utc']} · Santa Tereza · modo pesquisa (não operacional) · schema v{data.get('schema_version')}</p>

<div class='box'>
<strong>Pergunta:</strong> uma única rede prevendo 2h+4h (+8h) supera modelos Direct?<br>
<strong>Comparação justa:</strong> Direct scratch vs MIMO — mesmo pipeline Python.<br>
<strong>Teto operacional:</strong> métricas do .mat no <em>teste completo</em> (`mat_reference_metrics_teste`). O replay alinhado do .mat dá NASH≈1 e não é teto.<br>
<strong>Extra:</strong> leave-one-event-out, loss de trajetória e correção pós-hoc em subidas.
</div>

<h2>1. Amostras alinhadas</h2>
<ul>
<li>2h+4h: {ds['2h_4h_aligned']['n_rows']} linhas · teste {ds['2h_4h_aligned']['split_counts'].get('3')} · eventos {ds['2h_4h_aligned'].get('n_events','—')}</li>
<li>2h+4h+8h: {ds['2h_4h_8h_aligned']['n_rows']} linhas · teste {ds['2h_4h_8h_aligned']['split_counts'].get('3')}</li>
</ul>

<h2>2. Referência .mat (teste completo)</h2>
<ul>
<li>2h: NASH {fmt(ref['2h']['nash'])} · PERS {fmt(ref['2h']['pers'])} · E95 {fmt(ref['2h']['e95'],1)} cm</li>
<li>4h: NASH {fmt(ref['4h']['nash'])} · PERS {fmt(ref['4h']['pers'])} · E95 {fmt(ref['4h']['e95'],1)} cm</li>
</ul>

<h2>3. Experimento principal — 2h + 4h (15 inputs)</h2>
<p>MIMO base: nh={exp1['mimo']['training']['hidden']}, seed={exp1['mimo']['training']['seed']}.</p>
{render_table(exp1['summary_scratch_vs_mimo'], 'Direct scratch vs MIMO base')}
{render_table(repair_summary, 'Direct scratch vs MIMO + correção pós-hoc')}
{render_table(
    exp1['summary_mat_vs_mimo'],
    '.mat (teste completo) vs MIMO — teto operacional',
    footnote='Baseline = mat_reference_metrics_teste. Não usar o replay alinhado (NASH≈1) como teto.',
)}
{render_table(
    exp1.get('summary_mat_aligned_replay_vs_mimo') or {'ganhos': [], 'empates': [], 'perdas': []},
    '.mat alinhado (replay) vs MIMO — auditoria, não teto',
    footnote=data['method'].get('note_mat_aligned_replay') or 'Replay das predições armazenadas no .mat no recorte alinhado.',
)}

<h2>4. Leave-one-event-out</h2>
<p>Status: {loo.get('status')} · eventos avaliados: {loo.get('n_events_evaluated')}</p>
<table><thead><tr><th>Horizonte</th><th>NASH Direct</th><th>NASH MIMO</th><th>Δ NASH</th><th>Δ E95</th><th>Vitórias MIMO/Direct/empate</th><th>n</th></tr></thead>
<tbody>{loo_rows or '<tr><td colspan="7">LOO indisponível</td></tr>'}</tbody></table>

<h2>5. Coerência de trajetória no teste</h2>
<ul>
<li>MIMO base — violação em subidas: {fmt(cons['mimo_15in_2h4h'].get('rising_violation_rate'), 3)} ({cons['mimo_15in_2h4h'].get('n_rising_violations')}/{cons['mimo_15in_2h4h'].get('n_rising')})</li>
<li>MIMO repair — violação em subidas: {fmt(repair_cons.get('rising_violation_rate'), 3)}</li>
<li>Direct .mat — violação em subidas: {fmt(cons['direct_2h4h'].get('rising_violation_rate'), 3)}</li>
</ul>
<p>{data['method'].get('note_mono_loss','')}</p>

<h2>6. Experimento 2h+4h+8h</h2>
<p>Amostra pequena (n_teste={ds['2h_4h_8h_aligned']['split_counts'].get('3')}).</p>
{render_table(exp3['summary_scratch_vs_mimo'], 'Direct scratch vs MIMO')}

{round3_box}

{round4_box}

<h2>7. Handoff MATLAB (próximo passo nativo)</h2>
<p>Pacote de dados alinhados + script <code>train_mimo_2h4h_stz.m</code> em
<code>codigo_python/11_experimento_mimo/matlab/</code>. CSVs em
<a href='../assets/data/research_mimo_matlab_handoff/manifest.json'>assets/data/research_mimo_matlab_handoff/</a>.
Rodar no MATLAB e comparar ao teto <code>mat_reference_metrics_teste</code> — não ao replay NASH≈1.
As rodadas 3–4 esgotaram alavancas Python estáveis (pesos de subida, ae/be congelado, warm-start só na oculta):
gap 4h ≈0,12–0,13. Treino nativo MATLAB com a pipeline dos Direct permanece o caminho.</p>

<h2>8. JSON auditável</h2>
<p><a href='../assets/data/research_mimo_multihorizon_latest.json'>assets/data/research_mimo_multihorizon_latest.json</a></p>
</body></html>"""
    HTML_OUT.write_text(html, encoding="utf-8")
    print("OK", HTML_OUT)


if __name__ == "__main__":
    main()
