# -*- coding: utf-8 -*-
"""R65 (19/10/2026) — 📞 Televendas: duas sub-abas novas no formato do deck "Relatório Saray WhatsApp", portadas do protótipo
`proto_televendas_v2.py` (decisão do Álex, 19/10: "o protótipo está ok e pode ser adicionado como duas novas sub-abas").

  📊 9 · Fechamento WhatsApp   — painel de texto (narrativa, pontos de atenção, observações do analista, série dos últimos 4 meses)
                                 + SVG do funil Tickets → Oportunidades → Usuários únicos sem SAC → Qualificados → Lia × Humano → Vendas
                                 (desvios SAC / sem qualificação em âmbar) + 2 mini-gráficos estilo A.
  ↔️ 10 · WhatsApp mês a mês    — bullets valor × valor com chip de variação (% ou p.p., cor pela direção boa) + SVG dos dois funis lado a lado.

Fonte: só `alex_tv_dash_mes · s7_talkerchat` (já carregado em `_tvd_m`); nenhuma query nova. Grão SEMPRE mensal (mês de fechamento),
independentemente do grão da aba: o mês padrão é o último mês fechado dentro do período dos Controles Globais; um selectbox na própria
sub-aba permite trocar o mês e o mês de comparação. Réguas: Vendas Humano = `nv_tv_humano` (todos os IDPVs humanos, R58) com a fatia
`nv_tv_wpp` ("pelo IDPV WhatsApp" = o "Vendas Humano" do deck); Voz = humano − WhatsApp; Total = Lia + humano. Unidade explícita em
cada degrau (Ticket · Usuário único (telefone) · Venda (CTN)).

Idempotente (marker '📊 9 · Fechamento WhatsApp'). Grava num temporário, compila e só então substitui o app.py.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r65_tv_v2_whatsapp.py
"""
import sys
import pathlib
import py_compile
from _patchlib import read_app, write_app, APP

