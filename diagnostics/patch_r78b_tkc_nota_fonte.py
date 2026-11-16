"""R78b (16/11/2026) — aba 📞, sub-aba 7 · Talkerchat: nota "Fonte" atualizada.

A nota ainda descrevia a carga pelo GAS (tkcDaily 06h + tkcWorker a cada 10 min) e o CPF lido das mensagens. Estado real em 16/11/2026:
  - tickets: carga diária pelo Nekt (notebook-192d, Talkerchat tickets + CPF) a partir das ~06:10, desde 10/11/2026;
  - conversas: notebook-vl5s às 08:10, que também grava a origem do ticket (receptivo × ativo) desde 16/11;
  - CPF: objeto de contato da API (cpf_source = 'contact', desde 05/10); a leitura das mensagens ficou como reserva; filas SAC e
    SAC Coleta NPS não são consultadas;
  - a API pública segue sem etiquetas, equipe, CEP e sem o número de WhatsApp da conversa (conexão).
Só texto (nota e comentário de cabeçalho). Exige R78. Idempotente. Backup em app_bak_r78b.py.
Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r78b_tkc_nota_fonte.py
"""
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _patchlib import APP, read_app, write_app  # noqa: E402

text, bom, crlf = read_app()
orig = text
changes = []


def once(old, new, label):
    global text
    if new in text:
        changes.append(f"= {label} (já aplicado)")
        return
    n = text.count(old)
    assert n == 1, f"{label}: esperado 1 ocorrência, achei {n}"
    text = text.replace(old, new)
    changes.append(f"+ {label}")


once('''                "<b>Fonte: API pública do Talkerchat</b> (<code>alex_talkerchat_api</code>, carga GAS: <code>tkcDaily</code> 06h + "
                "<code>tkcWorker</code> a cada 10 min; frescor D-1, histórico desde 16/04/2026). Horários em America/Sao_Paulo — "
                "o export CSV antigo gravava UTC como hora local (heatmap deslocado 3 h). "
                "Perdas em relação ao export: etiquetas, equipe e CEP não vêm pela API; o CPF é lido das mensagens "
                "(<code>cpf_source = 'messages'</code>, ~75% dos tickets com motivo de compra/cadastro) até a D3 expor o campo. "
                "Compras confirmadas por CPF ±3 dias no NOMINAL.",
''', '''                "<b>Fonte: API pública do Talkerchat</b> (<code>alex_talkerchat_api</code>, uma linha por ticket, histórico desde "
                "16/04/2026). A carga roda uma vez por dia, de manhã, pelo Nekt (tickets a partir das ~06:10; conversas completas às "
                "08:10) e o painel é recalculado às 09:30: os números vão <b>até ontem</b> e o dia de hoje aparece incompleto. "
                "Horários em America/Sao_Paulo. O que a API não traz: etiquetas, equipe, CEP e o número de WhatsApp pelo qual a "
                "conversa entrou. O <b>CPF</b> vem do cadastro do contato no Talkerchat (preenchido durante a conversa); a leitura do "
                "CPF no texto das mensagens ficou só como reserva, e as filas SAC e SAC Coleta NPS não são consultadas. A <b>origem "
                "do ticket</b> (receptivo × envio nosso) vem da primeira mensagem de cada conversa. "
                "Compras confirmadas por CPF ±3 dias no NOMINAL.",
''', "nota Fonte da sub-aba 7")

once("    # Grão: segue _tvd (semana quando o período é curto). Frescor D-1 (tkcDaily 06h + tkcWorker 10 min; recarga 11:00).\n",
     "    # Grão: segue _tvd (semana quando o período é curto). Frescor D-1 (Nekt: notebook-192d ~06:10, notebook-vl5s 08:10;\n"
     "    # recarga_televendas 09:30). R78: funil pela regra receptivo × ativo (seções s7f_*).\n", "comentário de cabeçalho")

if text != orig:
    bak = APP.with_name("app_bak_r78b.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
