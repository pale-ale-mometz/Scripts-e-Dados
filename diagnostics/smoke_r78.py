"""Smoke R78: aba 📞 — funil do Talkerchat pela regra receptivo × ativo. Último Mês (out/26 fechado): sem exceções; a nota 📌 e o
bloco 📣 aparecem; usuários únicos do funil = 173.848 (224.760 contando tudo); tickets no total 314.271; sub-aba 9 com a regra na fonte.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r78.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(at.error)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1800])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    try:
        t += " " + " ".join(x.label for x in at.expander)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes=()):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    return ok


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, ["O que conta neste funil", "Envios nossos (tickets ativos)", "Ticket receptivo × ativo (Talkerchat)", "os números vão até ontem", "vem do cadastro do contato no Talkerchat"],
           ausentes=["O agregado ainda não tem o funil pela regra receptivo × ativo", "tkcWorker a cada 10 min"])
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (out/26)"):
    sys.exit(1)
t = texto(at)
ok = checa(at, ["O que conta neste funil", "314.271 tickets ao todo", "239.260 receptivos", "74.992 envios nossos", "6.311 com resposta",
                "68.681 envios sem resposta ficaram fora", "224.760 contando tudo, 173.848 no funil",
                "Tickets de disparo em massa", "Envios sem resposta (fora do funil)",
                "tickets = conversas iniciadas pelo cliente + envios nossos com resposta"]) and ok
m = re.search(r"Usuários únicos \(tel-8\) no período\s*([\d\.]+)", t)
p = bool(m) and m.group(1) == "173.848"; ok = ok and p
print(f"   {'OK ' if p else 'FALHA'} KPI Usuários únicos = {m.group(1) if m else None} (esperado 173.848)", flush=True)
tb = [d for d in at.dataframe if 'Disparo' in list(getattr(d.value, 'columns', []))]
p = bool(tb) and len(tb[0].value) == 30 and int(tb[0].value['Enviados'].sum()) == 74434 and int(tb[0].value['Responderam'].sum()) == 6034
ok = ok and p
print(f"   {'OK ' if p else 'FALHA'} tabela de disparos: {len(tb[0].value) if tb else None} linhas, enviados "
      f"{int(tb[0].value['Enviados'].sum()) if tb else None}, responderam {int(tb[0].value['Responderam'].sum()) if tb else None} "
      f"(esperado 30 / 74434 / 6034)", flush=True)
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
