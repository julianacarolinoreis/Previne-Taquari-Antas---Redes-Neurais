import json
from seg import load_events, segment

evs, conj = load_events('wb_top12h.xlsx')
PEAK_MIN = 500

def svg_event(ev, niv, keep, win=None):
    W, H = 300, 120
    padL, padR, padT, padB = 6, 6, 8, 14
    n = len(niv)
    lo, hi = min(niv), max(niv)
    hi = max(hi, PEAK_MIN + 40)
    rng = hi - lo or 1
    def X(i): return padL + (W - padL - padR) * (i / max(1, n - 1))
    def Y(v): return padT + (H - padT - padB) * (1 - (v - lo) / rng)
    parts = []
    # linha do limiar 5m
    y5 = Y(PEAK_MIN)
    parts.append(f'<line x1="{padL}" y1="{y5:.1f}" x2="{W-padR}" y2="{y5:.1f}" stroke="#c9a227" stroke-width="1" stroke-dasharray="3 3"/>')
    parts.append(f'<text x="{W-padR}" y="{y5-3:.1f}" text-anchor="end" font-size="8" fill="#a8801a">5 m</text>')
    # faixas mantidas (subida) sombreadas
    i = 0
    while i < n:
        if keep[i]:
            j = i
            while j < n and keep[j]: j += 1
            x0, x1 = X(i), X(j - 1)
            parts.append(f'<rect x="{x0:.1f}" y="{padT}" width="{max(1,x1-x0):.1f}" height="{H-padT-padB}" fill="#1b7a5a" opacity="0.13"/>')
            i = j
        else:
            i += 1
    # linha do nivel — verde onde mantido, cinza onde descartado
    def poly(pred, color, w):
        d = []
        for i in range(n):
            seg_on = pred(i)
            if seg_on:
                d.append(f'{X(i):.1f},{Y(niv[i]):.1f}')
            else:
                if d:
                    parts.append(f'<polyline points="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="{w}"/>')
                    d = []
        if d:
            parts.append(f'<polyline points="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="{w}"/>')
    # cinza (todo o traçado, fino, por baixo)
    allpts = " ".join(f'{X(i):.1f},{Y(niv[i]):.1f}' for i in range(n))
    parts.append(f'<polyline points="{allpts}" fill="none" stroke="#b8bfc7" stroke-width="1.4"/>')
    # verde apenas nas subidas mantidas (segmentos contíguos)
    i = 0
    while i < n:
        if keep[i]:
            j = i
            pts = []
            while j < n and keep[j]:
                pts.append(f'{X(j):.1f},{Y(niv[j]):.1f}'); j += 1
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#0f6b4a" stroke-width="2.4"/>')
            i = j
        else:
            i += 1
    if win:
        L,P,R = win
        parts.append(f'<circle cx="{X(P):.1f}" cy="{Y(niv[P]):.1f}" r="3" fill="#c0392b"/>')
    return f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block">{"".join(parts)}</svg>'

cards = []
tot = kept_tot = 0
for ev, niv in evs.items():
    keep, win = segment(niv, PEAK_MIN)
    k = sum(keep); tot += len(niv); kept_tot += k
    pura = k == 0
    if pura:
        motivo = 'pico não passa de 5 m — evento inteiro sai' if max(niv) < PEAK_MIN else 'só um espetinho — evento inteiro sai'
        tag = f'<span class="tag drop">{motivo}</span>'
    else:
        L,P,R = win
        tag = f'<span class="tag keep">{k} de {len(niv)} mantidas · inicia em {niv[L]} cm</span>'
    cards.append(f'''<div class="card {'off' if pura else ''}">
      <div class="chd"><b>Evento {ev}</b> <span class="conj">{conj[ev]}</span> · pico {max(niv)} cm</div>
      {svg_event(ev, niv, keep, win)}
      <div class="cf">{tag}</div>
    </div>''')

html = f'''<title>Prévia — corte subida vs. cobrinha</title>
<style>
  :root{{color-scheme:light}}
  body{{margin:0;background:#f6f8f7;color:#0e1f18;font-family:-apple-system,Segoe UI,Roboto,sans-serif}}
  .wrap{{max-width:1080px;margin:0 auto;padding:22px 18px 60px}}
  h1{{font-size:21px;margin:0 0 4px}}
  .sub{{color:#4a5a52;font-size:13.5px;margin:0 0 6px;line-height:1.5}}
  .legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:#33443c;margin:12px 0 20px;align-items:center}}
  .legend i{{display:inline-block;width:22px;height:0;border-top:3px solid;vertical-align:middle;margin-right:6px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
  .card{{background:#fff;border:1px solid #e2e8e5;border-radius:12px;padding:10px 12px 8px;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
  .card.off{{opacity:.62;background:#faf7f2}}
  .chd{{font-size:13px;margin-bottom:2px}}
  .conj{{font-size:11px;color:#6b7a72;background:#eef3f0;border-radius:20px;padding:1px 8px;margin-left:4px}}
  .cf{{margin-top:4px}}
  .tag{{font-size:11.5px;border-radius:20px;padding:2px 9px;display:inline-block}}
  .tag.keep{{background:#e6f2ec;color:#0f6b4a}}
  .tag.drop{{background:#f6ece0;color:#a86a1e}}
  .foot{{margin-top:24px;font-size:12.5px;color:#4a5a52;line-height:1.55;background:#fff;border:1px solid #e2e8e5;border-radius:12px;padding:14px 16px}}
</style>
<div class="wrap">
  <h1>Corte da subida — prévia</h1>
  <p class="sub">Nível em Santa Tereza (86472600), evento por evento. Mantém <b>um bloco contíguo</b>: a subida
  desde o começo (mesmo abaixo de 5 m) até o pico, cortando quando o nível cai abaixo de 5 m pela primeira vez
  depois do pico. Todo o "sobe-e-desce dos 5 m" do final sai.</p>
  <div class="legend">
    <span><i style="border-color:#0f6b4a"></i>subida mantida (treina a rede)</span>
    <span><i style="border-color:#b8bfc7"></i>descartado (final / recessão)</span>
    <span><i style="border-color:#c9a227;border-top-style:dashed"></i>referência 5 m</span>
    <span><b style="color:#c0392b">●</b> pico</span>
  </div>
  <div class="grid">{"".join(cards)}</div>
  <div class="foot">
    <b>Critério:</b> em cada evento, acha o <b>pico</b>; mantém desde o <b>início da subida</b> (mesmo abaixo de 5 m)
    até o primeiro momento em que o nível cai abaixo de 5 m depois do pico; descarta o resto (o final que fica
    subindo e descendo dos 5 m). Eventos que nunca passam de 5 m (14, 18) ou só um espetinho (7) saem inteiros.
    Nesta amostra (12h-ALT C0065): <b>{kept_tot} de {tot} mantidas ({100*kept_tot/tot:.0f}%)</b>.
    <br><br>Olha os eventos 3 e 4 (que você apontou) e me diz se o início da subida está pegando certo.
  </div>
</div>'''
open('preview_corte.html', 'w').write(html)
print('ok', tot, kept_tot)
