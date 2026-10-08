"""R63 (08/10/2026) — 📞 Televendas: (1) "Vendas (CTN) atribuídas" = NOMINAL tipo Televendas SEM bots (IDPV humano) com filiação no DIA
de uma ligação ao número (REL003 no ativo; REL002 atendida no receptivo); o resto do tel-8 × NOMINAL no período vira "Vendas assistidas"
(outro canal, bot ou outro dia) — decisão do Álex (08/10) para as sub-abas 1 Ativo, 2 Receptivo e 3 Funil unificado. Pipeline
televendas_dash R63: s1 vendas_atrib/vendas_atrib_alo/vendas_ctn_tv_humano/vendas_ctn_dia, s10 vendas_atrib/vendas_ctn_tv_humano,
s11 vendas_atrib_discados/vendas_ctn_discados_tv_humano. Tudo condicionado a `_r63` (métrica presente) — sem recarga cai no layout R45.
(2) Sai da sub-aba 2 o bloco "Vendas confirmadas (janela do contato) por canal creditado" e o parágrafo "Vendas encontradas (janela…)"
da nota (confundia a operação); o verbete do glossário fica só como histórico. (3) Glossário: verbete 'Vendas (CTN) / Filiaram no mês'
reescrito + 'Vendas (CTN) atribuídas × assistidas' novo. Idempotente (marker `_r63 =`).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r63_atribuicao_idpv_dia.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "_r63 = "
if MARKER in text:
    print("  = R63 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# ===== 1 · glossário =====
replace_once('''        d="O telefone discado (ou atendido, no receptivo) aparece no CTN com filiação no mesmo período, por qualquer canal de venda. É a régua do slide Funil Televendas do RMA (🧲) e, desde a R45, o último degrau dos funis da 📞. Dá números maiores que a venda confirmada na janela porque não exige janela de contato nem tabulação; 'com tipo Televendas' é a fatia que o CTN creditou ao canal (humanos + bots).",
        o="Escallo × NOMINAL por tel-8", a="🧲 📞", s=["Vendas (CTN)", "Filiaram no mês", "Discados que filiaram", "teto", "com tipo Televendas (CTN)"]),''',
             '''        d="O telefone discado (ou atendido, no receptivo) aparece no CTN com filiação no mesmo período, por qualquer canal de venda. É a régua do slide Funil Televendas do RMA (🧲). Na 📞, desde a R63 (08/10) ela é o total 'atribuídas + assistidas': o último degrau dos funis passou a ser só a venda atribuída (ver 'Vendas (CTN) atribuídas × assistidas').",
        o="Escallo × NOMINAL por tel-8", a="🧲 📞", s=["Vendas (CTN)", "Filiaram no mês", "Discados que filiaram", "teto", "com tipo Televendas (CTN)"]),
    'Vendas (CTN) atribuídas × assistidas': dict(sec="Televendas (Escallo)",
        d="Atribuída = o telefone discado (ou atendido) filiou no CTN com tipo Televendas pelo IDPV de um operador humano (bots Lia/Nora/Cris fora) e no MESMO DIA em que recebeu uma ligação ativa (no receptivo: no dia de uma ligação atendida). É a venda creditada à operação de telefone. Assistida = o telefone filiou no período, mas por outro canal (site, campo, MGM…), por um bot ou em outro dia: o televendas tocou o cliente, não fechou a venda. Atribuídas + assistidas = 'Vendas (CTN)' da régua do relatório.",
        p="Set/26 (ativo): 8.951 discados filiaram no mês; 1.415 com tipo Televendas (1.106 por operador humano, 309 por bot); 963 atribuídas (humano, no dia da ligação). Pedido do time (01/10): venda só pelo IDPV do televendas e só no próprio dia.",
        o="Escallo (REL003/REL002) × NOMINAL por tel-8 + IDPV", a="📞", s=["Vendas (CTN) atribuídas", "Vendas assistidas", "atribuída", "assistida", "venda no dia"]),''',
             "1) glossário")

# ===== 2 · sub-aba 1 · Escallo Ativo =====
replace_once('''        v_ctn_alo_tv = _tv_val(S, 'vendas_ctn_alo_tv'); v_ctn_p = _tv_val(S, 'vendas_ctn', meses=_tv_per_p)
        _sem_alo_tv = ((v_ctn_tv or 0) - (v_ctn_alo_tv or 0)) if v_ctn_tv is not None else None
        _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v_ctn, leads)} {_tv_delta(v_ctn, v_ctn_p)}",
                f"{_tv_n(v_ctn)} discados com filiação no NOMINAL no período (tel-8, qualquer canal) · {_tv_n(v_ctn_tv)} com tipo Televendas")
''', '''        v_ctn_alo_tv = _tv_val(S, 'vendas_ctn_alo_tv'); v_ctn_p = _tv_val(S, 'vendas_ctn', meses=_tv_per_p)
        _sem_alo_tv = ((v_ctn_tv or 0) - (v_ctn_alo_tv or 0)) if v_ctn_tv is not None else None
        # R63 (08/10): atribuída = tipo Televendas por IDPV humano E filiação no dia de uma ligação; o resto = assistida
        v_atrib = _tv_val(S, 'vendas_atrib'); v_atrib_alo = _tv_val(S, 'vendas_atrib_alo'); v_hum = _tv_val(S, 'vendas_ctn_tv_humano')
        v_dia = _tv_val(S, 'vendas_ctn_dia'); v_atrib_p = _tv_val(S, 'vendas_atrib', meses=_tv_per_p)
        _r63 = v_atrib is not None
        v_assist = ((v_ctn or 0) - (v_atrib or 0)) if (_r63 and v_ctn is not None) else None
        if _r63:
            _tv_kpi(k4, "🛒", "Vendas (CTN) atribuídas", f"{_tv_pct(v_atrib, leads)} {_tv_delta(v_atrib, v_atrib_p)}",
                    f"{_tv_n(v_atrib)} discados filiaram pelo IDPV de um operador no dia de uma ligação · {_tv_n(v_assist)} assistidas "
                    f"(filiaram no período por outro canal, bot ou outro dia)")
        else:
            _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v_ctn, leads)} {_tv_delta(v_ctn, v_ctn_p)}",
                    f"{_tv_n(v_ctn)} discados com filiação no NOMINAL no período (tel-8, qualquer canal) · {_tv_n(v_ctn_tv)} com tipo Televendas")
''', "2a) KPI 4 ativo")

replace_once('''            _tv_funil("Funil Escallo · discagem ativa — do discado à venda no CTN", [
                ("📞", "Leads discados (referência)", leads, "a mesma base do funil acima"),
                ("🛒", "Vendas (CTN)", v_ctn, "discados com filiação no NOMINAL no mesmo período, qualquer canal (tel-8) · seq. = % dos discados"),
                ("🗣️", "└ conversaram (≥ 10 s) e filiaram", v_ctn_alo, f"{_tv_pct(v_ctn_alo, alo)} das ligações qualificadas · seq. = % das vendas", 1),
                ("📞", "└ com tipo Televendas (CTN)", v_ctn_tv, f"{_tv_n(v_ctn_alo_tv)} com conversa ≥ 10 s · {_tv_n(_sem_alo_tv)} sem · seq. = % das vendas", 1),
            ], subtitle=_tv_per_lbl)
            st.caption("Fonte: ESCALLO_LEADS_MES (REL003 ativo + REL086 classificação; carga diária 8h) × NOMINAL_VENDAS por tel-8. "
                       "'Vendas (CTN)' é a régua do Relatório Mensal (R45): filiação no CTN no mesmo período, por qualquer canal de venda — "
                       "o Escallo não captura CPF, então o cruzamento é por telefone (teto de influência, não atribuição). "
                       "A tabulação 'venda' do operador e a confirmação na janela do contato saíram do funil e ficam na nota ao lado. "
''', '''            if _r63:
                _tv_funil("Funil Escallo · discagem ativa — do discado à venda no CTN", [
                    ("📞", "Leads discados (referência)", leads, "a mesma base do funil acima"),
                    ("🛒", "Vendas (CTN) atribuídas", v_atrib, "filiação no CTN com tipo Televendas pelo IDPV de um operador humano, no dia de uma ligação ao número · seq. = % dos discados"),
                    ("🗣️", "└ conversaram (≥ 10 s) e filiaram", v_atrib_alo, f"{_tv_pct(v_atrib_alo, alo)} das ligações qualificadas · seq. = % das atribuídas", 1),
                    ("🤝", "Vendas assistidas", v_assist, f"filiaram no período por outro canal, por bot ou em outro dia (tel-8 × NOMINAL) — influência, não atribuição · "
                                                           f"{_tv_n(v_hum)} com IDPV humano em qualquer dia · seq. = % dos discados", 0),
                ], subtitle=_tv_per_lbl)
            else:
                _tv_funil("Funil Escallo · discagem ativa — do discado à venda no CTN", [
                    ("📞", "Leads discados (referência)", leads, "a mesma base do funil acima"),
                    ("🛒", "Vendas (CTN)", v_ctn, "discados com filiação no NOMINAL no mesmo período, qualquer canal (tel-8) · seq. = % dos discados"),
                    ("🗣️", "└ conversaram (≥ 10 s) e filiaram", v_ctn_alo, f"{_tv_pct(v_ctn_alo, alo)} das ligações qualificadas · seq. = % das vendas", 1),
                    ("📞", "└ com tipo Televendas (CTN)", v_ctn_tv, f"{_tv_n(v_ctn_alo_tv)} com conversa ≥ 10 s · {_tv_n(_sem_alo_tv)} sem · seq. = % das vendas", 1),
                ], subtitle=_tv_per_lbl)
            st.caption("Fonte: ESCALLO_LEADS_MES (REL003 ativo + REL086 classificação; carga diária 8h) × NOMINAL_VENDAS por tel-8 + IDPV. "
                       + ("'Vendas (CTN) atribuídas' (R63, pedido do time): filiação com tipo Televendas pelo IDPV de um operador humano "
                          "(bots Lia/Nora/Cris fora) no mesmo dia de uma ligação ao número; 'assistidas' = o telefone filiou no período por outro "
                          "canal, por bot ou em outro dia — o televendas tocou o cliente, não fechou a venda. Atribuídas + assistidas = régua do RMA. "
                          if _r63 else
                          "'Vendas (CTN)' é a régua do Relatório Mensal (R45): filiação no CTN no mesmo período, por qualquer canal de venda — "
                          "o Escallo não captura CPF, então o cruzamento é por telefone (teto de influência, não atribuição). ")
                       + "A tabulação 'venda' do operador saiu do funil e fica na nota ao lado. "
''', "2b) funil ativo + caption")

replace_once('''        _tv_chart_mensal(_tv_long(S, ['leads', 'alo10', 'classif', 'vendas_ctn'], meses=_mg1,
                                  labels={'leads': 'Leads discados', 'alo10': 'Ligação Qualificada (≥ 10 s)', 'classif': 'Classificados', 'vendas_ctn': 'Vendas (CTN)'}),
                         "Série mensal — discagem ativa", stacked=False, rotulos=True, fonte="ESCALLO_LEADS_MES (REL003 + REL086)")
''', '''        _tv_chart_mensal(_tv_long(S, ['leads', 'alo10', 'classif', 'vendas_atrib' if _r63 else 'vendas_ctn'], meses=_mg1,
                                  labels={'leads': 'Leads discados', 'alo10': 'Ligação Qualificada (≥ 10 s)', 'classif': 'Classificados',
                                          'vendas_ctn': 'Vendas (CTN)', 'vendas_atrib': 'Vendas (CTN) atribuídas'}),
                         "Série mensal — discagem ativa", stacked=False, rotulos=True, fonte="ESCALLO_LEADS_MES (REL003 + REL086)")
''', "2c) série mensal ativo")

# ===== 3 · sub-aba 2 · Receptivo =====
replace_once('''        v10 = _tv_val(S10, 'vendas_ctn'); v10_tv = _tv_val(S10, 'vendas_ctn_tv')
''', '''        v10 = _tv_val(S10, 'vendas_ctn'); v10_tv = _tv_val(S10, 'vendas_ctn_tv')
        v10_atrib = _tv_val(S10, 'vendas_atrib'); v10_hum = _tv_val(S10, 'vendas_ctn_tv_humano')   # R63
        v10_atrib_p = _tv_val(S10, 'vendas_atrib', meses=_tv_per_p)
        _r63r = v10_atrib is not None
        v10_assist = ((v10 or 0) - (v10_atrib or 0)) if (_r63r and v10 is not None) else None
''', "3a) vars receptivo")
replace_once('''        _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v10, lg_atd)} {_tv_delta(v10, v10_p)}",
                f"{_tv_n(v10)} telefones atendidos com filiação no NOMINAL no período ({_tv_pct(v10, tl_atd)} dos telefones atendidos) · "
                f"{_tv_n(v10_tv)} tipo Televendas")
''', '''        if _r63r:
            _tv_kpi(k4, "🛒", "Vendas (CTN) atribuídas", f"{_tv_pct(v10_atrib, lg_atd)} {_tv_delta(v10_atrib, v10_atrib_p)}",
                    f"{_tv_n(v10_atrib)} telefones atendidos filiaram pelo IDPV de um operador no dia de uma ligação atendida "
                    f"({_tv_pct(v10_atrib, tl_atd)} dos telefones atendidos) · {_tv_n(v10_assist)} assistidas")
        else:
            _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v10, lg_atd)} {_tv_delta(v10, v10_p)}",
                    f"{_tv_n(v10)} telefones atendidos com filiação no NOMINAL no período ({_tv_pct(v10, tl_atd)} dos telefones atendidos) · "
                    f"{_tv_n(v10_tv)} tipo Televendas")
''', "3b) KPI 4 receptivo")
replace_once('''                ("🛒", "Vendas (CTN)", v10, f"telefones atendidos com filiação no NOMINAL no mesmo período (tel-8, qualquer canal) · "
                                          f"seq. = % das ligações atendidas · {_tv_pct(v10, tl_atd)} dos telefones atendidos", 1),
                ("📞", "└ com tipo Televendas (CTN)", v10_tv, "seq. = % das vendas", 3),
            ], subtitle=_tv_per_lbl)
''', '''            ] + ([
                ("🛒", "Vendas (CTN) atribuídas", v10_atrib, f"telefones atendidos que filiaram com tipo Televendas pelo IDPV de um operador humano, no dia "
                                                             f"de uma ligação atendida · seq. = % das ligações atendidas · {_tv_pct(v10_atrib, tl_atd)} dos telefones atendidos", 1),
                ("🤝", "Vendas assistidas", v10_assist, "atendidos que filiaram no período por outro canal, por bot ou em outro dia (tel-8 × NOMINAL) · seq. = % das atendidas", 1),
            ] if _r63r else [
                ("🛒", "Vendas (CTN)", v10, f"telefones atendidos com filiação no NOMINAL no mesmo período (tel-8, qualquer canal) · "
                                          f"seq. = % das ligações atendidas · {_tv_pct(v10, tl_atd)} dos telefones atendidos", 1),
                ("📞", "└ com tipo Televendas (CTN)", v10_tv, "seq. = % das vendas", 3),
            ]), subtitle=_tv_per_lbl)
''', "3c) funil receptivo")
replace_once('''            st.caption("Fonte: Televendas_REL002 (uma linha por ligação recebida; carga da TI) × NOMINAL_VENDAS por tel-8 — régua 'Vendas (CTN)' "
                       "da R45. Uma ligação que fica só na URA (sem fila, sem agente) não conta como recebida pela operação; o volume aparece "
                       "no KPI para conferência. Vendas por telefone porque o CTN não sabe qual ligação vendeu.")
''', '''            st.caption("Fonte: Televendas_REL002 (uma linha por ligação recebida; carga da TI) × NOMINAL_VENDAS por tel-8 + IDPV. "
                       + ("'Atribuídas' (R63): filiação com tipo Televendas pelo IDPV de um operador humano no dia de uma ligação atendida; "
                          "'assistidas' = filiou no período por outro canal, bot ou outro dia. " if _r63r else "Régua 'Vendas (CTN)' da R45. ")
                       + "Uma ligação que fica só na URA (sem fila, sem agente) não conta como recebida pela operação; o volume aparece "
                       "no KPI para conferência. Vendas por telefone porque o CTN não sabe qual ligação vendeu.")
''', "3d) caption receptivo")
# bloco "Vendas confirmadas (janela do contato) por canal creditado" sai (R63, pedido do Álex: confundia a operação)
replace_once('''            if not _t2.empty:
                _t2c = _t2.copy(); _t2c['pct'] = _t2c['valor'] / _t2c['valor'].sum() * 100
                _t2c['mes'] = 'período'; _t2c['serie'] = _t2c['dim']
                _tv_titulo("Vendas confirmadas (janela do contato) por canal creditado — receptivo",
                           f"tipo_venda gravado pelo CTN no NOMINAL · {_tv_per_lbl}", "A")
''', '''            if False:   # R63: bloco "Vendas confirmadas (janela do contato) por canal creditado" removido (confundia a operação)
                _t2c = _t2.copy(); _t2c['pct'] = _t2c['valor'] / _t2c['valor'].sum() * 100
                _t2c['mes'] = 'período'; _t2c['serie'] = _t2c['dim']
                _tv_titulo("Vendas confirmadas (janela do contato) por canal creditado — receptivo",
                           f"tipo_venda gravado pelo CTN no NOMINAL · {_tv_per_lbl}", "A")
''', "3e) bloco janela do contato (receptivo) desligado")
replace_once('''                f"não é movido pela ligação (Bloco 7 da Jornada: o receptivo não cria nem movimenta Negócio).<br><br>"
                f"<b>Vendas encontradas (janela do contato + 14 d, leitura anterior à R45).</b> {_tv_n(r_conf)} telefones ({_tv_pct(r_conf, r_leads)}) aparecem com filiação no NOMINAL; "
                f"dessas vendas, {_tv_pct(crm_v_no, crm_v)} têm Lead no CRM e {_tv_pct(crm_v_deal, crm_v)} têm Negócio. "
                f"Apenas <b>{_tv_pct(_tv_tipo, _tot_tipo)}</b> foram registradas pelo CTN com IDPV de televendas "
                f"(tipo Televendas no CTN); o restante foi creditado a outros canais (site, MGM, campo…) — vendas trabalhadas "
                f"ou influenciadas pelo televendas, não necessariamente convertidas por ele.",
                bg="#fff7ed", icon="⚠️")
''', '''                f"não é movido pela ligação (Bloco 7 da Jornada: o receptivo não cria nem movimenta Negócio).",
                bg="#fff7ed", icon="⚠️")
''', "3f) parágrafo 'Vendas encontradas (janela)' removido")
replace_once('''        _tv_chart_mensal(_tv_long(S10, ['recebidas', 'atendidas', 'abandono', 'vendas_ctn'], meses=_mg2,
                                  labels={'recebidas': 'Ligações recebidas', 'atendidas': 'Ligações atendidas', 'abandono': 'Abandono', 'vendas_ctn': 'Vendas (CTN)'}),
''', '''        _tv_chart_mensal(_tv_long(S10, ['recebidas', 'atendidas', 'abandono', 'vendas_atrib' if _r63r else 'vendas_ctn'], meses=_mg2,
                                  labels={'recebidas': 'Ligações recebidas', 'atendidas': 'Ligações atendidas', 'abandono': 'Abandono',
                                          'vendas_ctn': 'Vendas (CTN)', 'vendas_atrib': 'Vendas (CTN) atribuídas'}),
''', "3g) série mensal receptivo")

# ===== 4 · sub-aba 3 · funil unificado =====
replace_once('''        u_v_nd = _tv_val(S11, 'vendas_ctn_nao_discados'); u_fe_disc = _tv_val(S11, 'fe_discados'); u_fe_v = _tv_val(S11, 'fe_vendas_ctn')
        if u_ne is not None:
''', '''        u_v_nd = _tv_val(S11, 'vendas_ctn_nao_discados'); u_fe_disc = _tv_val(S11, 'fe_discados'); u_fe_v = _tv_val(S11, 'fe_vendas_ctn')
        u_atrib = _tv_val(S11, 'vendas_atrib_discados'); u_hum = _tv_val(S11, 'vendas_ctn_discados_tv_humano')   # R63
        _r63u = u_atrib is not None
        u_assist = ((u_v or 0) - (u_atrib or 0)) if (_r63u and u_v is not None) else None
        if u_ne is not None:
''', "4a) vars unificado")
replace_once('''                ("🛒", "Vendas (CTN) — dos discados", u_v, "tel-8 × NOMINAL no mesmo período, qualquer canal · seq. = % dos discados", 2),
                ("🗣️", "└ conversaram (≥ 10 s) e filiaram", u_v_alo, f"{_tv_pct(u_v_alo, u_alo)} das ligações qualificadas · seq. = % das vendas", 5),
                ("📞", "└ com tipo Televendas (CTN)", u_v_tv, "seq. = % das vendas", 5),
            ], subtitle=_tv_per_lbl)
''', '''            ] + ([
                ("🛒", "Vendas (CTN) atribuídas — dos discados", u_atrib, "filiação com tipo Televendas pelo IDPV de um operador humano, no dia de uma ligação · seq. = % dos discados", 2),
                ("🤝", "Vendas assistidas — dos discados", u_assist, f"filiaram no período por outro canal, bot ou outro dia (tel-8 × NOMINAL) · {_tv_n(u_hum)} com IDPV humano em qualquer dia · seq. = % dos discados", 2),
            ] if _r63u else [
                ("🛒", "Vendas (CTN) — dos discados", u_v, "tel-8 × NOMINAL no mesmo período, qualquer canal · seq. = % dos discados", 2),
                ("🗣️", "└ conversaram (≥ 10 s) e filiaram", u_v_alo, f"{_tv_pct(u_v_alo, u_alo)} das ligações qualificadas · seq. = % das vendas", 5),
                ("📞", "└ com tipo Televendas (CTN)", u_v_tv, "seq. = % das vendas", 5),
            ]), subtitle=_tv_per_lbl)
''', "4b) funil unificado")

write_app(text, bom, crlf)
print("R63 aplicada")
