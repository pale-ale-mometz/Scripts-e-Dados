"""R58b (05/10/2026) — sub-aba 💬 4 · Talkerchat: textos do piso do "qualificado" depois da reverificação da API.
A API pública ganhou GET /contact-object/{telefone}/values (objeto "Dados pessoais" com CPF); o Talkerchat.gs v1.4 passa a
ler o CPF de lá para todos os motivos (+ backfill desde abr/26). Só texto: nota 🧭 e verbete do glossário.
Idempotente (marker 'objeto de contato da API'). Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r58b_cpf_objeto_contato.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "objeto de contato da API"
if MARKER in text:
    print("  = R58b já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


replace_once('''(por isso {_tv_n(tq_h)} dos {_tv_n(tq_nc)} qualificados são de atendente humano). Para subir o piso: estender o "
                    f"<code>CPF_ENRICH</code> do Talkerchat.gs a todos os motivos fora do SAC, ou pedir à D3 o campo CPF / as etiquetas na API.<br><br>"''',
'''(por isso {_tv_n(tq_h)} dos {_tv_n(tq_nc)} qualificados são de atendente humano). <b>Em correção desde 05/10:</b> a API "
                    f"passou a expor o objeto de contato (CPF estruturado) e o Talkerchat.gs v1.4 lê o CPF de lá para todos os motivos — o backfill "
                    f"desde abr/26 está em andamento e os qualificados sobem a cada recarga.<br><br>"''',
             "1) nota 🧭")

replace_once('''        p="Piso: a carga só lê o CPF nos motivos Link enviado, Compra reportada, SAC e CPF já cadastrado; conversas da Lia fechadas por fim de expediente / sem interação / janela encerrada não têm CPF lido.",''',
'''        p="Até 05/10 a carga só lia o CPF (nas mensagens) em 4 motivos — piso. Desde o Talkerchat.gs v1.4 o CPF vem do objeto de contato da API ('Dados pessoais') para todos os motivos, com backfill desde abr/26; a série sobe à medida que o backfill avança.",''',
             "2) glossário")

write_app(text, bom, crlf)
print("R58b aplicada")
