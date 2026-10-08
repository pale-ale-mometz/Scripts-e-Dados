"""R60 (05/10/2026) — sub-aba 💬 4 · Talkerchat: funil por FILA (Triagem × Televendas), válido de 30/09 em diante.

Desde 30/09 a triagem da Lia roda na fila "Triagem" e o ticket que recebe "quero ser cliente" troca de fila (mesmo id) para
Televendas. Logo `queue = 'Televendas'` = intenção de compra declarada — um "qualificado" que não depende de CPF. O pipeline
(televendas_dash S7, R60) grava leads_fila_tv*, leads_so_triagem*, leads_outras_filas, tickets_triagem/_fila_tv_lia/_fila_tv_humano.
No app, quando os usuários que ficaram só na Triagem são >= 30 % dos usuários do período (`_fila_ok`), a sub-aba troca:
  * KPI 3 → "Triagem × Lia vendas × humano — tickets (por fila)";
  * funil → Tickets → Usuários únicos → Chegaram à fila Televendas → Qualificados (CPF validado) → Chegaram a um humano (fatia) →
    Vendas (CTN) — IDPVs humanos (% sobre quem chegou à fila) → └ IDPV WhatsApp;
  * nota 🧭 com a leitura por fila (triagem → SAC × inatividade, outras filas) e a referência tel-8 × CTN.
Períodos anteriores (set/26 e antes) continuam com o funil "sem SAC" do R58. Idempotente (marker `_fila_ok =`).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r60_talkerchat_fila_triagem.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "_fila_ok ="
if MARKER in text:
    print("  = R60 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# 1) variáveis
replace_once('''        _r58 = tl_ss is not None
''', '''        _r58 = tl_ss is not None
        # R60 (05/10): métricas por fila (Triagem × Televendas), válidas de 30/09 em diante
        tl_ftv = _tv_val(S, 'leads_fila_tv'); tl_ftv_h = _tv_val(S, 'leads_fila_tv_humano'); tl_ftv_q = _tv_val(S, 'leads_fila_tv_qualif')
        tl_ftv_qh = _tv_val(S, 'leads_fila_tv_qualif_humano'); tl_ftv_ctn = _tv_val(S, 'leads_fila_tv_ctn'); tl_ftv_hctn = _tv_val(S, 'leads_fila_tv_humano_ctn')
        tl_ftv_cli = _tv_val(S, 'leads_fila_tv_so_cliente'); tl_tri = _tv_val(S, 'leads_so_triagem'); tl_tri_sac = _tv_val(S, 'leads_so_triagem_sac')
        tl_out = _tv_val(S, 'leads_outras_filas'); tk_tri = _tv_val(S, 'tickets_triagem'); tk_ftv_lia = _tv_val(S, 'tickets_fila_tv_lia')
        tk_ftv_h = _tv_val(S, 'tickets_fila_tv_humano')
        tl_ftv_p = _tv_val(S, 'leads_fila_tv', meses=_tv_per_p); tl_ftv_q_p = _tv_val(S, 'leads_fila_tv_qualif', meses=_tv_per_p)
        _fila_ok = bool(_r58 and tl_ftv is not None and tl and (tl_tri or 0) >= 0.3 * tl)   # fluxo com fila Triagem dominante no período
''', "1) variáveis R60")

# 2) KPI 2 e 3
replace_once('''        if _r58:
            _tv_kpi(k2, "🪪", "Qualificados (CPF validado, não cliente)", f"{_tv_pct(tq_nc, tl_ss)} {_tv_delta(tq_nc, tq_nc_p)}",
                    f"{_tv_n(tq_nc)} dos {_tv_n(tl_ss)} usuários sem SAC · CPF lido e não cadastrado · piso (ver nota 🧭)")
        else:''', '''        if _fila_ok:
            _tv_kpi(k2, "🪪", "Chegaram à fila Televendas · qualificados (CPF)", f"{_tv_pct(tl_ftv, tl)} {_tv_delta(tl_ftv, tl_ftv_p)} · {_tv_pct(tl_ftv_q, tl_ftv)}",
                    f"{_tv_n(tl_ftv)} usuários disseram 'quero ser cliente' na triagem · {_tv_n(tl_ftv_q)} com CPF validado (não cliente) "
                    f"{_tv_delta(tl_ftv_q, tl_ftv_q_p)} · {_tv_n(tl_ftv_cli)} barrados depois (CPF já cadastrado)")
        elif _r58:
            _tv_kpi(k2, "🪪", "Qualificados (CPF validado, não cliente)", f"{_tv_pct(tq_nc, tl_ss)} {_tv_delta(tq_nc, tq_nc_p)}",
                    f"{_tv_n(tq_nc)} dos {_tv_n(tl_ss)} usuários sem SAC · CPF lido e não cadastrado · piso (ver nota 🧭)")
        else:''', "2a) KPI 2")

replace_once('''        if tk_sac is not None:  # agregado já traz a separação triagem → SAC × Lia vendas (18/09)
            _tv_kpi(k3, "🤖", "Lia (vendas) × triagem → SAC × humano — tickets",''', '''        if _fila_ok:
            _tv_kpi(k3, "🤖", "Triagem × Lia vendas × humano — tickets (por fila)",
                    f"{_tv_pct(tk_tri, tk)} · {_tv_pct(tk_ftv_lia, tk)} · {_tv_pct(tk_ftv_h, tk)}",
                    f"{_tv_n(tk_tri)} ficaram na fila Triagem · {_tv_n(tk_ftv_lia)} na fila Televendas só com a Lia · {_tv_n(tk_ftv_h)} com atendente · "
                    f"usuários: {_tv_pct(tl_tri, tl)} ficaram na triagem ({_tv_pct(tl_tri_sac, tl_tri)} deles redirecionados ao SAC)", color="#2e8a4f")
        elif tk_sac is not None:  # agregado já traz a separação triagem → SAC × Lia vendas (18/09)
            _tv_kpi(k3, "🤖", "Lia (vendas) × triagem → SAC × humano — tickets",''', "2b) KPI 3")

# 3) funil
replace_once('''        with c1:
            if _r58:
                _tv_funil("Funil Talkerchat — time humano (WhatsApp, sem SAC)", [''', '''        with c1:
            if _fila_ok:
                _tv_funil("Funil Talkerchat — time humano (fila Televendas)", [
                    ("💬", "Tickets", tk, f"conversas criadas no período · {_tv_n(tk_tri)} ficaram na fila Triagem"),
                    ("👤", "Usuários únicos", tl, f"tel-8 · {_tv_n(tl_tri)} só na Triagem ({_tv_n(tl_tri_sac)} redirecionados ao SAC) · {_tv_n(tl_out)} em outras filas"),
                    ("🎯", "Chegaram à fila Televendas", tl_ftv, "disseram 'quero ser cliente' na triagem — o ticket troca de fila (intenção de compra declarada)"),
                    ("🪪", "Qualificados (CPF validado, não cliente)", tl_ftv_q, f"CPF lido e não cadastrado · {_tv_n(tl_ftv_cli)} barrados como 'CPF já cadastrado' · fatia dos que chegaram à fila", 2),
                    ("🧑‍💼", "Chegaram a um humano", tl_ftv_h, "agent_id em algum ticket — fatia dos que chegaram à fila", 2),
                    ("🏷️", "Vendas (CTN) — IDPVs humanos de Televendas", _nv58_hum, "NOMINAL por IDPV do vendedor, venda do dia · % lida sobre quem chegou à fila", 2),
                    ("📱", "└ pelo IDPV WhatsApp", _nv58_wpp, "IDPV '… ATENDIMENTO WHATSAPP' · fatia das Vendas (CTN) humano", 5),
                ], subtitle=f"{_tv_per_lbl} · fila Triagem desde 30/09 · venda por IDPV (pedido do Badaró) · Lia à parte, abaixo")
            elif _r58:
                _tv_funil("Funil Talkerchat — time humano (WhatsApp, sem SAC)", [''', "3) funil por fila")

# 4) nota 🧭
replace_once('''        with c2:
            if _r58:
                _tv_note(
                    f"<b>Régua nova (01/10, pedido do time de Televendas).</b>''', '''        with c2:
            if _fila_ok:
                _tv_note(
                    f"<b>Funil por fila (desde 30/09).</b> A triagem da Lia passou a rodar na fila <b>Triagem</b>: quem escolhe 'quero ser cliente' "
                    f"tem o ticket movido para a fila <b>Televendas</b> (mesmo ticket); quem não escolhe fica na Triagem e fecha como "
                    f"'Redirecionado para o SAC' (outros assuntos / já cliente) ou 'Inatividade'. Por isso o topo útil do funil é "
                    f"<b>chegaram à fila Televendas</b> = intenção de compra declarada — não depende de o CPF ter sido lido. No período: "
                    f"{_tv_n(tl_tri)} usuários ({_tv_pct(tl_tri, tl)}) ficaram na Triagem, {_tv_n(tl_tri_sac)} deles redirecionados ao SAC; "
                    f"{_tv_n(tl_out)} ({_tv_pct(tl_out, tl)}) passaram só por outras filas (Pré-venda automático, NPS, TIM).<br><br>"
                    f"<b>Qualificado</b> = CPF lido e não cadastrado (objeto de contato da API; backfill em andamento). "
                    f"<b>Venda</b> = CTN por IDPV (pedido do Badaró), no dia. Referência pela régua do telefone (tel-8 × CTN no mesmo período): "
                    f"<b>{_tv_n(tl_ftv_ctn)}</b> dos que chegaram à fila filiaram ({_tv_pct(tl_ftv_ctn, tl_ftv)}); dos que chegaram a um humano, "
                    f"{_tv_n(tl_ftv_hctn)} ({_tv_pct(tl_ftv_hctn, tl_ftv_h)}). Dos usuários da fila Televendas, {_tv_pct(tl_ftv_h, tl_ftv)} "
                    f"chegaram a um atendente — o resto ficou com a Lia (link de adesão). Set/26 e antes seguem a régua 'sem SAC' (R58): "
                    f"os dois funis não são comparáveis no topo. Compra reportada e CPF ±3 d no expander 📋.",
                    bg="#f0fdf4", icon="🧭")
            elif _r58:
                _tv_note(
                    f"<b>Régua nova (01/10, pedido do time de Televendas).</b>''', "4) nota 🧭 por fila")

# 5) série mensal: por fila quando disponível
replace_once('''            if _r58:
                _tv_chart_mensal(_tv_long(S, ['leads_sem_sac', 'qualif_nao_cliente', 'leads_humano_sem_sac'], meses=_mg7,''', '''            if _fila_ok:
                _tv_chart_mensal(_tv_long(S, ['leads_so_triagem', 'leads_fila_tv', 'leads_fila_tv_qualif', 'leads_fila_tv_humano'], meses=_mg7,
                                          labels={'leads_so_triagem': 'Só na Triagem', 'leads_fila_tv': 'Chegaram à fila Televendas',
                                                  'leads_fila_tv_qualif': 'Qualificados (CPF)', 'leads_fila_tv_humano': 'Chegaram a um humano'}),
                                 "Funil por mês — por fila (desde 30/09)", subtitle="usuários únicos (tel-8) · meses anteriores a out/26 ficam em zero (a fila Triagem não existia)",
                                 stacked=False, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api) · queue")
            elif _r58:
                _tv_chart_mensal(_tv_long(S, ['leads_sem_sac', 'qualif_nao_cliente', 'leads_humano_sem_sac'], meses=_mg7,''', "5) série por fila")

# 6) glossário
replace_once('''    'Usuário sem SAC': dict(sec="WhatsApp (Talkerchat)",''', '''    'Fila Triagem / fila Televendas': dict(sec="WhatsApp (Talkerchat)",
        d="Desde 30/09 a triagem da Lia roda na fila Triagem. Quem escolhe 'quero ser cliente' tem o ticket movido para a fila Televendas (mesmo ticket) — é a intenção de compra declarada, o topo do funil do time humano. Quem não escolhe fica na Triagem (Redirecionado para o SAC ou Inatividade). Outras filas: Pré-venda (automático), SAC Coleta NPS, TIM Reaquecimento.",
        p="Válido de out/26 em diante; set/26 e antes usam a régua 'sem SAC' e não são comparáveis no topo.",
        o="Talkerchat (queue)", a="📞", s=["Triagem", "Chegaram à fila Televendas", "intenção declarada", "quero ser cliente"]),
    'Usuário sem SAC': dict(sec="WhatsApp (Talkerchat)",''', "6) glossário")

write_app(text, bom, crlf)
print("R60 aplicada")