text, bom, crlf = read_app()
MARKER = "📊 9 · Fechamento WhatsApp"
if MARKER in text:
    print("  = R65 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# ---------------------------------------------------------------------------------------------------------------
# 1) lista de sub-abas da 📞
# ---------------------------------------------------------------------------------------------------------------
replace_once('''                        "📏 7 · Três réguas", "🔀 8 · Grupos A–D"])''',
             '''                        "📏 7 · Três réguas", "🔀 8 · Grupos A–D",
                        "📊 9 · Fechamento WhatsApp", "↔️ 10 · WhatsApp mês a mês"])''',
             "1) st.tabs da 📞 · duas sub-abas novas")

# ---------------------------------------------------------------------------------------------------------------
# 2) bloco das sub-abas 9 e 10 — entra no fim da função _aba_tab6 (depois da sub-aba 5, antes do bloco da TAB 7 APP)
# ---------------------------------------------------------------------------------------------------------------
BLOCO = r'''
    # =================================================================
    # 9 · FECHAMENTO WHATSAPP e 10 · WHATSAPP MÊS A MÊS (R65, 19/10/2026) — formato do deck "Relatório Saray WhatsApp",
    # portado de proto_televendas_v2.py. Só alex_tv_dash_mes · s7_talkerchat (grão mensal, mês de fechamento).
    # =================================================================
    _W2_GREENS = ['#166534', '#2e8a4f', '#57a86f', '#8cc79e', '#c8e3cf']
    _W2_AMBER, _W2_AMBER_BG = '#b45309', '#fff7ed'
    _W2_INK, _W2_MUTED, _W2_LINE = '#0f172a', '#64748b', '#e2e8f0'
    _W2_FONT = "Inter, 'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif"
    _W2_MESES_PT = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro',
                    'Novembro', 'Dezembro']
    _W2_MESES_AB = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

    def _w2_fmt(n):
        if n is None or (isinstance(n, float) and pd.isna(n)):
            return "—"
        return f"{int(round(n)):,}".replace(",", ".")

    def _w2_pct(a, b, nd=0):
        if a is None or b is None or b <= 0:
            return "—"
        return f"{a / b * 100:.{nd}f}%".replace(".", ",")

    def _w2_ratio(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    def _w2_m_ab(ts):
        return f"{_W2_MESES_AB[ts.month]}/{ts.year % 100:02d}"

    def _w2_m_nome(ts):
        return _W2_MESES_PT[ts.month]

    _w2_s7 = _tvd_m[_tvd_m['secao'] == 's7_talkerchat'] if not _tvd_m.empty else _tvd_m
    _w2_piv = (_w2_s7.pivot_table(index='mes', columns='metrica', values='valor', aggfunc='sum')
               if not _w2_s7.empty else pd.DataFrame())

    def _w2_val(mes, metrica):
        try:
            v = _w2_piv.loc[mes, metrica]
        except KeyError:
            return None
        return None if pd.isna(v) else float(v)

    def _w2_calc(mes):
        """Todos os degraus do funil do deck para um mês, a partir do S7. None quando a métrica não existe."""
        g = lambda k: _w2_val(mes, k)
        r = dict(mes=mes)
        r['tickets'] = g('tickets')
        r['tickets_sac'] = g('tickets_sac')
        r['oportunidades'] = g('tickets_sem_sac')
        r['usuarios'] = g('leads')
        r['usuarios_sem_sac'] = g('leads_sem_sac')
        r['qualificados'] = g('qualif_nao_cliente')
        r['transbordo'] = g('qualif_humano')
        r['sem_qualif'] = (r['usuarios_sem_sac'] - r['qualificados']) if None not in (r['usuarios_sem_sac'], r['qualificados']) else None
        r['lia'] = (r['qualificados'] - r['transbordo']) if None not in (r['qualificados'], r['transbordo']) else None
        r['vendas_lia'] = g('nv_lia')
        r['vendas_humano'] = g('nv_tv_humano')            # todos os IDPVs humanos de Televendas (telefone + WhatsApp), bots fora — R58
        r['vendas_wpp'] = g('nv_tv_wpp')                  # └ fatia: IDPV "… ATENDIMENTO WHATSAPP" (= "Vendas Humano" do deck)
        r['vendas_tv'] = g('nv_tv')
        r['vendas_outros_bots'] = g('nv_bots_outros') or 0.0
        r['vendas_voz'] = (r['vendas_humano'] - r['vendas_wpp']) if None not in (r['vendas_humano'], r['vendas_wpp']) else None
        r['vendas_total'] = (r['vendas_lia'] + r['vendas_humano']) if None not in (r['vendas_lia'], r['vendas_humano']) else None
        r['conv_lia'] = _w2_ratio(r['vendas_lia'], r['lia'])
        r['conv_humano'] = _w2_ratio(r['vendas_humano'], r['transbordo'])
        r['conv_humano_wpp'] = _w2_ratio(r['vendas_wpp'], r['transbordo'])
        r['p_wpp_humano'] = _w2_ratio(r['vendas_wpp'], r['vendas_humano'])
        r['p_sac'] = _w2_ratio(r['tickets_sac'], r['tickets'])
        r['p_sem_qualif'] = _w2_ratio(r['sem_qualif'], r['usuarios_sem_sac'])
        r['p_transbordo'] = _w2_ratio(r['transbordo'], r['qualificados'])
        return r

    _w2_meses = [m for m in sorted(_w2_piv.index) if (_w2_val(m, 'tickets') or 0) > 1000] if not _w2_piv.empty else []
    _w2_mes_corrente = pd.Timestamp(reference_date.year, reference_date.month, 1)

    # --- SVG: funil do mês (slide 1) ---
    def _w2_txt(x, y, s, size=12, w=400, fill=_W2_INK, anchor='middle', extra=''):
        return (f"<text x='{x}' y='{y}' font-size='{size}' font-weight='{w}' fill='{fill}' text-anchor='{anchor}' "
                f"font-family=\"{_W2_FONT}\" {extra}>{s}</text>")

    def _w2_seg(y0, y1, w0, w1, color, cx=380):
        return (f"<path d='M{cx - w0 / 2},{y0} L{cx + w0 / 2},{y0} L{cx + w1 / 2},{y1} L{cx - w1 / 2},{y1} Z' "
                f"fill='{color}' stroke='#ffffff' stroke-width='2'/>")

    def _w2_box(x, y, w, h, fill, stroke, r=10, sw=1.5, dash=''):
        return (f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{r}' fill='{fill}' stroke='{stroke}' "
                f"stroke-width='{sw}' {('stroke-dasharray=' + chr(39) + dash + chr(39)) if dash else ''}/>")

    def _w2_arrow(x0, y0, x1, y1, color, sw=2.5, curve=None):
        d = f"M{x0},{y0} L{x1},{y1}" if curve is None else f"M{x0},{y0} Q{curve[0]},{curve[1]} {x1},{y1}"
        return f"<path d='{d}' stroke='{color}' stroke-width='{sw}' fill='none' marker-end='url(#w2ah-{color.strip('#')})'/>"

    def _w2_defs(colors):
        return "<defs>" + "".join(
            f"<marker id='w2ah-{c.strip('#')}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
            f"<path d='M0,0 L10,5 L0,10 Z' fill='{c}'/></marker>" for c in colors) + "</defs>"

    def _w2_svg_funil(r):
        G, AMB, AMB_BG, INK, MUT = _W2_GREENS, _W2_AMBER, _W2_AMBER_BG, _W2_INK, _W2_MUTED
        cx, W, H = 390, 760, 952
        s = [f"<svg viewBox='0 0 {W} {H}' width='100%' xmlns='http://www.w3.org/2000/svg' style='font-family:{_W2_FONT};'>",
             _w2_defs([AMB, G[1], G[0], '#94a3b8'])]
        seg = [  # (y0, y1, w0, w1, cor, título, valor, legenda-unidade, texto-%)
            (22, 118, 420, 372, G[0], 'VOLUME TOTAL DE TICKETS', r['tickets'], 'Ticket · Talkerchat, todas as filas', ''),
            (126, 222, 364, 316, G[1], 'OPORTUNIDADES COMERCIAIS', r['oportunidades'], 'Ticket fora do SAC',
             f"{_w2_pct(r['oportunidades'], r['tickets'])} dos tickets"),
            (230, 318, 308, 262, G[2], 'USUÁRIOS ÚNICOS SEM SAC', r['usuarios_sem_sac'], 'Usuário único (telefone) · unidade muda aqui',
             f"de {_w2_fmt(r['usuarios'])} usuários no mês"),
            (326, 418, 254, 206, G[3], 'QUALIFICADOS ÚNICOS', r['qualificados'], 'CPF validado, não cliente (processáveis)',
             f"{_w2_pct(r['qualificados'], r['usuarios_sem_sac'])} dos usuários sem SAC"),
        ]
        for i, (y0, y1, w0, w1, c, t, v, u, p) in enumerate(seg):
            s.append(_w2_seg(y0, y1, w0, w1, c))
            fg = '#ffffff' if i < 3 else INK
            s.append(_w2_txt(cx, y0 + 24, t, 11.5, 800, fg, extra="letter-spacing='.6'"))
            s.append(_w2_txt(cx, y0 + 54, _w2_fmt(v), 27, 800, fg))
            s.append(_w2_txt(cx, y0 + 72, u, 10, 500, fg if i < 3 else MUT))
            if p:
                s.append(_w2_txt(cx, y0 + 87, p, 10.5, 700, fg if i < 3 else G[0]))
        # desvio esquerdo: Tickets SAC
        s.append(_w2_arrow(cx - 200, 70, 172, 70, AMB, 3))
        s.append(_w2_box(8, 26, 162, 100, AMB_BG, AMB))
        s.append(_w2_txt(89, 44, 'DESVIO', 9.5, 700, AMB, extra="letter-spacing='.8'"))
        s.append(_w2_txt(89, 62, 'TICKETS SAC', 11, 800, INK))
        s.append(_w2_txt(89, 86, _w2_fmt(r['tickets_sac']), 21, 800, AMB))
        s.append(_w2_txt(89, 101, f"{_w2_pct(r['tickets_sac'], r['tickets'])} dos tickets", 9.5, 600, INK))
        s.append(_w2_txt(89, 114, 'já cliente / transferido ao SAC', 8.5, 500, MUT))
        # desvio direito: sem qualificação
        s.append(_w2_arrow(cx + 146, 274, 588, 274, AMB, 3))
        s.append(_w2_box(590, 226, 162, 106, AMB_BG, AMB))
        s.append(_w2_txt(671, 244, 'DESVIO', 9.5, 700, AMB, extra="letter-spacing='.8'"))
        s.append(_w2_txt(671, 262, 'SEM QUALIFICAÇÃO', 11, 800, INK))
        s.append(_w2_txt(671, 286, _w2_fmt(r['sem_qualif']), 21, 800, AMB))
        s.append(_w2_txt(671, 301, f"{_w2_pct(r['sem_qualif'], r['usuarios_sem_sac'])} dos usuários sem SAC", 9.5, 600, INK))
        s.append(_w2_txt(671, 314, 'sem CPF validado: sem interação,', 8.5, 500, MUT))
        s.append(_w2_txt(671, 325, 'fim de expediente, janela encerrada…', 8.5, 500, MUT))
        # ramos Lia × Humano
        yb = 470
        s.append(_w2_arrow(cx - 60, 420, 200, yb - 6, G[1], 3, curve=(cx - 120, 452)))
        s.append(_w2_arrow(cx + 60, 420, 560, yb - 6, G[0], 3, curve=(cx + 120, 452)))
        cols = [
            (200, G[1], '🤖 CANAL LIA (bot)', 'sem transbordo', 'TRABALHADO PELA LIA', r['lia'],
             f"{_w2_pct(r['lia'], r['qualificados'])} dos qualificados únicos", 'VENDAS LIA (CTN)', r['vendas_lia'],
             'NOMINAL por IDPV LIA - GT7 · filiação no mês'),
            (560, G[0], '🧑‍💼 CANAL HUMANO', 'transbordo ao atendente', 'TRANSBORDO HUMANO', r['transbordo'],
             f"{_w2_pct(r['transbordo'], r['qualificados'])} dos qualificados únicos", 'VENDAS HUMANO (CTN)', r['vendas_humano'],
             'NOMINAL por IDPV de operador humano (bots fora) · no mês'),
        ]
        for (x, c, hd, sub, e1, v1, n1, e2, v2, n2) in cols:
            s.append(_w2_txt(x, yb + 14, hd, 12.5, 800, c))
            s.append(_w2_txt(x, yb + 29, sub, 9.5, 500, MUT))
            s.append(_w2_box(x - 125, yb + 40, 250, 70, '#ffffff', c, sw=2))
            s.append(_w2_txt(x, yb + 60, e1, 10.5, 800, INK, extra="letter-spacing='.5'"))
            s.append(_w2_txt(x, yb + 88, _w2_fmt(v1), 24, 800, c))
            s.append(_w2_txt(x, yb + 103, n1, 9.5, 500, MUT))
            s.append(_w2_arrow(x, yb + 112, x, yb + 134, c, 2.5))
            s.append(_w2_box(x - 125, yb + 136, 250, 70, c, c, sw=2))
            s.append(_w2_txt(x, yb + 156, e2, 10.5, 800, '#ffffff', extra="letter-spacing='.5'"))
            s.append(_w2_txt(x, yb + 184, _w2_fmt(v2), 24, 800, '#ffffff'))
            s.append(_w2_txt(x, yb + 199, n2, 9, 500, '#e5f0e8'))
        xh = 560   # degrau extra do ramo humano: fatia pelo IDPV WhatsApp (o resto é Voz)
        s.append(_w2_arrow(xh, yb + 208, xh, yb + 226, G[0], 2.5))
        s.append(_w2_box(xh - 125, yb + 228, 250, 66, '#f0fdf4', G[0], r=8, sw=1.5, dash='4 3'))
        s.append(_w2_txt(xh, yb + 245, '└ PELO IDPV WHATSAPP DO ATENDENTE', 9.5, 800, INK, extra="letter-spacing='.4'"))
        s.append(_w2_txt(xh, yb + 267, _w2_fmt(r['vendas_wpp']), 19, 800, G[0]))
        s.append(_w2_txt(xh, yb + 279, f"{_w2_pct(r['vendas_wpp'], r['vendas_humano'])} das vendas humano", 8.5, 600, INK))
        s.append(_w2_txt(xh, yb + 288, f"o resto é Voz (IDPV telefone): {_w2_fmt(r['vendas_voz'])}", 8, 500, MUT))
        yp = yb + 300   # pílulas de conversão
        s.append(_w2_box(200 - 95, yp, 190, 30, '#ecfdf5', G[0], r=15, sw=1.5))
        s.append(_w2_txt(200, yp + 20, f"CONVERSÃO LIA: {_w2_pct(r['conv_lia'] * 100, 100, 1) if r['conv_lia'] is not None else '—'}", 12, 800, G[0]))
        s.append(_w2_box(xh - 130, yp, 260, 30, '#ecfdf5', G[0], r=15, sw=1.5))
        s.append(_w2_txt(xh, yp + 20, f"CONVERSÃO HUMANO: {_w2_pct(r['conv_humano'] * 100, 100, 1) if r['conv_humano'] is not None else '—'}"
                                      f" · WhatsApp {_w2_pct(r['conv_humano_wpp'] * 100, 100, 1) if r['conv_humano_wpp'] is not None else '—'}",
                         10.5, 800, G[0]))
        yt = yp + 54   # total
        s.append(_w2_arrow(200, yp + 32, cx - 90, yt + 6, G[1], 2.5, curve=(200, yt - 6)))
        s.append(_w2_arrow(xh, yp + 32, cx + 90, yt + 6, G[0], 2.5, curve=(xh, yt - 6)))
        s.append(_w2_box(cx - 170, yt, 340, 92, G[0], G[0], r=14))
        s.append(_w2_txt(cx, yt + 22, '🏆 TOTAL TELEVENDAS (CTN) · LIA + HUMANO', 11, 800, '#ffffff', extra="letter-spacing='.5'"))
        s.append(_w2_txt(cx, yt + 56, _w2_fmt(r['vendas_total']), 30, 800, '#ffffff'))
        s.append(_w2_txt(cx, yt + 78, f"Lia {_w2_fmt(r['vendas_lia'])} · Humano {_w2_fmt(r['vendas_humano'])} (WhatsApp {_w2_fmt(r['vendas_wpp'])} · Voz {_w2_fmt(r['vendas_voz'])})",
                         11, 600, '#e5f0e8'))
        s.append(_w2_txt(cx, yt + 112, f"Televendas total no CTN (tipo Televendas, todos os IDPVs): {_w2_fmt(r['vendas_tv'])}"
                                       + (f" · outros bots (Nora/Cris): {_w2_fmt(r['vendas_outros_bots'])}" if r['vendas_outros_bots'] else ""),
                         9.5, 500, MUT))
        s.append("</svg>")
        return "".join(s)

    # --- SVG: mês vs mês anterior (slide 2) ---
    def _w2_delta(cur, prev, good='up', pp=False):
        """(texto, cor-fundo, cor-texto). pp=True: diferença em pontos percentuais (taxas)."""
        if cur is None or prev is None:
            return ("—", '#f1f5f9', '#475569')
        if pp:
            d = (cur - prev) * 100
            txt = f"{d:+.1f} pp".replace('.', ',')
        else:
            if prev <= 0:
                return ("—", '#f1f5f9', '#475569')
            d = (cur - prev) / prev * 100
            txt = f"{d:+.0f}%"
        if abs(d) < 0.05:
            return (txt, '#f1f5f9', '#475569')
        better = (d > 0) if good == 'up' else (d < 0)
        return (txt, '#dcfce7' if better else '#fee2e2', '#15803d' if better else '#b91c1c')

    def _w2_svg_comp(a, b):
        G, AMB, AMB_BG, INK, MUT = _W2_GREENS, _W2_AMBER, _W2_AMBER_BG, _W2_INK, _W2_MUTED
        W, H = 760, 872
        s = [f"<svg viewBox='0 0 {W} {H}' width='100%' xmlns='http://www.w3.org/2000/svg' style='font-family:{_W2_FONT};'>",
             _w2_defs(['#94a3b8'])]
        xl, xr, xc = 170, 590, 380
        s.append(_w2_txt(xl, 24, _w2_m_nome(b['mes']).upper() + f" {b['mes'].year}", 15, 800, MUT, extra="letter-spacing='1'"))
        s.append(_w2_txt(xr, 24, _w2_m_nome(a['mes']).upper() + f" {a['mes'].year}", 15, 800, G[0], extra="letter-spacing='1'"))
        s.append(_w2_txt(xc, 24, 'variação', 10.5, 600, MUT))
        rows = [  # (rótulo, chave, unidade, good, pp, largura relativa)
            ('Total de tickets', 'tickets', 'Ticket', 'up', False, 1.00),
            ('Tickets SAC (desvio)', 'tickets_sac', 'Ticket', 'down', False, 0.92),
            ('Oportunidades comerciais', 'oportunidades', 'Ticket fora do SAC', 'up', False, 0.86),
            ('Usuários únicos sem SAC', 'usuarios_sem_sac', 'Usuário único', 'up', False, 0.80),
            ('Sem qualificação (desvio)', 'sem_qualif', 'Usuário único', 'down', False, 0.74),
            ('Qualificados únicos', 'qualificados', 'CPF validado, não cliente', 'up', False, 0.68),
        ]
        y = 40
        for (lbl, k, un, good, pp, rel) in rows:
            amber = 'desvio' in lbl
            for x, r, dark in ((xl, b, False), (xr, a, True)):
                w = 240 * rel
                fill = AMB_BG if amber else ('#ffffff' if dark else '#f8fafc')
                stroke = AMB if amber else (G[0] if dark else '#cbd5e1')
                s.append(_w2_box(x - w / 2, y, w, 58, fill, stroke, r=8, sw=1.5))
                s.append(_w2_txt(x, y + 17, lbl, 10.5, 800, AMB if amber else INK))
                s.append(_w2_txt(x, y + 40, _w2_fmt(r[k]), 20, 800, AMB if amber else (G[0] if dark else INK)))
                s.append(_w2_txt(x, y + 52, un, 8.5, 500, MUT))
            t, bg, fg = _w2_delta(a[k], b[k], good, pp)
            s.append(_w2_arrow(xl + 122, y + 29, xc - 62, y + 29, '#94a3b8', 1.5))
            s.append(_w2_arrow(xr - 122, y + 29, xc + 62, y + 29, '#94a3b8', 1.5))
            s.append(_w2_box(xc - 58, y + 14, 116, 30, bg, bg, r=15))
            s.append(_w2_txt(xc, y + 34, t, 13, 800, fg))
            y += 70
        y += 6
        s.append(_w2_txt(xl, y + 12, '🤖 Lia (sem transbordo)      🧑‍💼 Humano (transbordo)', 10, 700, MUT))
        s.append(_w2_txt(xr, y + 12, '🤖 Lia (sem transbordo)      🧑‍💼 Humano (transbordo)', 10, 700, MUT))
        y += 20
        pares = [  # (rótulo-lia, chave-lia, rótulo-humano, chave-humano, pp) — chave-lia None = só o lado humano (degrau extra)
            ('Trabalhado pela Lia', 'lia', 'Transbordo humano', 'transbordo', False),
            ('Vendas Lia (CTN)', 'vendas_lia', 'Vendas Humano (CTN)', 'vendas_humano', False),
            (None, None, '└ pelo IDPV WhatsApp', 'vendas_wpp', False),
            ('Conversão Lia', 'conv_lia', 'Conversão Humano', 'conv_humano', True),
            (None, None, '└ Conversão · WhatsApp', 'conv_humano_wpp', True),
        ]
        for (l1, k1, l2, k2, pp) in pares:
            extra = k1 is None
            h = 44 if extra else 56
            for x, r, dark in ((xl, b, False), (xr, a, True)):
                for j, (lbl, k) in enumerate(((l1, k1), (l2, k2))):
                    if k is None:
                        continue
                    bx = x - 125 + j * 130
                    c = G[1] if j == 0 else G[0]
                    s.append(_w2_box(bx, y, 120, h, '#ecfdf5' if pp else ('#f0fdf4' if extra else '#ffffff'),
                                     c if dark else '#cbd5e1', r=8, sw=1.5, dash='4 3' if extra else ''))
                    s.append(_w2_txt(bx + 60, y + 15, lbl, 9 if extra else 9.5, 800, INK))
                    vtxt = (_w2_pct(r[k] * 100, 100, 1) if (pp and r[k] is not None) else ('—' if pp else _w2_fmt(r[k])))
                    s.append(_w2_txt(bx + 60, y + (34 if extra else 41), vtxt, 15 if extra else 18, 800, c if dark else INK))
            for j, k in enumerate((k1, k2)):
                if k is None:
                    continue
                t, bg, fg = _w2_delta(a[k], b[k], 'up', pp)
                cy = (y + 11) if extra else (y + 14 + j * 24)
                s.append(_w2_box(xc - 58, cy, 116, 22, bg, bg, r=11))
                s.append(_w2_txt(xc, cy + 15, ('Lia ' if j == 0 else ('WhatsApp ' if extra else 'Humano ')) + t, 10.5, 800, fg))
            y += (52 if extra else 66)
        y += 8
        for x, r, dark in ((xl, b, False), (xr, a, True)):
            s.append(_w2_box(x - 125, y, 250, 64, G[0] if dark else '#f1f5f9', G[0] if dark else '#cbd5e1', r=12))
            s.append(_w2_txt(x, y + 18, '🏆 TOTAL TELEVENDAS (CTN) — LIA + HUMANO', 10, 800, '#ffffff' if dark else INK))
            s.append(_w2_txt(x, y + 44, _w2_fmt(r['vendas_total']), 24, 800, '#ffffff' if dark else INK))
            s.append(_w2_txt(x, y + 57, f"WhatsApp {_w2_fmt(r['vendas_lia'] + r['vendas_wpp']) if None not in (r['vendas_lia'], r['vendas_wpp']) else '—'}"
                                        f" · Voz {_w2_fmt(r['vendas_voz'])}", 8.5, 500, '#e5f0e8' if dark else MUT))
        t, bg, fg = _w2_delta(a['vendas_total'], b['vendas_total'], 'up')
        s.append(_w2_box(xc - 58, y + 17, 116, 30, bg, bg, r=15))
        s.append(_w2_txt(xc, y + 37, t, 13, 800, fg))
        s.append("</svg>")
        return "".join(s)

    # --- painel de texto ---
    def _w2_p(txt, color=_W2_INK, bold=False, size=13.5):
        st.markdown(f"<div style='font-size:{size}px;color:{color};line-height:1.5;margin:0 0 10px;"
                    f"font-weight:{700 if bold else 400};'>{txt}</div>", unsafe_allow_html=True)

    def _w2_media_anterior(mes, chave_num, chave_den, n=3):
        ant = [m for m in _w2_meses if m < mes][-n:]
        vals = [_w2_ratio(_w2_calc(m)[chave_num], _w2_calc(m)[chave_den]) for m in ant]
        vals = [v for v in vals if v is not None]
        return (sum(vals) / len(vals), len(ant)) if vals else (None, 0)

    def _w2_obs_bloco(obs):
        if obs and obs.strip():
            st.markdown(f"<div style='font-size:12px;font-weight:800;color:{_W2_INK};text-decoration:underline;margin:8px 0 6px;'>Observações</div>",
                        unsafe_allow_html=True)
            for ln in [x.strip() for x in obs.splitlines() if x.strip()]:
                _w2_p("– " + ln, size=12.5)

    def _w2_painel_mes(r, obs):
        G, INK, MUT, LINE = _W2_GREENS, _W2_INK, _W2_MUTED, _W2_LINE
        tv = r['vendas_tv']
        if tv:
            p_lia, p_hum, p_wpp, p_voz = (_w2_pct(r['vendas_lia'], tv), _w2_pct(r['vendas_humano'], tv),
                                          _w2_pct(r['vendas_wpp'], tv), _w2_pct(r['vendas_voz'], tv))
            _w2_p(f"O resultado de vendas no canal <b>Televendas</b> (Lia + operadores humanos) foi de <b>{_w2_fmt(tv)} vendas (CTN)</b> em "
                  f"{_w2_m_nome(r['mes']).lower()}: <b>{p_lia}</b> pelo bot Lia e <b>{p_hum}</b> pelos operadores humanos — destes, "
                  f"<b>{p_wpp}</b> pelo IDPV WhatsApp e <b>{p_voz}</b> pela Voz (IDPV telefone)"
                  + (f"; outros bots: {_w2_fmt(r['vendas_outros_bots'])}" if r['vendas_outros_bots'] else "") + ".")
        if r['conv_lia'] is not None:
            _w2_p(f"A conversão da Lia ({_w2_pct(r['conv_lia'] * 100, 100, 1)}) é lida sobre os qualificados que ficaram com o bot — "
                  f"desconsidera o volume transbordado para o humano ({_w2_fmt(r['transbordo'])}, "
                  f"{_w2_pct(r['transbordo'], r['qualificados'])} dos qualificados únicos). A conversão humana "
                  f"({_w2_pct(r['conv_humano'] * 100, 100, 1) if r['conv_humano'] is not None else '—'}) usa todos os IDPVs humanos — o IDPV do operador "
                  f"também recebe vendas fechadas por telefone, por isso o degrau \"pelo IDPV WhatsApp\" "
                  f"({_w2_pct(r['conv_humano_wpp'] * 100, 100, 1) if r['conv_humano_wpp'] is not None else '—'}) é a leitura estrita do canal.",
                  MUT, size=12.5)
        st.markdown(f"<div style='font-size:12px;font-weight:800;color:{INK};text-decoration:underline;margin:4px 0 6px;'>Pontos de atenção</div>",
                    unsafe_allow_html=True)
        for (lbl, num, den, bom) in (("Tickets transferidos para o SAC", 'tickets_sac', 'tickets', 'down'),
                                     ("Tickets não qualificados (sem CPF validado)", 'sem_qualif', 'usuarios_sem_sac', 'down'),
                                     ("Transbordo para o humano", 'transbordo', 'qualificados', 'up')):
            cur = _w2_ratio(r[num], r[den])
            med, n = _w2_media_anterior(r['mes'], num, den)
            if cur is None:
                continue
            if med is None:
                _w2_p(f"<b>{lbl}</b>: {_w2_pct(cur * 100, 100)} do volume.", size=12.5)
                continue
            d = (cur - med) * 100
            piorou = (d > 0) if bom == 'down' else (d < 0)
            cor = '#b91c1c' if (piorou and abs(d) >= 3) else (G[0] if abs(d) >= 3 else INK)
            verbo = 'aumento' if d > 0 else 'queda'
            _w2_p(f"<b>{lbl}</b>: <b>{_w2_pct(cur * 100, 100)}</b> em {_w2_m_ab(r['mes'])} — {verbo} de {abs(d):.0f} p.p. sobre a média "
                  f"dos {n} meses anteriores ({_w2_pct(med * 100, 100)}).", cor, bold=False, size=12.5)
        _w2_obs_bloco(obs)
        meses4 = [m for m in _w2_meses if m <= r['mes']][-4:]
        linhas = [('Transbordo humano (% dos qualificados)', 'p_transbordo'), ('Tickets SAC (% dos tickets)', 'p_sac'),
                  ('Sem qualificação (% dos usuários sem SAC)', 'p_sem_qualif'), ('Conversão Lia', 'conv_lia'),
                  ('Conversão Humano (todos os IDPVs)', 'conv_humano'), ('└ Conversão · IDPV WhatsApp', 'conv_humano_wpp'),
                  ('└ WhatsApp nas vendas humano', 'p_wpp_humano')]
        _c = {m: _w2_calc(m) for m in meses4}
        th = "".join(f"<th style='text-align:right;padding:5px 8px;border-bottom:1.5px solid {INK};font-weight:800;"
                     f"color:{G[0] if m == r['mes'] else INK};'>{_w2_m_ab(m)}</th>" for m in meses4)
        tr = ""
        for lbl, k in linhas:
            tds = "".join(f"<td style='text-align:right;padding:5px 8px;border-bottom:1px solid {LINE};"
                          f"font-weight:{800 if m == r['mes'] else 500};'>"
                          f"{_w2_pct(_c[m][k] * 100, 100) if _c[m][k] is not None else '—'}</td>" for m in meses4)
            tr += f"<tr><td style='padding:5px 8px;border-bottom:1px solid {LINE};color:{INK};'>{lbl}</td>{tds}</tr>"
        st.markdown(f"<div style='font-size:11px;color:{MUT};margin-top:6px;'>Série mensal (mês cheio, com fins de semana e feriados — "
                    f"a tabela de transferência do deck usa só dias úteis):</div>"
                    f"<table style='width:100%;border-collapse:collapse;font-size:12px;margin-top:4px;'>"
                    f"<tr><th></th>{th}</tr>{tr}</table>", unsafe_allow_html=True)

    def _w2_painel_comp(a, b, obs):
        def linha(lbl, k, good='up', pp=False, un=''):
            t, _, fg = _w2_delta(a[k], b[k], good, pp)
            va = _w2_pct(a[k] * 100, 100, 1) if pp and a[k] is not None else _w2_fmt(a[k])
            vb = _w2_pct(b[k] * 100, 100, 1) if pp and b[k] is not None else _w2_fmt(b[k])
            _w2_p(f"– <b>{lbl}</b>: {va} em {_w2_m_ab(a['mes'])} vs {vb} em {_w2_m_ab(b['mes'])} "
                  f"(<span style='color:{fg};font-weight:800;'>{t}</span>){(' · ' + un) if un else ''}", size=12.5)
        _w2_p(f"Os resultados do canal WhatsApp — {_w2_m_nome(a['mes']).lower()} vs {_w2_m_nome(b['mes']).lower()}:", bold=True)
        linha("Vendas totais Televendas (CTN)", 'vendas_total', un='Lia + todos os IDPVs humanos')
        linha("Vendas Lia", 'vendas_lia')
        linha("Vendas Humano (todos os IDPVs humanos)", 'vendas_humano')
        linha("└ pelo IDPV WhatsApp", 'vendas_wpp')
        linha("Conversão Lia", 'conv_lia', pp=True)
        linha("Conversão Humano", 'conv_humano', pp=True)
        linha("└ Conversão · IDPV WhatsApp", 'conv_humano_wpp', pp=True)
        linha("Tickets transferidos para o SAC (% dos tickets)", 'p_sac', good='down', pp=True)
        linha("Sem qualificação (% dos usuários sem SAC)", 'p_sem_qualif', good='down', pp=True)
        linha("Transbordo humano (% dos qualificados)", 'p_transbordo', pp=True)
        linha("Total de tickets", 'tickets')
        linha("Oportunidades comerciais", 'oportunidades')
        _w2_obs_bloco(obs)

    def _w2_mini_bar(labels, values, colors, title, sub):
        _tv_titulo(title, sub, "A")
        _d = pd.DataFrame({'x': labels, 'y': [v if v is not None else 0 for v in values]})
        _d['rotulo'] = [_w2_fmt(v) for v in values]
        fig = px.bar(_d, x='x', y='y', text='rotulo', template='cdt_a' if _CDT_THEME else 'plotly_white')
        fig.update_traces(marker_color=colors, textposition='outside', textfont=dict(size=11, color=_W2_INK),
                          hovertemplate='%{x}: %{y:,.0f}<extra></extra>', cliponaxis=False)
        fig.update_layout(height=210, margin=dict(l=6, r=40, t=14, b=26), showlegend=False, xaxis_title='', yaxis_title='')
        fig.update_yaxes(range=[0, max([v for v in values if v] or [1]) * 1.25], tickfont=dict(size=10))
        st.plotly_chart(fig, use_container_width=True, config=dict(displayModeBar=False))

    def _w2_controles(key):
        """Seletor do mês de fechamento (padrão: último mês fechado dentro do período dos Controles Globais) e do mês de comparação."""
        _cands = [m for m in _w2_meses if m <= _tv_m_fim] or list(_w2_meses)
        _fech = [m for m in _cands if m < _w2_mes_corrente]
        _def = _fech[-1] if _fech else _cands[-1]
        _opts = list(reversed(_w2_meses))
        c1_, c2_ = st.columns([1, 1])
        mes_sel = c1_.selectbox("Mês de fechamento", _opts, index=_opts.index(_def), key=f"{key}_mes",
                                format_func=lambda m: f"{_w2_m_nome(m)} {m.year}",
                                help="Padrão: último mês fechado dentro do período dos Controles Globais. O mês corrente aparece como parcial.")
        _ant = [m for m in _w2_meses if m < mes_sel]
        mes_cmp = c2_.selectbox("Comparar com", list(reversed(_ant)) or [None], key=f"{key}_cmp",
                                format_func=lambda m: f"{_w2_m_nome(m)} {m.year}" if m is not None else "—")
        return mes_sel, mes_cmp

    _w2_regua_md = """
| Degrau | Unidade | Métrica (S7) | Observação |
|---|---|---|---|
| Volume total de tickets | Ticket | `tickets` | todas as filas do Talkerchat no mês |
| Tickets SAC (desvio) | Ticket | `tickets_sac` | motivos 4/174/186/189 (SAC / já cliente) ou fila SAC — R62 |
| Oportunidades comerciais | Ticket | `tickets_sem_sac` | tickets fora do SAC |
| Usuários únicos sem SAC | Usuário único (telefone) | `leads_sem_sac` | a unidade muda de ticket para pessoa aqui |
| Sem qualificação (desvio) | Usuário único | `leads_sem_sac − qualif_nao_cliente` | sem CPF validado: sem interação, fim de expediente, janela encerrada… |
| Qualificados únicos | Usuário único | `qualif_nao_cliente` | CPF lido pelo objeto de contato da API e não cliente (R58/R61) |
| Transbordo humano | Usuário único | `qualif_humano` | qualificados que chegaram a um atendente |
| Trabalhado pela Lia | Usuário único | `qualif_nao_cliente − qualif_humano` | qualificados que ficaram só com o bot |
| Vendas Lia (CTN) | Venda (CTN) | `nv_lia` | NOMINAL, IDPV LIA - GT7, `DT_FILIACAO` no mês |
| Vendas Humano (CTN) | Venda (CTN) | `nv_tv_humano` | **todos os IDPVs de operador humano** de Televendas (telefone + WhatsApp), bots fora — R58 |
| └ pelo IDPV WhatsApp | Venda (CTN) | `nv_tv_wpp` | fatia das vendas humano pelo IDPV "… ATENDIMENTO WHATSAPP" (é o "Vendas Humano" do deck) |
| Voz | Venda (CTN) | `nv_tv_humano − nv_tv_wpp` | IDPV telefone do operador |
| Conversão | % | vendas ÷ etapa de cima do mesmo ramo | humano em duas leituras: todos os IDPVs e só WhatsApp |
| Total | Venda (CTN) | `nv_lia + nv_tv_humano` | = Televendas total (`nv_tv`) menos outros bots |

**Diferença conhecida para o deck (set/26):** o "qualificado" do deck é mais estreito (27,6 k tickets / 27,1 k únicos) do que
`qualif_nao_cliente` (35,7 k usuários). Por isso "Trabalhado pela Lia" aqui é maior e a conversão da Lia sai menor (14,5 % × 24 %).
Tickets, SAC, oportunidades e Vendas Lia batem a ±4 %; o "Vendas Humano" do deck corresponde ao degrau "pelo IDPV WhatsApp", não ao total humano.
A régua por fila (R60, só ≥ out/26) não é usada aqui, para a comparação mês a mês ficar homogênea desde mai/26.
"""

    # =================================================================
    # 9 · FECHAMENTO WHATSAPP
    # =================================================================
    with _tv_tabs[8]:
        if not _w2_meses:
            st.warning("`alex_tv_dash_mes` não tem a seção s7_talkerchat com volume mensal. Rode `gt7 run televendas_dash --arg only=s7`.")
        else:
            _w2_mes, _w2_cmp = _w2_controles("t6_w2a")
            _w2_obs = st.text_area("Observações do analista (entram no painel de texto das duas sub-abas)", height=90, key="t6_w2_obs",
                                   placeholder="Ex.: Ainda não estamos com o Talkerchat integrado ao HubSpot; no volume de vendas podemos ter "
                                               "clientes convertidos vindos da Zenvia…")
            _w2_A = _w2_calc(_w2_mes)
            st.markdown(f"<div style='font-size:24px;font-weight:800;color:{_W2_GREENS[0]};line-height:1.15;margin:4px 0 2px;'>"
                        f"Resultados do WhatsApp — Fechamento {_w2_m_nome(_w2_mes)} {_w2_mes.year}</div>"
                        f"<div style='font-size:12.5px;color:{_W2_MUTED};margin-bottom:10px;'>Canal Televendas · Talkerchat (WhatsApp) × NOMINAL (CTN) · "
                        f"unidade indicada em cada degrau: <b>Ticket</b>, <b>Usuário único (telefone)</b> ou <b>Venda (CTN)</b></div>",
                        unsafe_allow_html=True)
            if _w2_mes >= _w2_mes_corrente:
                st.warning(f"⏳ {_w2_m_nome(_w2_mes)} ainda está em curso — números parciais até a última recarga.")
            _w2_c1, _w2_c2 = st.columns([0.40, 0.60], gap="large")
            with _w2_c1:
                _w2_painel_mes(_w2_A, _w2_obs)
            with _w2_c2:
                st.markdown(f"<div style='border:1px solid {_W2_LINE};border-radius:14px;padding:10px 12px 4px;background:#fff;'>"
                            f"<div style='font-size:13px;font-weight:800;color:{_W2_INK};letter-spacing:.4px;margin:2px 0 4px 8px;'>"
                            f"FUNIL DE VENDAS: DESEMPENHO DE {_w2_m_nome(_w2_mes).upper()}</div>" + _w2_svg_funil(_w2_A) + "</div>",
                            unsafe_allow_html=True)
                _w2_g1, _w2_g2 = st.columns(2)
                with _w2_g1:
                    _w2_mini_bar(['Oportunidades', 'SAC'], [_w2_A['oportunidades'], _w2_A['tickets_sac']], [_W2_GREENS[0], _W2_AMBER],
                                 "Oportunidades vs. SAC", "tickets do mês · fora do SAC × desviados ao SAC")
                with _w2_g2:
                    _w2_mini_bar(['Lia', 'Humano', '└ IDPV WhatsApp'], [_w2_A['vendas_lia'], _w2_A['vendas_humano'], _w2_A['vendas_wpp']],
                                 [_W2_GREENS[1], _W2_GREENS[0], _W2_GREENS[3]],
                                 "Lia vs. Humano — vendas (CTN)", "NOMINAL por IDPV · humano = todos os IDPVs de operador; fatia WhatsApp à parte")
                _tv_fonte("alex_tv_dash_mes · s7_talkerchat (pipeline televendas_dash) · Talkerchat (tickets, filas, CPF do objeto de contato) × NOMINAL_VENDAS por IDPV")
            with st.expander("📐 Réguas deste fechamento (e onde ele difere do deck)"):
                st.markdown(_w2_regua_md)

    # =================================================================
    # 10 · WHATSAPP MÊS A MÊS
    # =================================================================
    with _tv_tabs[9]:
        if not _w2_meses:
            st.warning("`alex_tv_dash_mes` não tem a seção s7_talkerchat com volume mensal. Rode `gt7 run televendas_dash --arg only=s7`.")
        else:
            _w2_mes_b, _w2_cmp_b = _w2_controles("t6_w2b")
            _w2_obs_b = st.session_state.get("t6_w2_obs", "")
            if _w2_cmp_b is None:
                st.info("Não há mês anterior disponível para comparar.")
            else:
                _w2_A2, _w2_B2 = _w2_calc(_w2_mes_b), _w2_calc(_w2_cmp_b)
                st.markdown(f"<div style='font-size:24px;font-weight:800;color:{_W2_GREENS[0]};line-height:1.15;margin:4px 0 2px;'>"
                            f"WhatsApp — {_w2_m_nome(_w2_mes_b)} vs {_w2_m_nome(_w2_cmp_b)}</div>"
                            f"<div style='font-size:12.5px;color:{_W2_MUTED};margin-bottom:10px;'>variação = mês cheio vs mês cheio (sem corte de mesmo trecho) · "
                            f"verde quando anda na direção boa (SAC e sem qualificação: bom quando cai)</div>", unsafe_allow_html=True)
                if _w2_mes_b >= _w2_mes_corrente:
                    st.warning(f"⏳ {_w2_m_nome(_w2_mes_b)} ainda está em curso — comparação com um mês parcial.")
                _w2_d1, _w2_d2 = st.columns([0.40, 0.60], gap="large")
                with _w2_d1:
                    _w2_painel_comp(_w2_A2, _w2_B2, _w2_obs_b)
                with _w2_d2:
                    st.markdown(f"<div style='border:1px solid {_W2_LINE};border-radius:14px;padding:10px 12px 4px;background:#fff;'>"
                                + _w2_svg_comp(_w2_A2, _w2_B2) + "</div>", unsafe_allow_html=True)
                    _tv_fonte("alex_tv_dash_mes · s7_talkerchat · variação = mês cheio vs mês cheio (sem corte de mesmo trecho)")
'''

ANCORA_TAB7 = '''# =====================================================================
# TAB 7: APP — funil (download → cadastro → compra), uso de produtos, freemium'''
replace_once(ANCORA_TAB7, BLOCO.lstrip("\n") + "\n\n" + ANCORA_TAB7, "2) sub-abas 9 e 10 no fim da _aba_tab6")

# ---------------------------------------------------------------------------------------------------------------
# 3) glossário — dois verbetes na seção WhatsApp (Talkerchat)
# ---------------------------------------------------------------------------------------------------------------
replace_once('''    'Lia, Cris, Nora (bots)': dict(sec="WhatsApp (Talkerchat)",''',
             '''    'Fechamento WhatsApp (funil do deck)': dict(sec="WhatsApp (Talkerchat)",
        d="Sub-abas 📞 9 e 10: o funil do mês no formato do Relatório Saray WhatsApp — Tickets → Oportunidades comerciais (fora do SAC) → Usuários únicos sem SAC → Qualificados únicos → ramos Lia (sem transbordo) × Humano (transbordo) → Vendas (CTN) → Total. Desvios em âmbar: Tickets SAC e Sem qualificação. A unidade muda de Ticket para Usuário único (telefone) no 3º degrau e para Venda (CTN) nos ramos.",
        p="Vendas Humano = todos os IDPVs humanos de Televendas (R58); o degrau 'pelo IDPV WhatsApp' é a fatia que o deck chama de 'Vendas Humano'. Voz = humano − WhatsApp. Mês cheio, com fins de semana (o deck usa dias úteis na tabela de transferência).",
        o="alex_tv_dash_mes · s7_talkerchat (Talkerchat × NOMINAL por IDPV)", a="📞",
        s=["Fechamento WhatsApp", "Oportunidades comerciais", "Sem qualificação", "Trabalhado pela Lia", "Transbordo humano", "Voz", "funil do deck"]),
    'Lia, Cris, Nora (bots)': dict(sec="WhatsApp (Talkerchat)",''',
             "3) glossário · verbete Fechamento WhatsApp")

# ---------------------------------------------------------------------------------------------------------------
# grava num temporário, compila, só então substitui
# ---------------------------------------------------------------------------------------------------------------
tmp = APP.with_name("app_r65_tmp.py")
tmp.write_bytes(bom + (text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
try:
    py_compile.compile(str(tmp), doraise=True)
except py_compile.PyCompileError as e:
    print("ERRO: o app patchado não compila:", str(e)[:800])
    sys.exit(1)
write_app(text, bom, crlf)
tmp.unlink()
print("R65 aplicada")
