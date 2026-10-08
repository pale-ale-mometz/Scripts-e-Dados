"""R61 (07/10/2026) — sub-aba 💬 4 · Talkerchat: tira os textos de "piso" do qualificado. O backfill de CPF pelo objeto de
contato da API (tkc_cpf_backfill + Talkerchat.gs v1.4.1) terminou em 07/10 00:51 — 385.041 telefones desde abr/26, 179.5 k com
CPF — e o S7 foi recarregado (televendas_dash --only=s7, 01:07). Só texto: glossário (d/p/o), legendas dos KPIs e do funil,
notas 🧭 das duas réguas (sem SAC e por fila). Idempotente (marker 'backfill concluído 07/10').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r61_piso_cpf_completo.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "backfill concluído 07/10"
if MARKER in text:
    print("  = R61 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# 1) glossário — verbete 'Qualificado (CPF validado, não cliente)'
replace_once('''        d="Usuário sem SAC cujo CPF foi lido nas mensagens e que não foi barrado como cliente (motivo do ticket fora de 'Transferido/Redirecionado para o SAC' e 'CPF já Cadastrado').''',
             '''        d="Usuário sem SAC cujo CPF foi lido (objeto de contato 'Dados pessoais' da API; mensagens como reserva) e que não foi barrado como cliente (motivo do ticket fora de 'Transferido/Redirecionado para o SAC' e 'CPF já Cadastrado').''',
             "1a) glossário · definição")
replace_once('''        p="Até 05/10 a carga só lia o CPF (nas mensagens) em 4 motivos — piso. Desde o Talkerchat.gs v1.4 o CPF vem do objeto de contato da API ('Dados pessoais') para todos os motivos, com backfill desde abr/26; a série sobe à medida que o backfill avança.",''',
             '''        p="Cobertura: CPF pelo objeto de contato da API para todos os motivos de fechamento, histórico completo de abr/26 em diante (backfill concluído 07/10). Quem fecha a conversa sem informar os dados fica sem CPF — não é limite de leitura, é o que o cliente chegou a informar. Até 05/10 a carga só lia o CPF nas mensagens de 4 motivos (piso); recargas anteriores a essa data subestimavam a série.",''',
             "1b) glossário · pegadinha")
replace_once('''        o="Talkerchat (leitura das mensagens) + motivo de fechamento", a="📞", s=["Qualificados", "Qualificado (com CPF)", "CPF validado"]),''',
             '''        o="Talkerchat (objeto de contato da API + mensagens) + motivo de fechamento", a="📞", s=["Qualificados", "Qualificado (com CPF)", "CPF validado"]),''',
             "1c) glossário · origem")

# 2) KPI (régua sem SAC)
replace_once('''                    f"{_tv_n(tq_nc)} dos {_tv_n(tl_ss)} usuários sem SAC · CPF lido e não cadastrado · piso (ver nota 🧭)")''',
             '''                    f"{_tv_n(tq_nc)} dos {_tv_n(tl_ss)} usuários sem SAC · CPF lido (objeto de contato) e não cadastrado · ver nota 🧭")''',
             "2) KPI qualificados")

# 3) degrau do funil (régua sem SAC)
replace_once('''                    ("🪪", "Qualificados (CPF validado, não cliente)", tq_nc, "CPF lido nas mensagens e motivo fora de SAC/já cadastrado · piso (nota 🧭)"),''',
             '''                    ("🪪", "Qualificados (CPF validado, não cliente)", tq_nc, "CPF lido (objeto de contato) e motivo fora de SAC/já cadastrado (nota 🧭)"),''',
             "3) funil · degrau qualificados")

# 4) nota 🧭 por fila (R60)
replace_once('''                    f"<b>Qualificado</b> = CPF lido e não cadastrado (objeto de contato da API; backfill em andamento). "''',
             '''                    f"<b>Qualificado</b> = CPF lido e não cadastrado (objeto de contato da API; histórico completo desde abr/26). "''',
             "4) nota 🧭 por fila")

# 5) nota 🧭 régua sem SAC (R58/R58b)
replace_once('''                    f"{_tv_pct(tl_so, tl)} do total). <b>Qualificado</b> = CPF lido nas mensagens <i>e</i> motivo fora desses — o 'CPF validado "
                    f"como não cliente'. É um <b>piso</b>: a carga só lê o CPF nos motivos Link enviado, Compra reportada, SAC e CPF já "
                    f"cadastrado; a Lia não grava CPF nas conversas fechadas por fim de expediente, sem interação ou janela encerrada "
                    f"(por isso {_tv_n(tq_h)} dos {_tv_n(tq_nc)} qualificados são de atendente humano). <b>Em correção desde 05/10:</b> a API "
                    f"passou a expor o objeto de contato (CPF estruturado) e o Talkerchat.gs v1.4 lê o CPF de lá para todos os motivos — o backfill "
                    f"desde abr/26 está em andamento e os qualificados sobem a cada recarga.<br><br>"''',
             '''                    f"{_tv_pct(tl_so, tl)} do total). <b>Qualificado</b> = CPF lido <i>e</i> motivo fora desses — o 'CPF validado "
                    f"como não cliente'. O CPF vem do objeto de contato da API ('Dados pessoais', preenchido no fluxo da conversa; as mensagens "
                    f"ficam como reserva) e vale para todos os motivos de fechamento — histórico completo de abr/26 em diante "
                    f"(backfill concluído 07/10). Quem fecha a conversa sem informar os dados fica sem CPF: não é limite de leitura, é o que "
                    f"o cliente chegou a informar. {_tv_n(tq_h)} dos {_tv_n(tq_nc)} qualificados passaram por atendente humano.<br><br>"''',
             "5) nota 🧭 régua sem SAC")

write_app(text, bom, crlf)
print("R61 aplicada")
