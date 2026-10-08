"""R62 (08/10/2026) — sub-aba 💬 4 · Talkerchat: fila "SAC" nova (desde 04/10) e motivo 189 "Informou que já é cliente".
A triagem passou a mover para a fila SAC quem já é cliente (~5 k tickets/dia, 0 humano); a fila Triagem caiu para ~2 k/dia. O pipeline
(televendas_dash R62) passou a contar fila SAC e motivo 189 como SAC/já cliente (TKC_CLI_IDS, TKC_SAC_PRED; fila_tri = Triagem ou SAC;
métrica nova tickets_fila_sac). Aqui: só texto — glossário (2 verbetes), KPI 3, degraus do funil por fila e sem SAC, nota 🧭 por fila
e nota 🧭 sem SAC, subtítulo do gráfico "Tickets por mês". Variável nova tk_fsac (tickets na fila SAC). Idempotente (marker 'tk_fsac').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r62_fila_sac.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "tk_fsac"
if MARKER in text:
    print("  = R62 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# 1) glossário — 'Fila Triagem / fila Televendas'
replace_once('''Quem não escolhe fica na Triagem (Redirecionado para o SAC ou Inatividade). Outras filas: Pré-venda (automático), SAC Coleta NPS, TIM Reaquecimento.",''',
             '''Quem não escolhe fica na Triagem (Inatividade) ou, desde 04/10, é movido para a fila SAC ('Informou que já é cliente' / 'Redirecionado para o SAC') — Triagem e SAC juntas são o 'ficou na triagem' do funil. Outras filas: Pré-venda (automático), SAC Coleta NPS, TIM Reaquecimento.",''',
             "1a) glossário · fila Triagem")
replace_once('''        o="Talkerchat (queue)", a="📞", s=["Triagem", "Chegaram à fila Televendas", "intenção declarada", "quero ser cliente"]),''',
             '''        o="Talkerchat (queue)", a="📞", s=["Triagem", "fila SAC", "Chegaram à fila Televendas", "intenção declarada", "quero ser cliente"]),''',
             "1b) glossário · sinônimos")
# 2) glossário — 'Usuário sem SAC'
replace_once('''        d="Usuário único (tel-8) com ao menos um ticket no período fora dos motivos de SAC (Transferido/Redirecionado para o SAC) e de 'CPF já Cadastrado'. Quem só teve tickets desses motivos já é cliente e fica fora do funil (o volume aparece na nota do topo).",
        o="Talkerchat (close_reason_id 4, 174, 186, 5)", a="📞", s=["sem SAC", "só SAC", "Leads sem SAC"]),''',
             '''        d="Usuário único (tel-8) com ao menos um ticket no período fora dos motivos de SAC/já cliente (Transferido/Redirecionado para o SAC, 'Informou que já é cliente' — desde 04/10 — e 'CPF já Cadastrado') e fora da fila SAC. Quem só teve tickets desses já é cliente e fica fora do funil (o volume aparece na nota do topo).",
        o="Talkerchat (close_reason_id 4, 174, 186, 189, 5 ou queue = 'SAC')", a="📞", s=["sem SAC", "só SAC", "Leads sem SAC"]),''',
             "2) glossário · Usuário sem SAC")
# 3) variável nova + KPI 3 (por fila)
replace_once('''        tk_ftv_h = _tv_val(S, 'tickets_fila_tv_humano')
''', '''        tk_ftv_h = _tv_val(S, 'tickets_fila_tv_humano')
        tk_fsac = _tv_val(S, 'tickets_fila_sac')   # R62: fila SAC (desde 04/10) — já clientes movidos pela triagem; conta em tk_tri
''', "3a) variável tk_fsac")
replace_once('''                    f"{_tv_n(tk_tri)} ficaram na fila Triagem · {_tv_n(tk_ftv_lia)} na fila Televendas só com a Lia · {_tv_n(tk_ftv_h)} com atendente · "
                    f"usuários: {_tv_pct(tl_tri, tl)} ficaram na triagem ({_tv_pct(tl_tri_sac, tl_tri)} deles redirecionados ao SAC)", color="#2e8a4f")''',
             '''                    f"{_tv_n(tk_tri)} ficaram na triagem (filas Triagem/SAC" + (f", {_tv_n(tk_fsac)} na SAC" if tk_fsac else "") + f") · {_tv_n(tk_ftv_lia)} na fila Televendas só com a Lia · "
                    f"{_tv_n(tk_ftv_h)} com atendente · usuários: {_tv_pct(tl_tri, tl)} ficaram na triagem ({_tv_pct(tl_tri_sac, tl_tri)} deles já clientes / SAC)", color="#2e8a4f")''',
             "3b) KPI 3 por fila")
# 4) degraus do funil por fila
replace_once('''                    ("💬", "Tickets", tk, f"conversas criadas no período · {_tv_n(tk_tri)} ficaram na fila Triagem"),
                    ("👤", "Usuários únicos", tl, f"tel-8 · {_tv_n(tl_tri)} só na Triagem ({_tv_n(tl_tri_sac)} redirecionados ao SAC) · {_tv_n(tl_out)} em outras filas"),''',
             '''                    ("💬", "Tickets", tk, f"conversas criadas no período · {_tv_n(tk_tri)} ficaram na triagem (filas Triagem/SAC)"),
                    ("👤", "Usuários únicos", tl, f"tel-8 · {_tv_n(tl_tri)} só na triagem ({_tv_n(tl_tri_sac)} já clientes / SAC) · {_tv_n(tl_out)} em outras filas"),''',
             "4) funil por fila · degraus 1–2")
# 5) degraus do funil sem SAC
replace_once('''                    ("💬", "Tickets fora do SAC", tk_ss, f"de {_tv_n(tk)} tickets criados no período · fora: Transferido/Redirecionado para o SAC e 'CPF já Cadastrado'"),''',
             '''                    ("💬", "Tickets fora do SAC", tk_ss, f"de {_tv_n(tk)} tickets criados no período · fora: Transferido/Redirecionado para o SAC, 'Informou que já é cliente', 'CPF já Cadastrado' e a fila SAC"),''',
             "5) funil sem SAC · degrau 1")
# 6) subtítulo do gráfico "Tickets por mês"
replace_once('''                             subtitle="close_reason 4 (Transferido para SAC) = triagem · agent_id = humano · resto = Lia" if tk_sac is not None else "attended_by_bot / agent_id da API",''',
             '''                             subtitle="motivos SAC / já cliente (4, 174, 186, 189) ou fila SAC = triagem → SAC · agent_id = humano · resto = Lia" if tk_sac is not None else "attended_by_bot / agent_id da API",''',
             "6) subtítulo tickets por mês")
# 7) nota 🧭 por fila
replace_once('''                    f"tem o ticket movido para a fila <b>Televendas</b> (mesmo ticket); quem não escolhe fica na Triagem e fecha como "
                    f"'Redirecionado para o SAC' (outros assuntos / já cliente) ou 'Inatividade'. Por isso o topo útil do funil é "
                    f"<b>chegaram à fila Televendas</b> = intenção de compra declarada — não depende de o CPF ter sido lido. No período: "
                    f"{_tv_n(tl_tri)} usuários ({_tv_pct(tl_tri, tl)}) ficaram na Triagem, {_tv_n(tl_tri_sac)} deles redirecionados ao SAC; "''',
             '''                    f"tem o ticket movido para a fila <b>Televendas</b> (mesmo ticket); quem não escolhe fica na Triagem ('Inatividade') ou, "
                    f"desde 04/10, é movido para a fila <b>SAC</b> ('Informou que já é cliente' / 'Redirecionado para o SAC' — outros assuntos, já "
                    f"cliente). Por isso o topo útil do funil é <b>chegaram à fila Televendas</b> = intenção de compra declarada — não depende "
                    f"de o CPF ter sido lido. No período: {_tv_n(tl_tri)} usuários ({_tv_pct(tl_tri, tl)}) ficaram na triagem (Triagem + SAC), "
                    f"{_tv_n(tl_tri_sac)} deles já clientes / SAC; "''',
             "7) nota 🧭 por fila")
# 8) nota 🧭 sem SAC
replace_once('''                    f"<b>Régua nova (01/10, pedido do time de Televendas).</b> O funil parte dos usuários <b>sem SAC</b>: quem só teve tickets "
                    f"'Transferido/Redirecionado para o SAC' ou 'CPF já Cadastrado' já é cliente e fica fora ({_tv_n(tl_so)} usuários, "''',
             '''                    f"<b>Régua nova (01/10, pedido do time de Televendas).</b> O funil parte dos usuários <b>sem SAC</b>: quem só teve tickets "
                    f"'Transferido/Redirecionado para o SAC', 'Informou que já é cliente' (desde 04/10, fila SAC) ou 'CPF já Cadastrado' já é cliente e fica fora ({_tv_n(tl_so)} usuários, "''',
             "8) nota 🧭 sem SAC")

write_app(text, bom, crlf)
print("R62 aplicada")
