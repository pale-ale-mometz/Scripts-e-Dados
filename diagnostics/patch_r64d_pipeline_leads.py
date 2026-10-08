"""R64d (08/10/2026) — 📞 sub-aba 3 (HubSpot): o funil do pipeline ("Pipeline CDT - Lead Televendas", abaixo do unificado) ainda dizia
"Contatos no fluxo do televendas" no 1º degrau; passa a "Leads enviados ao televendas em horário comercial" (mesma unidade: Contato do HubSpot com
data_de_entrada_no_fluxo_do_televendas no período), alinhado ao KPI 1 e ao funil unificado (R64/R64b). Só rótulos.
Idempotente (marker 'Negócios dos leads enviados').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r64d_pipeline_leads.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "Negócios dos leads enviados"
if MARKER in text:
    print("  = R64d já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


replace_once('''                _tv_funil("Pipeline CDT - Lead Televendas · Negócios dos Contatos no fluxo, por estágio", [
                    ("🚪", "Contatos no fluxo do televendas" + ("" if _t5_fe else " (no expediente)"), fluxo,
                     "Contato: data_de_entrada_no_fluxo_do_televendas no período"''',
             '''                _tv_funil("Pipeline CDT - Lead Televendas · Negócios dos leads enviados ao televendas, por estágio", [
                    ("🚪", "Leads enviados ao televendas" + ("" if _t5_fe else " em horário comercial"), fluxo,
                     "Contato do HubSpot com data_de_entrada_no_fluxo_do_televendas no período"''',
             "1) funil do pipeline · título + degrau 1")
replace_once('''                ], subtitle="os estágios são fatias dos Negócios dos Contatos no fluxo (um Negócio pode entrar em vários no período) · do topo = % dos Contatos")''',
             '''                ], subtitle="os estágios são fatias dos Negócios dos leads enviados (Contatos do HubSpot; um Negócio pode entrar em vários estágios no período) · do topo = % dos leads enviados")''',
             "2) funil do pipeline · subtítulo")

write_app(text, bom, crlf)
print("R64d aplicada")
