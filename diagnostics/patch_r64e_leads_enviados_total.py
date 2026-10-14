"""R64e (14/10/2026) — 📞 Televendas: vocabulário novo em TODO lugar, inclusive fallbacks e glossário (pedido do Álex, 14/10).
(1) "leads enviados ao televendas" em vez de "Contatos no fluxo" também fora do funil: título da sub-aba 3, bloco 💬 com × sem WhatsApp,
    toggle de raias, série da sub-aba 7, degraus do funil do pipeline ("% dos leads enviados"); (2) ramos de FALLBACK (agregado sem as
    métricas R58/R63) passam a usar os termos novos: "Vendas (CTN) — atribuídas + assistidas" (sem a separação neste período), sem
    "Compra reportada"/"Confirmadas (CPF ±3 d)" como degrau do funil Talkerchat, KPI 4 da Talkerchat como "Vendas (CTN) — humano · Lia"
    indisponível; (3) 🧲 Aquisição (fallback do s2_super) e sub-aba 7 (Régua 4) sem "Vendas confirmadas (janela do contato)" como rótulo,
    "alô humano" → "conversa ≥ 10 s com operador humano"; (4) glossário sem os rótulos antigos como sinônimos ("Alô (≥ 10 s)",
    "Vendas confirmadas (janela…)", "sales-ready", "Contatos no fluxo"), verbetes 'Fluxo do televendas' e 'Venda confirmada (janela do
    contato)' reescritos. Só texto/rótulos — nenhuma métrica muda. Idempotente (marker 'Funil HubSpot (leads enviados)').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r64e_leads_enviados_total.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "Funil HubSpot (leads enviados)"
if MARKER in text:
    print("  = R64e já aplicada")
    sys.exit(0)


def rep(old, new, label, n=1):
    global text
    c = text.count(old)
    if c != n:
        print(f"ERRO: {label}: ancora encontrada {c}x (esperado {n})")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# ---------------------------------------------------------------- (1) "leads enviados" fora do funil (sub-abas 3 e 7)
rep('"🧭 3 · Funil HubSpot (Contatos)"', '"🧭 3 · Funil HubSpot (leads enviados)"', "1a) título da sub-aba 3")
rep('''help="Estudo complementar: taxa de filiação dos Contatos que entraram no fluxo, separando quem veio de um canal "''',
    '''help="Estudo complementar: taxa de filiação dos leads enviados ao televendas (Contatos do HubSpot), separando quem veio de um canal "''',
    "1b) help do toggle WhatsApp")
rep('''help="Alternativa ao funil: Contatos no fluxo na raia de Contato, entradas por estágio na raia de Negócio, "''',
    '''help="Alternativa ao funil: leads enviados ao televendas na raia de Contato, entradas por estágio na raia de Negócio, "''',
    "1c) help do toggle de raias")
rep('''"rótulo 'Fora do expediente' no funil_de_contatos · seq. = % dos Contatos", 0)]''',
    '''"rótulo 'Fora do expediente' no funil_de_contatos · seq. = % dos leads enviados", 0)]''', "1d) pipeline · fora do expediente")
rep('''("🤝", "Viraram Negócio na esteira", _ent['LEAD'], "Negócio criado no 1º estágio da esteira (LEAD) · seq. = % dos Contatos"),''',
    '''("🤝", "Viraram Negócio na esteira", _ent['LEAD'], "Negócio criado no 1º estágio da esteira (LEAD) · seq. = % dos leads enviados"),''',
    "1e) pipeline · viraram Negócio")
rep('''for _lbl_w, _org_w in (("Todos os Contatos do fluxo", None), ("Origem WhatsApp", 'whatsapp'), ("Sem os leads de WhatsApp", 'outros')):''',
    '''for _lbl_w, _org_w in (("Todos os leads enviados", None), ("Origem WhatsApp", 'whatsapp'), ("Sem os leads de WhatsApp", 'outros')):''',
    "1f) bloco WhatsApp · linhas")
rep('''_rows_w.append({'Contatos no fluxo': _lbl_w, 'Entradas': _tv_n(_e), 'com CPF': _tv_pct(_cp, _e),''',
    '''_rows_w.append({'Leads enviados ao televendas': _lbl_w, 'Entradas': _tv_n(_e), 'com CPF': _tv_pct(_cp, _e),''',
    "1g) bloco WhatsApp · coluna (dict)")
rep('''_st_mt(_rows_w, ['Contatos no fluxo', 'Entradas', 'com CPF', 'Filiaram no período',''',
    '''_st_mt(_rows_w, ['Leads enviados ao televendas', 'Entradas', 'com CPF', 'Filiaram no período',''',
    "1h) bloco WhatsApp · coluna (lista)")
rep('''_tv_titulo("Conversão dos Contatos do fluxo — com e sem os leads de WhatsApp",''',
    '''_tv_titulo("Conversão dos leads enviados ao televendas — com e sem os leads de WhatsApp",''', "1i) bloco WhatsApp · título")
rep('''labels={'filiacoes_fluxo_antes': 'Contatos no fluxo antes de filiar'}),''',
    '''labels={'filiacoes_fluxo_antes': 'Leads enviados ao televendas antes de filiar'}),''', "1j) sub-aba 7 · série")
rep('''subtitle="resultado (NOMINAL) · influência (Contatos no fluxo antes / Escallo tel-8) · processo (Negócios GANHO)")''',
    '''subtitle="resultado (NOMINAL) · influência (leads enviados ao televendas antes de filiar / Escallo tel-8) · processo (Negócios GANHO)")''',
    "1k) sub-aba 7 · subtítulo")
rep('''_tv_kpi(k4, "☎️", "Vendas confirmadas pelo Escallo (janela do contato)", _tv_n(esc_cas),
                f"ativo {_tv_n(esc_at)} · receptivo {_tv_n(esc_re)} — por mês da venda", color="#b45309")''',
    '''_tv_kpi(k4, "☎️", "Régua 4 · Escallo · atribuídas + assistidas (tel-8, janela do contato)", _tv_n(esc_cas),
                f"ativo {_tv_n(esc_at)} · receptivo {_tv_n(esc_re)} — por mês da venda · telefone tocado pelo Escallo antes de filiar", color="#b45309")''',
    "1l) sub-aba 7 · Régua 4")

# ---------------------------------------------------------------- (2) fallbacks das sub-abas 1 / 2 / 3 (agregado sem vendas_atrib)
_SEM_SEP = "separação atribuída × assistida indisponível neste período"
rep('''            _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v_ctn, leads)} {_tv_delta(v_ctn, v_ctn_p)}",
                    f"{_tv_n(v_ctn)} discados com filiação no NOMINAL no período (tel-8, qualquer canal) · {_tv_n(v_ctn_tv)} com tipo Televendas")''',
    f'''            _tv_kpi(k4, "🛒", "Vendas (CTN) — atribuídas + assistidas", f"{{_tv_pct(v_ctn, leads)}} {{_tv_delta(v_ctn, v_ctn_p)}}",
                    f"{{_tv_n(v_ctn)}} discados com filiação no NOMINAL no período (tel-8, qualquer canal) · {{_tv_n(v_ctn_tv)}} com tipo Televendas · "
                    f"{_SEM_SEP} (recarregue o s1)")''',
    "2a) sub-aba 1 · KPI 4 fallback")
rep('''                    ("🛒", "Vendas (CTN)", v_ctn, "discados com filiação no NOMINAL no mesmo período, qualquer canal (tel-8) · seq. = % dos discados"),
                    ("🗣️", "└ conversaram (≥ 10 s) e filiaram", v_ctn_alo, f"{_tv_pct(v_ctn_alo, alo)} das ligações qualificadas · seq. = % das vendas", 1),
                    ("📞", "└ com tipo Televendas (CTN)", v_ctn_tv, f"{_tv_n(v_ctn_alo_tv)} com conversa ≥ 10 s · {_tv_n(_sem_alo_tv)} sem · seq. = % das vendas", 1),''',
    f'''                    ("🛒", "Vendas (CTN) — atribuídas + assistidas", v_ctn, "discados com filiação no NOMINAL no mesmo período, qualquer canal (tel-8) · {_SEM_SEP} · seq. = % dos discados"),
                    ("🗣️", "└ conversaram (≥ 10 s) e filiaram", v_ctn_alo, f"{{_tv_pct(v_ctn_alo, alo)}} das ligações qualificadas · seq. = % das vendas", 1),
                    ("📞", "└ com tipo Televendas (CTN) — inclui bots e vendas em outro dia", v_ctn_tv, f"{{_tv_n(v_ctn_alo_tv)}} com conversa ≥ 10 s · {{_tv_n(_sem_alo_tv)}} sem · seq. = % das vendas", 1),''',
    "2b) sub-aba 1 · funil fallback")
rep('''                          "'Vendas (CTN)' é a régua do Relatório Mensal (R45): filiação no CTN no mesmo período, por qualquer canal de venda — "
                          "o Escallo não captura CPF, então o cruzamento é por telefone (teto de influência, não atribuição). ")''',
    '''                          "'Vendas (CTN) — atribuídas + assistidas': neste período o agregado ainda não separa a venda atribuída (IDPV de operador "
                          "humano, no dia de uma ligação) da assistida — é a régua do Relatório Mensal: filiação no CTN no mesmo período, por qualquer "
                          "canal (o Escallo não captura CPF, o cruzamento é por telefone). Recarregue o s1 para ver a separação. ")''',
    "2c) sub-aba 1 · caption fallback")
rep('''                                          'vendas_ctn': 'Vendas (CTN)', 'vendas_atrib': 'Vendas (CTN) atribuídas'}),''',
    '''                                          'vendas_ctn': 'Vendas (CTN) — atribuídas + assistidas', 'vendas_atrib': 'Vendas (CTN) atribuídas'}),''',
    "2d) séries mensais sub-abas 1 e 2 · rótulo fallback", n=2)
rep('''            _tv_kpi(k4, "🛒", "Vendas (CTN)", f"{_tv_pct(v10, lg_atd)} {_tv_delta(v10, v10_p)}",
                    f"{_tv_n(v10)} telefones atendidos com filiação no NOMINAL no período ({_tv_pct(v10, tl_atd)} dos telefones atendidos) · "
                    f"{_tv_n(v10_tv)} tipo Televendas")''',
    f'''            _tv_kpi(k4, "🛒", "Vendas (CTN) — atribuídas + assistidas", f"{{_tv_pct(v10, lg_atd)}} {{_tv_delta(v10, v10_p)}}",
                    f"{{_tv_n(v10)}} telefones atendidos com filiação no NOMINAL no período ({{_tv_pct(v10, tl_atd)}} dos telefones atendidos) · "
                    f"{{_tv_n(v10_tv)}} tipo Televendas · {_SEM_SEP}")''',
    "2e) sub-aba 2 · KPI 4 fallback")
rep('''                ("🛒", "Vendas (CTN)", v10, f"telefones atendidos com filiação no NOMINAL no mesmo período (tel-8, qualquer canal) · "
                                          f"seq. = % das ligações atendidas · {_tv_pct(v10, tl_atd)} dos telefones atendidos", 1),
                ("📞", "└ com tipo Televendas (CTN)", v10_tv, "seq. = % das vendas", 3),''',
    f'''                ("🛒", "Vendas (CTN) — atribuídas + assistidas", v10, f"telefones atendidos com filiação no NOMINAL no mesmo período (tel-8, qualquer canal) · "
                                          f"{_SEM_SEP} · seq. = % das ligações atendidas · {{_tv_pct(v10, tl_atd)}} dos telefones atendidos", 1),
                ("📞", "└ com tipo Televendas (CTN) — inclui bots e vendas em outro dia", v10_tv, "seq. = % das vendas", 3),''',
    "2f) sub-aba 2 · funil fallback")
rep('''"'assistidas' = filiou no período por outro canal, bot ou outro dia. " if _r63r else "Régua 'Vendas (CTN)' da R45. ")''',
    '''"'assistidas' = filiou no período por outro canal, bot ou outro dia. " if _r63r else
                          "'Vendas (CTN) — atribuídas + assistidas': o Televendas_REL002 só guarda o mês corrente, então neste período não dá para "
                          "separar a atribuída (IDPV de operador humano, no dia de uma ligação atendida) da assistida — fica a régua do relatório "
                          "(filiação no período, qualquer canal, tel-8). ")''',
    "2g) sub-aba 2 · caption fallback")
rep('''                ("🛒", "Vendas (CTN) — dos discados", u_v, "tel-8 × NOMINAL no mesmo período, qualquer canal · seq. = % dos discados", 2),
                ("🗣️", "└ conversaram (≥ 10 s) e filiaram", u_v_alo, f"{_tv_pct(u_v_alo, u_alo)} das ligações qualificadas · seq. = % das vendas", 5),
                ("📞", "└ com tipo Televendas (CTN)", u_v_tv, "seq. = % das vendas", 5),''',
    f'''                ("🛒", "Vendas (CTN) — atribuídas + assistidas, dos discados", u_v, "tel-8 × NOMINAL no mesmo período, qualquer canal · {_SEM_SEP} (recarregue o s11) · seq. = % dos discados", 2),
                ("🗣️", "└ conversaram (≥ 10 s) e filiaram", u_v_alo, f"{{_tv_pct(u_v_alo, u_alo)}} das ligações qualificadas · seq. = % das vendas", 5),
                ("📞", "└ com tipo Televendas (CTN) — inclui bots e vendas em outro dia", u_v_tv, "seq. = % das vendas", 5),''',
    "2h) sub-aba 3 · funil unificado fallback")

# ---------------------------------------------------------------- (2) fallbacks da sub-aba 4 Talkerchat (agregado sem R58)
rep('''            _tv_kpi(k2, "🪪", "Qualificados (com CPF)", f"{_tv_pct(tcpf, tl)}", f"{_tv_n(tcpf)} usuários com CPF capturado nas mensagens")''',
    '''            _tv_kpi(k2, "🪪", "Qualificados (CPF lido)", f"{_tv_pct(tcpf, tl)}",
                    f"{_tv_n(tcpf)} usuários com CPF lido · a régua 'CPF validado, não cliente' exige a recarga do S7 (agregado sem R58)")''',
    "2i) Talkerchat · KPI 2 fallback")
rep('''            _tv_kpi(k4, "🛒", "Compras reportadas → confirmadas", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                    f"Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)} · {_tv_pct(tconf, tpar)} confirmadas no NOMINAL (CPF ±3 d)")''',
    '''            _tv_kpi(k4, "🏷️", "Vendas (CTN) — humano · Lia", "—",
                    f"NOMINAL por IDPV indisponível neste período (agregado sem nv_*; recarregue o S7) · registro da operação: "
                    f"{_tv_n(tcomp)} compras reportadas {_tv_delta(tcomp, tcomp_p)}, Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)}", color="#166534")''',
    "2j) Talkerchat · KPI 4 fallback")
rep('''                    ("🪪", "Qualificados (CPF)", tcpf, "CPF capturado nas mensagens (~75% de acerto) · seq. = % dos usuários únicos"),
                    ("🧑‍💼", "Chegaram a um humano", th, "usuários com agent_id em algum ticket — fatia dos usuários únicos (seq. = % deles)", 1),
                    ("🛒", "Compra reportada (usuários)", tlc, f"close_reason = 'Compra reportada' · {_tv_n(tcomp)} tickets"),
                    ("✅", "Confirmadas no CTN (CPF ±3 d)", tconf, "pares CPF × âncora (fechamento) ±3 d"),
                ], subtitle=_tv_per_lbl)''',
    '''                    ("🪪", "Qualificados (CPF lido)", tcpf, "CPF lido · a régua 'não cliente' e os usuários sem SAC exigem a recarga do S7 · seq. = % dos usuários únicos"),
                    ("🧑‍💼", "Chegaram a um humano", th, "usuários com agent_id em algum ticket — fatia dos usuários únicos (seq. = % deles)", 1),
                ], subtitle=_tv_per_lbl)
                st.caption(f"Vendas (CTN) por IDPV indisponíveis neste período (agregado sem as métricas R58 — rode `gt7 run televendas_dash --arg only=s7 "
                           f"--arg nv=skip`). Registro da operação: {_tv_n(tcomp)} compras reportadas ({_tv_n(tlc)} usuários), "
                           f"{_tv_n(tconf)} confirmadas por CPF ±3 d — relato do atendente/bot, não é a venda do funil.")''',
    "2k) Talkerchat · funil fallback sem compra reportada")
rep('''                                 "Compras reportadas por mês — Lia × humano", subtitle="close_reason = 'Compra reportada'",
                                 stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")''',
    '''                                 "Registro da operação — compras reportadas por mês (Lia × humano)", subtitle="close_reason = 'Compra reportada' · relato, não filiação · usuários sem SAC e qualificados exigem a recarga do S7",
                                 stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")''',
    "2l) Talkerchat · série fallback")
rep('''                _tv_kpi(n4, "🛒", "Reportadas (Talkerchat) × CTN", f"{_tv_n(tlia)} → {_tv_n(_nv_lia)}",''',
    '''                _tv_kpi(n4, "🛒", "Registro (compras reportadas da Lia) × CTN", f"{_tv_n(tlia)} → {_tv_n(_nv_lia)}",''',
    "2m) Fluxo Lia · KPI 4 fallback")
rep('''                    _tv_titulo("Ranking de atendentes — Vendas (CTN) por IDPV" if _ag58 else "Ranking de atendentes — compras reportadas",''',
    '''                    _tv_titulo("Ranking de atendentes — Vendas (CTN) por IDPV" if _ag58 else "Ranking de atendentes — compras reportadas (registro; Vendas (CTN) por IDPV exigem a recarga do S7)",''',
    "2n) ranking · título fallback")
rep('''xaxis_title='vendas (CTN) por IDPV' if _ag58 else 'compras reportadas',''',
    '''xaxis_title='vendas (CTN) por IDPV' if _ag58 else 'compras reportadas (registro)',''', "2o) ranking · eixo fallback")

# ---------------------------------------------------------------- (3) 🧲 Aquisição (fallback do s2_super) — mesmos termos
rep('''("🗣️", "Ligação Qualificada (≥ 10 s)", _v8s('alo10', 'televendas'), "alô humano"),''',
    '''("🗣️", "Ligação Qualificada (≥ 10 s)", _v8s('alo10', 'televendas'), "conversa ≥ 10 s com operador humano"),''', "3a) 🧲 ativo s8 · nota")
rep('''("🗣️", "Ligação Qualificada (≥ 10 s)", _v10('s2_super', 'alo10', _sel10, 'ativo'), "alô humano"),
                    ("✅", "Vendas confirmadas (janela do contato)", _v10('s2_super', 'venda_confirmada', _sel10, 'ativo'), "tel-8 × NOMINAL na janela do contato"),''',
    '''("🗣️", "Ligação Qualificada (≥ 10 s)", _v10('s2_super', 'alo10', _sel10, 'ativo'), "conversa ≥ 10 s com operador humano"),
                    ("🛒", "Vendas (CTN) — atribuídas + assistidas (janela do contato)", _v10('s2_super', 'venda_confirmada', _sel10, 'ativo'), "tel-8 × NOMINAL na janela do contato · sem a separação atribuída × assistida (s8 não carregado)"),''',
    "3b) 🧲 ativo fallback")
rep('''("🗣️", "Ligação Qualificada (≥ 10 s)", _v8s('alo10', 'receptivo'), "alô humano"),''',
    '''("🗣️", "Ligação Qualificada (≥ 10 s)", _v8s('alo10', 'receptivo'), "conversa ≥ 10 s com operador humano"),''', "3c) 🧲 receptivo s8 · nota")
rep('''("🗣️", "Ligação Qualificada (≥ 10 s)", _v10('s2_super', 'alo10', _sel10, 'receptivo'), "alô humano"),
                    ("✅", "Vendas confirmadas (janela do contato)", _v10('s2_super', 'venda_confirmada', _sel10, 'receptivo'), "tel-8 × NOMINAL na janela do contato"),''',
    '''("🗣️", "Ligação Qualificada (≥ 10 s)", _v10('s2_super', 'alo10', _sel10, 'receptivo'), "conversa ≥ 10 s com operador humano"),
                    ("🛒", "Vendas (CTN) — atribuídas + assistidas (janela do contato)", _v10('s2_super', 'venda_confirmada', _sel10, 'receptivo'), "tel-8 × NOMINAL na janela do contato · sem a separação atribuída × assistida (s8 não carregado)"),''',
    "3d) 🧲 receptivo fallback")

# ---------------------------------------------------------------- (4) glossário — sem os rótulos antigos como sinônimos
rep('''        o="HubSpot", a="📞 🧲 🧭", s=["contatos", "Contatos no fluxo", "Existem no CRM (Contato por tel-8)", "Contatos que entraram no fluxo", "Com Contato no HubSpot"]),''',
    '''        o="HubSpot", a="📞 🧲 🧭", s=["contatos", "Existem no CRM (Contato por tel-8)", "Com Contato no HubSpot"]),''',
    "4a) glossário · Contato")
rep('''        d="A janela de duas horas em que os Leads do Grupo A ficam exclusivos do televendas antes de irem para distribuição. 'Entrou no fluxo' = tem a data de entrada gravada no Contato.",
        o="HubSpot (workflow)", a="📞 🧲", s=["Contatos no fluxo", "no fluxo TV"]),''',
    '''        d="A janela de duas horas em que os Leads do Grupo A ficam exclusivos do televendas antes de irem para distribuição. 'Entrou no fluxo' = tem a data de entrada gravada no Contato. Na 📞 esse Contato é o 'lead enviado ao televendas' — 'em horário comercial' tira os que entraram fora do expediente (rótulo 'Fora do expediente' no funil_de_contatos), que a esteira não trabalha.",
        p="Leia 'leads enviados' como pessoas (Contatos do HubSpot), não como números de telefone: o controle de duplicados abaixo do funil unificado mostra quantos números únicos há entre eles.",
        o="HubSpot (workflow)", a="📞 🧲", s=["Leads enviados ao televendas", "leads enviados", "em horário comercial", "no fluxo TV", "Entrou no fluxo"]),''',
    "4b) glossário · Fluxo do televendas")
rep('''        o="Escallo", a="📞 🧲", s=["alô", "alô humano", "Alô (≥ 10 s)", "Falaram ≥ 10 s", "Ligações qualificadas", "conversaram"]),''',
    '''        o="Escallo", a="📞 🧲", s=["alô", "alô humano", "Falaram ≥ 10 s", "Ligações qualificadas", "conversaram"]),''',
    "4c) glossário · Ligação Qualificada")
rep('''        d="O telefone discado aparece no CTN com filiação entre o 1º contato do mês e o último contato + 14 dias. É um teto de influência: a filiação coincidiu com a ligação, não prova que o televendas vendeu. Vive nos funis da operação (📞).",''',
    '''        d="O telefone discado aparece no CTN com filiação entre o 1º contato do mês e o último contato + 14 dias. É um teto de influência: a filiação coincidiu com a ligação, não prova que o televendas vendeu. Desde a R63 (08/10) não é degrau de funil na 📞: aparece só como confirmação da tabulação 'venda' do operador (nota da sub-aba 1), na Régua 4 da sub-aba 7 e na coluna 'Conf. CTN' do lado ramal — a venda do funil é a 'atribuída' (IDPV humano, no dia).",''',
    "4d) glossário · Venda confirmada (d)")
rep('''        o="Escallo × NOMINAL por tel-8", a="📞 🧲", s=["Confirmada no CTN", "Vendas confirmadas", "conf. CTN", "venda casada", "Vendas confirmadas (janela do contato)", "Vendas confirmadas (janela)"]),''',
    '''        o="Escallo × NOMINAL por tel-8", a="📞 🧲", s=["Confirmada no CTN", "conf. CTN", "venda casada", "janela do contato + 14 d"]),''',
    "4e) glossário · Venda confirmada (sinônimos)")
rep('''        o="Talkerchat × NOMINAL por CPF", a="📞", s=["Compras reportadas", "Confirmadas no CTN (CPF ±3 d)", "tabulação do atendente"]),''',
    '''        o="Talkerchat × NOMINAL por CPF", a="📞", s=["Compras reportadas", "Confirmadas por CPF ±3 d", "Registro da operação", "tabulação do atendente"]),''',
    "4f) glossário · Compra reportada")
rep('''        o="Talkerchat / CTN", a="📞", s=["Lia", "bots", "triagem", "handover", "sales-ready"]),''',
    '''        o="Talkerchat / CTN", a="📞", s=["Lia", "bots", "triagem", "handover"]),''', "4g) glossário · bots")

write_app(text, bom, crlf)
print("R64e aplicada")
