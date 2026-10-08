"""R64b (08/10): rótulos do topo do funil unificado (pedido do Álex) — 1º degrau "Leads enviados ao televendas em horário comercial"
(no lugar de "(no expediente)"), 2º degrau "↳ Leads que viraram Negócio na esteira do televendas (no período)" com nota em português simples;
o KPI 1 da sub-aba 3 acompanha. Idempotente (marker 'em horário comercial').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r64b_rotulos_horario_comercial.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
if "em horário comercial" in text:
    print("  = R64b já aplicada"); sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x"); sys.exit(1)
    text = text.replace(old, new); print(f"  + {label}")


replace_once('''        _tv_kpi(k1, "🚪", "Leads enviados ao televendas" + ("" if _t5_fe else " (no expediente)"), _tv_n(fluxo),''',
             '''        _tv_kpi(k1, "🚪", "Leads enviados ao televendas" + ("" if _t5_fe else " em horário comercial"), _tv_n(fluxo),''',
             "1) KPI 1")
replace_once('''                ("🚪", "Leads enviados ao televendas (no expediente)", u_ne,
                 f"Contatos do HubSpot que entraram no fluxo do televendas no período; {_tv_n(u_fe)} fora do expediente ficam fora · "''',
             '''                ("🚪", "Leads enviados ao televendas em horário comercial", u_ne,
                 f"Contatos do HubSpot que entraram no fluxo do televendas no período; {_tv_n(u_fe)} que entraram fora do expediente ficam fora · "''',
             "2) degrau 1")
replace_once('''                ("🤝", "↳ Leads com Negócio que entrou em LEAD no período", u_lead,
                 "fatia dos leads enviados (conta Contatos, não Negócios — o funil do pipeline abaixo conta Negócios de qualquer Contato/coorte)", 0),''',
             '''                ("🤝", "↳ Leads que viraram Negócio na esteira do televendas (no período)", u_lead,
                 "fatia dos leads enviados: têm pelo menos um Negócio que entrou no estágio LEAD da pipeline do televendas no período ('virou card'). "
                 "Conta leads, não Negócios — o funil da pipeline mais abaixo conta Negócios de qualquer lead, inclusive enviados em meses anteriores ou fora do expediente", 0),''',
             "3) degrau 2")
write_app(text, bom, crlf)
print("R64b aplicada")
