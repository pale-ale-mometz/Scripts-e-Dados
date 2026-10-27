"""Smoke R77b: aba 📨 CRM — régua do 3535 em três visões (mês set/2026): Fora = R$ 28.697,28 (GT7) · Todo o 3535 = Só aquisição = R$ 33.905,60
(+ R$ 5.208,32 dos 3 templates 'CDT - AQUI' de 24–28/09). Sem exceções; funil segue a régua.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r77b.py
"""
import os, sys, time, pathlib, re
import pandas as pd
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
    t += " " + " ".join(w.value for w in at.warning if w.value)
    return re.sub(r'\s+', ' ', t)


def gasto_set(at):
    """'Valor gasto — set/26 1–30' no KPI: pega o R$ que segue o rótulo."""
    t = texto(at)
    m = re.search(r'Valor gasto — set/26 1–30\s*R\$\s*([\d\.\,]+)', t)
    return m.group(1) if m else None


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual · Fora"):
    sys.exit(1)
ok = True
mes = at.selectbox(key='t8_mes'); mes.set_value(pd.Timestamp('2026-09-01'))
if not run(at, "set/26 · Fora"):
    sys.exit(1)
g = gasto_set(at); print(f"   Fora (GT7): gasto set/26 = {g}"); ok = ok and (g == "28.697,28")
rad = at.radio(key='t8_reg_3535')
for opt, esperado in (("Todo o 3535", "33.905,60"), ("Só 3535 de aquisição ('AQUI'/'GT7' no nome)", "33.905,60")):
    rad.set_value(opt)
    if not run(at, f"set/26 · {opt}"):
        sys.exit(1)
    g = gasto_set(at); t = texto(at)
    p = g == esperado; ok = ok and p
    print(f"   {'OK ' if p else 'FALHA'} {opt}: gasto set/26 = {g} (esperado {esperado})")
    p2 = "Régua do gasto:" in t and "Templates de aquisição fora da régua GT7" not in t; ok = ok and p2
    print(f"   {'OK ' if p2 else 'FALHA'} caption da régua presente e aviso AQUI ausente")
    p3 = "Instância de Aquisição (templates GT7 + " in t; ok = ok and p3
    print(f"   {'OK ' if p3 else 'FALHA'} funil com escopo rotulado pela régua")
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
