"""Rodada R58 (01/10/2026) — sub-aba 💬 4 · Talkerchat: pedidos do time de Televendas (pós-apresentação).

Pedidos e como foram atendidos (decisões do Álex em 01/10):
  1) Tirar o volume de vendas reportadas por atendente → o ranking passa a ser Vendas (CTN) por IDPV casado ao atendente
     (NOMINAL tipo Televendas, venda do dia); "compras reportadas" vira coluna de registro.
  2) Cruzamento pelos IDPVs (Badaró), não por tabulação → Vendas (CTN) = NOMINAL por IDPV humano de Televendas (telefone +
     WhatsApp — escolha do Álex), com a fatia "pelo IDPV WhatsApp"; a compra reportada e a confirmação CPF ±3 d ficam num
     expander "📋 Registro da operação".
  3) Só venda do dia (DT_FILIACAO no período), não a janela ±3 d do ticket.
  4) Só leads sem SAC; "qualificado" = CPF validado como não cliente (CPF lido e motivo fora de SAC / já cadastrado) —
     o volume de SAC fica na nota do topo. Piso explicado na nota (o GAS só lê CPF em 5 motivos).
  5) Fluxo Lia e vendas Lia em bloco separado (já era o bloco R44; ganhou o rótulo "Fluxo Lia — frente separada").
  6) Sai o funil "Qualificação → sales-ready → distribuição" (amostra de mensagens); cards e série das fases ficam.
Fonte no agregado (televendas_dash.py S7, R58): s7_talkerchat leads_so_sac, leads_sem_sac, qualif_nao_cliente,
leads_humano_sem_sac, qualif_humano, tickets_sem_sac, leads_sem_sac_ctn, qualif_ctn, humano_ctn, nv_tv_wpp;
s7_atendente vendas_ctn, vendas_ctn_wpp, vendas_ctn_tel, idpv_n.
Idempotente (marker `_r58 = tl_ss is not None`); preserva BOM/CRLF via _patchlib.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r58_talkerchat_time.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()

MARKER = "_r58 = tl_ss is not None"
if MARKER in text:
    print("  = R58 já aplicada (marker presente)")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# ---------------------------------------------------------------------------------------------------------
# 0) cabeçalho da aba
# ---------------------------------------------------------------------------------------------------------
replace_once("#   7 Talkerchat           usuários únicos → com CPF → Lia/humano → compra → NOMINAL; sem Negócios\n",
             "#   7 Talkerchat           usuários sem SAC → qualificados (CPF validado, não cliente) → humano → Vendas (CTN) por IDPV [R58]; Lia à parte\n",
             "0) cabeçalho")

# ---------------------------------------------------------------------------------------------------------
# 1) glossário
# ---------------------------------------------------------------------------------------------------------
replace_once('''    'Qualificado (com CPF)': dict(sec="WhatsApp (Talkerchat)",
        d="Usuário cujo CPF foi lido nas mensagens da conversa (~75% de acerto). Só esses cruzam com o CTN.",
        o="Talkerchat (leitura das mensagens)", a="📞", s=["Qualificados"]),
    'Compra reportada / confirmada': dict(sec="WhatsApp (Talkerchat)",
        d="Compra reportada = ticket fechado com esse motivo (o que o atendente ou o bot registrou). Confirmada = o CPF aparece no CTN com filiação até 3 dias antes ou depois do fechamento.",
        o="Talkerchat × NOMINAL por CPF", a="📞", s=["Compras reportadas", "Confirmadas no CTN (CPF ±3 d)"]),
''', '''    'Qualificado (CPF validado, não cliente)': dict(sec="WhatsApp (Talkerchat)",
        d="Usuário sem SAC cujo CPF foi lido nas mensagens e que não foi barrado como cliente (motivo do ticket fora de 'Transferido/Redirecionado para o SAC' e 'CPF já Cadastrado'). É o 'CPF validado como não cliente' pedido pelo time (01/10) — antes contava só quem informou o CPF.",
        p="Piso: a carga só lê o CPF nos motivos Link enviado, Compra reportada, SAC e CPF já cadastrado; conversas da Lia fechadas por fim de expediente / sem interação / janela encerrada não têm CPF lido.",
        o="Talkerchat (leitura das mensagens) + motivo de fechamento", a="📞", s=["Qualificados", "Qualificado (com CPF)", "CPF validado"]),
    'Usuário sem SAC': dict(sec="WhatsApp (Talkerchat)",
        d="Usuário único (tel-8) com ao menos um ticket no período fora dos motivos de SAC (Transferido/Redirecionado para o SAC) e de 'CPF já Cadastrado'. Quem só teve tickets desses motivos já é cliente e fica fora do funil (o volume aparece na nota do topo).",
        o="Talkerchat (close_reason_id 4, 174, 186, 5)", a="📞", s=["sem SAC", "só SAC", "Leads sem SAC"]),
    'Compra reportada / confirmada': dict(sec="WhatsApp (Talkerchat)",
        d="Compra reportada = ticket fechado com esse motivo (o que o atendente ou o bot registrou). Confirmada = o CPF aparece no CTN com filiação até 3 dias antes ou depois do fechamento. Desde 01/10 é registro da operação (expander 📋), não etapa do funil: a venda do funil é a do CTN por IDPV, no dia.",
        o="Talkerchat × NOMINAL por CPF", a="📞", s=["Compras reportadas", "Confirmadas no CTN (CPF ±3 d)", "tabulação do atendente"]),
    'Vendas (CTN) por IDPV — WhatsApp humano': dict(sec="WhatsApp (Talkerchat)",
        d="Filiações do CTN (NOMINAL_VENDAS, CPF × data de filiação no período) com tipo Televendas e IDPV de operador humano (telefone ou '… ATENDIMENTO WHATSAPP'; os bots ficam fora). É o cruzamento por IDPV pedido pelo Badaró, lido no dia da filiação. No ranking, o IDPV é casado ao atendente do Talkerchat pelo nome.",
        p="Inclui vendas que o operador fechou por telefone — a fatia 'pelo IDPV WhatsApp' isola a superfície. A régua por telefone (tel-8 × CTN) fica na nota como referência.",
        o="NOMINAL_VENDAS por IDPV (DT_FILIACAO) × alex_idpvs", a="📞", s=["Vendas (CTN) humano", "IDPV WhatsApp", "vendas por IDPV"]),
''', "1) glossário: qualificado / sem SAC / compra reportada / vendas por IDPV")

# ---------------------------------------------------------------------------------------------------------
# 2) variáveis R58 no topo da sub-aba
# ---------------------------------------------------------------------------------------------------------
replace_once('''        tab_per = _tv_val(S, 'abertos')
        tcrm_l = _tv_val(S, 'leads_cpf');''', '''        tab_per = _tv_val(S, 'abertos')
        # R58 (01/10): funil sem SAC · qualificado não cliente · tel-8 × CTN · NOMINAL por IDPV humano/WhatsApp
        tl_ss = _tv_val(S, 'leads_sem_sac'); tl_so = _tv_val(S, 'leads_so_sac'); tq_nc = _tv_val(S, 'qualif_nao_cliente')
        th_ss = _tv_val(S, 'leads_humano_sem_sac'); tq_h = _tv_val(S, 'qualif_humano'); tk_ss = _tv_val(S, 'tickets_sem_sac')
        tl_ctn = _tv_val(S, 'leads_sem_sac_ctn'); tq_ctn = _tv_val(S, 'qualif_ctn'); th_ctn = _tv_val(S, 'humano_ctn')
        tl_ss_p = _tv_val(S, 'leads_sem_sac', meses=_tv_per_p); tq_nc_p = _tv_val(S, 'qualif_nao_cliente', meses=_tv_per_p)
        _r58 = tl_ss is not None
        _nv58_hum = _tv_val(S, 'nv_tv_humano'); _nv58_wpp = _tv_val(S, 'nv_tv_wpp'); _nv58_lia = _tv_val(S, 'nv_lia')
        _nv58_hum_p = _tv_val(S, 'nv_tv_humano', meses=_tv_per_p); _nv58_wpp_p = _tv_val(S, 'nv_tv_wpp', meses=_tv_per_p)
        tcrm_l = _tv_val(S, 'leads_cpf');''', "2) variáveis R58")

# ---------------------------------------------------------------------------------------------------------
# 3) KPIs linha 1
# ---------------------------------------------------------------------------------------------------------
replace_once('''                (f"{_tv_n(tk)} tickets {_tv_delta(tk, tk_p)} · " + f"{tk / tl:.2f}".replace('.', ',') + " por usuário"
                 + (f" · {_tv_n(tlc_id)} contatos (contact_id)" if tlc_id is not None else "")) if tk and tl else "")
        _tv_kpi(k2, "🪪", "Qualificados (com CPF)", f"{_tv_pct(tcpf, tl)}", f"{_tv_n(tcpf)} usuários com CPF capturado nas mensagens")
''', '''                (f"{_tv_n(tk)} tickets {_tv_delta(tk, tk_p)} · " + f"{tk / tl:.2f}".replace('.', ',') + " por usuário"
                 + (f" · {_tv_n(tlc_id)} contatos (contact_id)" if tlc_id is not None else "")
                 + (f" · <b>sem SAC {_tv_n(tl_ss)}</b> {_tv_delta(tl_ss, tl_ss_p)} · só SAC/já cliente {_tv_n(tl_so)}" if _r58 else "")) if tk and tl else "")
        if _r58:
            _tv_kpi(k2, "🪪", "Qualificados (CPF validado, não cliente)", f"{_tv_pct(tq_nc, tl_ss)} {_tv_delta(tq_nc, tq_nc_p)}",
                    f"{_tv_n(tq_nc)} dos {_tv_n(tl_ss)} usuários sem SAC · CPF lido e não cadastrado · piso (ver nota 🧭)")
        else:
            _tv_kpi(k2, "🪪", "Qualificados (com CPF)", f"{_tv_pct(tcpf, tl)}", f"{_tv_n(tcpf)} usuários com CPF capturado nas mensagens")
''', "3a) KPI 1 e 2")

replace_once('''        _tv_kpi(k4, "🛒", "Compras reportadas → confirmadas", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                f"Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)} · {_tv_pct(tconf, tpar)} confirmadas no NOMINAL (CPF ±3 d)")
''', '''        if _r58 and _nv58_hum is not None:
            _tv_kpi(k4, "🏷️", "Vendas (CTN) — humano · Lia", f"{_tv_n(_nv58_hum)} {_tv_delta(_nv58_hum, _nv58_hum_p)} · {_tv_n(_nv58_lia)}",
                    f"NOMINAL por IDPV, venda do dia · pelo IDPV WhatsApp {_tv_n(_nv58_wpp)} {_tv_delta(_nv58_wpp, _nv58_wpp_p)} · "
                    f"compras reportadas no Talkerchat {_tv_n(tcomp)} (registro 📋)", color="#166534")
        else:
            _tv_kpi(k4, "🛒", "Compras reportadas → confirmadas", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                    f"Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)} · {_tv_pct(tconf, tpar)} confirmadas no NOMINAL (CPF ±3 d)")
''', "3b) KPI 4")

# ---------------------------------------------------------------------------------------------------------
# 4) funil + série
# ---------------------------------------------------------------------------------------------------------
replace_once('''        with c1:
            _tv_funil("Funil Talkerchat (WhatsApp)", [
                ("💬", "Tickets", tk, "conversas criadas no período (created_at, fuso BRT)"),
                ("👤", "Usuários únicos", tl, f"telefone_key (tel-8)" + (f" · {_tv_n(tlc_id)} por contact_id" if tlc_id is not None else "")),
                ("🪪", "Qualificados (CPF)", tcpf, "CPF capturado nas mensagens (~75% de acerto) · seq. = % dos usuários únicos"),
                ("🧑‍💼", "Chegaram a um humano", th, "usuários com agent_id em algum ticket — fatia dos usuários únicos (seq. = % deles)", 1),
                ("🛒", "Compra reportada (usuários)", tlc, f"close_reason = 'Compra reportada' · {_tv_n(tcomp)} tickets"),
                ("✅", "Confirmadas no CTN (CPF ±3 d)", tconf, "pares CPF × âncora (fechamento) ±3 d"),
            ], subtitle=_tv_per_lbl)
            _mg7 = _tv_meses_grafico('t6_s7_ano')
''', '''        with c1:
            if _r58:
                _tv_funil("Funil Talkerchat — time humano (WhatsApp, sem SAC)", [
                    ("💬", "Tickets fora do SAC", tk_ss, f"de {_tv_n(tk)} tickets criados no período · fora: Transferido/Redirecionado para o SAC e 'CPF já Cadastrado'"),
                    ("👤", "Usuários únicos sem SAC", tl_ss, f"tel-8 com ao menos um ticket fora do SAC · {_tv_n(tl_so)} usuários só com SAC (já clientes) ficam fora"),
                    ("🪪", "Qualificados (CPF validado, não cliente)", tq_nc, "CPF lido nas mensagens e motivo fora de SAC/já cadastrado · piso (nota 🧭)"),
                    ("🧑‍💼", "Chegaram a um humano", th_ss, "usuários sem SAC com agent_id em algum ticket — fatia dos usuários sem SAC", 1),
                    ("🏷️", "Vendas (CTN) — IDPVs humanos de Televendas", _nv58_hum, "NOMINAL por IDPV do vendedor, venda do dia · % lida sobre os usuários sem SAC", 1),
                    ("📱", "└ pelo IDPV WhatsApp", _nv58_wpp, "IDPV '… ATENDIMENTO WHATSAPP' · fatia das Vendas (CTN) humano", 4),
                ], subtitle=f"{_tv_per_lbl} · venda por IDPV (pedido do Badaró), não por tabulação · Lia à parte, abaixo")
            else:
                _tv_funil("Funil Talkerchat (WhatsApp)", [
                    ("💬", "Tickets", tk, "conversas criadas no período (created_at, fuso BRT)"),
                    ("👤", "Usuários únicos", tl, f"telefone_key (tel-8)" + (f" · {_tv_n(tlc_id)} por contact_id" if tlc_id is not None else "")),
                    ("🪪", "Qualificados (CPF)", tcpf, "CPF capturado nas mensagens (~75% de acerto) · seq. = % dos usuários únicos"),
                    ("🧑‍💼", "Chegaram a um humano", th, "usuários com agent_id em algum ticket — fatia dos usuários únicos (seq. = % deles)", 1),
                    ("🛒", "Compra reportada (usuários)", tlc, f"close_reason = 'Compra reportada' · {_tv_n(tcomp)} tickets"),
                    ("✅", "Confirmadas no CTN (CPF ±3 d)", tconf, "pares CPF × âncora (fechamento) ±3 d"),
                ], subtitle=_tv_per_lbl)
            _mg7 = _tv_meses_grafico('t6_s7_ano')
''', "4a) funil sem SAC")

replace_once('''            _tv_chart_mensal(_tv_long(S, ['compras_lia', 'compras_humano'], meses=_mg7,
                                      labels={'compras_lia': 'Compras Lia (bot)', 'compras_humano': 'Compras humano'}),
                             "Compras reportadas por mês — Lia × humano", subtitle="close_reason = 'Compra reportada'",
                             stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")
        with c2:
''', '''            if _r58:
                _tv_chart_mensal(_tv_long(S, ['leads_sem_sac', 'qualif_nao_cliente', 'leads_humano_sem_sac'], meses=_mg7,
                                          labels={'leads_sem_sac': 'Usuários sem SAC', 'qualif_nao_cliente': 'Qualificados (não cliente)',
                                                  'leads_humano_sem_sac': 'Chegaram a um humano'}),
                                 "Funil por mês — usuários sem SAC × qualificados × humano", subtitle="usuários únicos (tel-8) · colunas lado a lado, não empilhadas",
                                 stacked=False, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api) · motivos de SAC/já cliente fora")
            else:
                _tv_chart_mensal(_tv_long(S, ['compras_lia', 'compras_humano'], meses=_mg7,
                                          labels={'compras_lia': 'Compras Lia (bot)', 'compras_humano': 'Compras humano'}),
                                 "Compras reportadas por mês — Lia × humano", subtitle="close_reason = 'Compra reportada'",
                                 stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")
        with c2:
            if _r58:
                _tv_note(
                    f"<b>Régua nova (01/10, pedido do time de Televendas).</b> O funil parte dos usuários <b>sem SAC</b>: quem só teve tickets "
                    f"'Transferido/Redirecionado para o SAC' ou 'CPF já Cadastrado' já é cliente e fica fora ({_tv_n(tl_so)} usuários, "
                    f"{_tv_pct(tl_so, tl)} do total). <b>Qualificado</b> = CPF lido nas mensagens <i>e</i> motivo fora desses — o 'CPF validado "
                    f"como não cliente'. É um <b>piso</b>: a carga só lê o CPF nos motivos Link enviado, Compra reportada, SAC e CPF já "
                    f"cadastrado; a Lia não grava CPF nas conversas fechadas por fim de expediente, sem interação ou janela encerrada "
                    f"(por isso {_tv_n(tq_h)} dos {_tv_n(tq_nc)} qualificados são de atendente humano). Para subir o piso: estender o "
                    f"<code>CPF_ENRICH</code> do Talkerchat.gs a todos os motivos fora do SAC, ou pedir à D3 o campo CPF / as etiquetas na API.<br><br>"
                    f"<b>Venda</b> = CTN por IDPV (pedido do Badaró), no dia da filiação — inclui o que o operador fechou por telefone; a fatia "
                    f"'pelo IDPV WhatsApp' isola a superfície. Referência pela régua do <b>telefone</b> (tel-8 × CTN no mesmo período, a mesma "
                    f"do Escallo): <b>{_tv_n(tl_ctn)}</b> usuários sem SAC filiaram ({_tv_pct(tl_ctn, tl_ss)}); dos qualificados, {_tv_n(tq_ctn)} "
                    f"({_tv_pct(tq_ctn, tq_nc)}); dos que chegaram a um humano, {_tv_n(th_ctn)} ({_tv_pct(th_ctn, th_ss)}). A compra reportada "
                    f"(tabulação) e a confirmação por CPF ±3 d ficam no expander 📋 abaixo, como registro da operação.",
                    bg="#f0fdf4", icon="🧭")
''', "4b) série mensal + nota 🧭")

# ---------------------------------------------------------------------------------------------------------
# 5) expander "Registro da operação" + rótulo do bloco da Lia
# ---------------------------------------------------------------------------------------------------------
replace_once('''        # ---- R44 (23/09): vendas da Lia no CTN — NOMINAL_VENDAS por IDPV (régua da planilha "Numeros Lia") ----
''', '''        # ---- R58: compra reportada (tabulação do atendente/bot) sai do funil e fica como registro da operação ----
        if _r58:
            with st.expander("📋 Registro da operação — compras reportadas no Talkerchat (tabulação) e confirmação por CPF"):
                st.caption("Mantido a pedido do time para a operação acompanhar a própria classificação. Não é a venda do funil: "
                           "a venda é a do CTN por IDPV, no dia (bloco acima e Fluxo Lia abaixo).")
                e1, e2, e3, e4 = st.columns(4)
                _tv_kpi(e1, "🛒", "Compras reportadas (tickets)", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                        f"close_reason = 'Compra reportada' · {_tv_n(tlc)} usuários", color="#b45309")
                _tv_kpi(e2, "🤖", "Reportadas pela Lia", _tv_n(tlia), f"{_tv_pct(tlia, tcomp)} das reportadas · CTN Lia no período: {_tv_n(_nv58_lia)}", color="#b45309")
                _tv_kpi(e3, "🧑‍💼", "Reportadas por atendente", _tv_n(thum), f"{_tv_pct(thum, tcomp)} das reportadas · CTN humano: {_tv_n(_nv58_hum)}", color="#b45309")
                _tv_kpi(e4, "✅", "Confirmadas por CPF ±3 d", f"{_tv_n(tconf)} · {_tv_pct(tconf, tpar)}",
                        f"de {_tv_n(tpar)} pares CPF × fechamento com CPF lido · janela do ticket, não a venda do dia", color="#b45309")
                _tv_chart_mensal(_tv_long(S, ['compras_lia', 'compras_humano'], meses=_mg7,
                                          labels={'compras_lia': 'Compras Lia (bot)', 'compras_humano': 'Compras humano'}),
                                 "Compras reportadas por mês — Lia × humano", subtitle="close_reason = 'Compra reportada' · relato, não filiação",
                                 stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")

        # ---- R44 (23/09): vendas da Lia no CTN — NOMINAL_VENDAS por IDPV (régua da planilha "Numeros Lia") ----
''', "5a) expander registro da operação")

replace_once('''            _tv_titulo("Vendas da Lia no CTN — NOMINAL por IDPV (LIA - GT7)",
                       f"{_tv_per_lbl} · filiações reais (CPF × data), não o que o bot reportou · régua da planilha de controle do Talkerchat", "A")
''', '''            _tv_titulo("Fluxo Lia — vendas da Lia no CTN, NOMINAL por IDPV (LIA - GT7)",
                       f"{_tv_per_lbl} · frente separada do time humano (o Televendas não responde pela Lia) — comparação lado a lado · "
                       f"filiações reais (CPF × data), não o que o bot reportou · régua da planilha de controle do Talkerchat", "A")
''', "5b) título do bloco da Lia")

replace_once('''            _tv_kpi(n4, "🛒", "Reportadas (Talkerchat) × CTN", f"{_tv_n(tlia)} → {_tv_n(_nv_lia)}",
                    f"compras reportadas da Lia ÷ vendas Lia no CTN = {_tv_pct(tlia, _nv_lia)} · confirmadas por CPF ±3 d: {_tv_n(tconf)}",
                    color="#b45309")
''', '''            if _nv58_wpp is not None:
                _tv_kpi(n4, "📱", "Humano pelo IDPV WhatsApp (CTN)", f"{_tv_n(_nv58_wpp)} {_tv_delta(_nv58_wpp, _nv58_wpp_p)}",
                        f"{_tv_pct(_nv58_wpp, _nv_hum)} do televendas humano · telefone {_tv_n((_nv_hum or 0) - (_nv58_wpp or 0))} · "
                        f"Lia ÷ (Lia + WhatsApp humano) = {_tv_pct(_nv_lia, (_nv_lia or 0) + (_nv58_wpp or 0))}", color="#0f172a")
            else:
                _tv_kpi(n4, "🛒", "Reportadas (Talkerchat) × CTN", f"{_tv_n(tlia)} → {_tv_n(_nv_lia)}",
                        f"compras reportadas da Lia ÷ vendas Lia no CTN = {_tv_pct(tlia, _nv_lia)} · confirmadas por CPF ±3 d: {_tv_n(tconf)}",
                        color="#b45309")
''', "5c) KPI 4 do bloco da Lia")

# ---------------------------------------------------------------------------------------------------------
# 6) sai o funil sales-ready (fases ficam)
# ---------------------------------------------------------------------------------------------------------
replace_once('''            g1, g2 = st.columns([1.9, 1])
            with g1:
                _tv_funil("Qualificação → sales-ready → distribuição", [
                    ("💬", "Tickets", _f_tot, "base da estimativa (meses tocados pelo período)"),
                    ("🪪", "Informaram o CPF (qualificados)", _q_cpf, "CPF nas mensagens ou desfecho da triagem"),
                    ("✅", "Sales-ready", _q_sr, f"CPF não cadastrado → segue para venda (Lia ou humano) · erro amostral {_pp(_e_s)}"),
                    ("🤖", "↳ distribuídos para a Lia", _q_bot, "link de adesão enviado pela Lia · seq. = % dos sales-ready", 2),
                    ("🧑‍💼", "↳ distribuídos para humano", _q_hum, "'Vou conectar você com um consultor…' ou atendente · seq. = % dos sales-ready", 2),
                ], subtitle="estimativa por amostra de mensagens · as duas últimas linhas são fatias dos sales-ready (o resto ficou sem desfecho)")
            with g2:
                _tv_note(f"<b>Como ler.</b> A API não tem campo de handover; o pipeline <code>tkc_fases</code> lê as mensagens de uma amostra "
                         f"(40 tickets por motivo de fechamento × mês) e classifica pelo roteiro: apresentação da Lia → pedido de CPF → desfecho "
                         f"('já está cadastrado' = SAC · 'ainda não é filiado' + link = Lia vendas · 'Vou conectar você com um consultor' = humano). "
                         f"Erro amostral (95%) da fatia Lia vendas: {_pp(_e_v)} no mês. Atualizar: <code>gt7 run tkc_fases --arg meses=AAAA-MM --arg refresh=1</code>.",
                         bg="#f8fafc", icon="ℹ️")
''', '''            # R58 (01/10): o funil "Qualificação → sales-ready → distribuição" saiu a pedido do time (estimativa por amostra);
            #      _q_cpf/_q_sr/_q_bot/_q_hum continuam lidos (s7_fases) caso voltem a ser usados.
            _tv_note(f"<b>Como ler.</b> A API não tem campo de handover; o pipeline <code>tkc_fases</code> lê as mensagens de uma amostra "
                     f"(40 tickets por motivo de fechamento × mês) e classifica pelo roteiro: apresentação da Lia → pedido de CPF → desfecho "
                     f"('já está cadastrado' = SAC · 'ainda não é filiado' + link = Lia vendas · 'Vou conectar você com um consultor' = humano). "
                     f"Erro amostral (95%) da fatia Lia vendas: {_pp(_e_v)} no mês. Atualizar: <code>gt7 run tkc_fases --arg meses=AAAA-MM --arg refresh=1</code>. "
                     f"O funil de sales-ready por amostra saiu em 01/10 (pedido do time) — a qualificação oficial é a do funil acima.",
                     bg="#f8fafc", icon="ℹ️")
''', "6) sales-ready fora")

# ---------------------------------------------------------------------------------------------------------
# 7) ranking de atendentes por Vendas (CTN) por IDPV
# ---------------------------------------------------------------------------------------------------------
replace_once('''                for _c in ['tickets', 'leads', 'compras', 'espera_avg_min', 'duracao_avg_min']:
                    if _c not in _ag.columns:
                        _ag[_c] = 0.0
''', '''                for _c in ['tickets', 'leads', 'compras', 'espera_avg_min', 'duracao_avg_min']:
                    if _c not in _ag.columns:
                        _ag[_c] = 0.0
                _ag58 = _r58 and 'vendas_ctn' in _ag.columns   # R58: vendas (CTN) por IDPV casado ao atendente
                for _c in ['vendas_ctn', 'vendas_ctn_wpp', 'vendas_ctn_tel', 'idpv_n']:
                    if _c not in _ag.columns:
                        _ag[_c] = 0.0
''', "7a) colunas R58 no ranking")

replace_once('''                _ag['taxa'] = (_ag['compras'] / _ag['tickets'].where(_ag['tickets'] > 0) * 100).astype(float)
                _ag = _ag.sort_values(['compras', 'tickets'], ascending=False).reset_index(drop=True)
                _n_ag = len(_ag)
                r1, r2 = st.columns([1.2, 1])
                with r1:
                    _tv_titulo("Ranking de atendentes — compras reportadas", f"{_n_ag} atendentes com ticket no período · {_tv_per_lbl}", "A")
                    _top = _ag.head(15).copy()
                    _top['rotulo'] = _top.apply(lambda r: f"{format_br(r['compras'])} · {r['taxa']:.1f}%".replace('.', ',') if pd.notna(r['taxa']) else format_br(r['compras']), axis=1)
                    fig_ag = px.bar(_top.iloc[::-1], x='compras', y='dim', orientation='h', text='rotulo',
                                    color_discrete_sequence=[_TV_CORES_A[0]], template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig_ag.update_traces(textposition='outside', cliponaxis=False, textfont_size=11)
                    fig_ag.update_layout(height=max(320, 26 * len(_top) + 80), xaxis_title='compras reportadas', yaxis_title='',
                                         showlegend=False, margin=dict(r=90))
                    st.plotly_chart(fig_ag, use_container_width=True)
                    _tv_fonte("API Talkerchat (alex_talkerchat_api) · rótulo = compras · taxa (compras / tickets)")
                with r2:
                    st.markdown("**Tabela completa**")
                    _tab = _ag[['dim', 'tickets', 'leads', 'compras', 'taxa', 'espera_avg_min', 'duracao_avg_min']].copy()
                    _tab['taxa'] = _tab['taxa'].round(1)
                    _tab['espera_avg_min'] = _tab['espera_avg_min'].map(_tv_min)
                    _tab['duracao_avg_min'] = _tab['duracao_avg_min'].map(_tv_min)
                    _tab = _tab.rename(columns={'dim': 'Atendente', 'tickets': 'Tickets', 'leads': 'Usuários', 'compras': 'Compras',
                                                'taxa': 'Taxa %', 'espera_avg_min': 'Espera média', 'duracao_avg_min': 'Duração média'})
                    _st_df(_tab, use_container_width=True, hide_index=True, height=max(320, 26 * len(_top) + 80))
                    st.caption("Só tickets com atendente (agent_id). Espera = criado → assumido; duração = assumido → fechado; "
                               "médias por atendente (ponderadas por tickets quando o período tem mais de um mês/semana).")
''', '''                if _ag58:
                    _ag['venda_col'] = _ag['vendas_ctn'].astype(float)
                    _ag['taxa'] = (_ag['vendas_ctn'] / _ag['leads'].where(_ag['leads'] > 0) * 100).astype(float)
                    _ag.loc[_ag['idpv_n'] <= 0, ['venda_col', 'taxa']] = float('nan')
                    _ag = _ag.sort_values(['venda_col', 'compras', 'tickets'], ascending=False, na_position='last').reset_index(drop=True)
                else:
                    _ag['venda_col'] = _ag['compras'].astype(float)
                    _ag['taxa'] = (_ag['compras'] / _ag['tickets'].where(_ag['tickets'] > 0) * 100).astype(float)
                    _ag = _ag.sort_values(['compras', 'tickets'], ascending=False).reset_index(drop=True)
                _n_ag = len(_ag)
                _sem_idpv = list(_ag.loc[_ag['idpv_n'] <= 0, 'dim']) if _ag58 else []
                r1, r2 = st.columns([1.2, 1])
                with r1:
                    _tv_titulo("Ranking de atendentes — Vendas (CTN) por IDPV" if _ag58 else "Ranking de atendentes — compras reportadas",
                               f"{_n_ag} atendentes com ticket no período · {_tv_per_lbl}"
                               + (f" · {len(_sem_idpv)} sem IDPV casado (no fim da tabela)" if _sem_idpv else ""), "A")
                    _top = _ag.head(15).copy()
                    _top = _top[_top['venda_col'].notna()] if _ag58 else _top
                    _top['rotulo'] = _top.apply(lambda r: f"{format_br(r['venda_col'])} · {r['taxa']:.1f}%".replace('.', ',') if pd.notna(r['taxa']) else format_br(r['venda_col']), axis=1)
                    fig_ag = px.bar(_top.iloc[::-1], x='venda_col', y='dim', orientation='h', text='rotulo',
                                    color_discrete_sequence=[_TV_CORES_A[0]], template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig_ag.update_traces(textposition='outside', cliponaxis=False, textfont_size=11)
                    fig_ag.update_layout(height=max(320, 26 * len(_top) + 80), xaxis_title='vendas (CTN) por IDPV' if _ag58 else 'compras reportadas',
                                         yaxis_title='', showlegend=False, margin=dict(r=90))
                    st.plotly_chart(fig_ag, use_container_width=True)
                    _tv_fonte("NOMINAL_VENDAS tipo Televendas por IDPV (telefone + WhatsApp), IDPV casado ao atendente pelo nome · rótulo = vendas · "
                              "taxa (vendas / usuários atendidos)" if _ag58 else
                              "API Talkerchat (alex_talkerchat_api) · rótulo = compras · taxa (compras / tickets)")
                with r2:
                    st.markdown("**Tabela completa**")
                    if _ag58:
                        _tab = _ag[['dim', 'tickets', 'leads', 'vendas_ctn', 'vendas_ctn_wpp', 'taxa', 'compras', 'espera_avg_min', 'duracao_avg_min']].copy()
                        _tab.loc[_ag['idpv_n'] <= 0, ['vendas_ctn', 'vendas_ctn_wpp']] = float('nan')
                    else:
                        _tab = _ag[['dim', 'tickets', 'leads', 'compras', 'taxa', 'espera_avg_min', 'duracao_avg_min']].copy()
                    _tab['taxa'] = _tab['taxa'].round(1)
                    _tab['espera_avg_min'] = _tab['espera_avg_min'].map(_tv_min)
                    _tab['duracao_avg_min'] = _tab['duracao_avg_min'].map(_tv_min)
                    _tab = _tab.rename(columns={'dim': 'Atendente', 'tickets': 'Tickets', 'leads': 'Usuários', 'compras': 'Reportadas (Talkerchat)' if _ag58 else 'Compras',
                                                'vendas_ctn': 'Vendas (CTN)', 'vendas_ctn_wpp': 'das quais IDPV WhatsApp',
                                                'taxa': 'Taxa %', 'espera_avg_min': 'Espera média', 'duracao_avg_min': 'Duração média'})
                    _st_df(_tab, use_container_width=True, hide_index=True, height=max(320, 26 * len(_top) + 80))
                    _cap58 = (("Vendas (CTN) = NOMINAL tipo Televendas no período pelos IDPVs do atendente (telefone e WhatsApp), casados pelo nome "
                               "(Talkerchat grava 'Nome Sobrenome'; o CTN, o nome completo). Taxa = vendas ÷ usuários atendidos no WhatsApp — "
                               "lembrando que o IDPV também recebe vendas fechadas por telefone. 'Reportadas' = tabulação do atendente (registro). "
                               + (f"Sem IDPV casado: {', '.join(_sem_idpv)}. " if _sem_idpv else "")) if _ag58 else "")
                    st.caption(_cap58 + "Só tickets com atendente (agent_id). Espera = criado → assumido; duração = assumido → fechado; "
                               "médias por atendente (ponderadas por tickets quando o período tem mais de um mês/semana).")
''', "7b) ranking por vendas (CTN)")

write_app(text, bom, crlf)
print("R58 aplicada — app.py gravado")
