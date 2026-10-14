"""Smoke R64e: vocabulário novo também fora do funil, nos fallbacks e no glossário. Semana Atual (sem fallback) e Último Mês (set/26: o
receptivo cai no fallback "atribuídas + assistidas" porque o REL002 só tem o mês corrente).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r64e.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(at.error)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1500])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    try:
        t += " " + " ".join(tb.label for tb in at.tabs)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    return ok


NOVOS = ["Régua 4 · Escallo · atribuídas + assistidas",   # (rótulo da série "antes de filiar" é do plotly, não do markdown)
         "Leads enviados ao televendas em horário comercial", "Vendas (CTN) atribuídas"]
ANTIGOS = ["Contatos no fluxo antes de filiar", "Vendas confirmadas pelo Escallo (janela do contato)", "Funil HubSpot (Contatos)",
           "Contatos no fluxo do televendas", "Conversão dos Contatos do fluxo", "Vendas confirmadas (janela do contato) por canal creditado",
           "Compras reportadas → confirmadas", "Compra reportada (usuários)", "Qualificados (com CPF)"]

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, NOVOS, ANTIGOS + ["atribuídas + assistidas, dos discados"])
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26)"):
    sys.exit(1)
# set/26: receptivo sem vendas_atrib (REL002 só tem o mês corrente) → fallback com o vocabulário novo
ok = checa(at, NOVOS + ["Vendas (CTN) — atribuídas + assistidas", "separação atribuída × assistida indisponível"],
           ANTIGOS + ["Régua 'Vendas (CTN)' da R45"]) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
