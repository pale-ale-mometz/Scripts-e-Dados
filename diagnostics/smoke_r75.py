"""Smoke R75/R75c: sub-aba 📣 8 · Mídia do app (Singular) — Semana Atual e Último Mês; sem exceções e com os blocos A–E presentes.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r75.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(at.error)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1500])
    for e in at.error:
        if 'singular' in e.value.lower() or 'vw_' in e.value.lower():
            print("ST.ERROR:", e.value[:300])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    t += " " + " ".join(i.value for i in at.info if i.value)
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes=()):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    return ok


NOVOS = ["Mídia do app — campanhas, CPI, ritmo da meta e efeito cruzado", "Instalações pagas (atribuídas a mídia)",
         "CPI das campanhas de Download — Android", "A · Campanhas de Download", "B · Ritmo da meta de instalações",
         "C · Efeito cruzado", "D · Conciliação de custo", "Rede diz × SDK vê",
         "E · O que a instalação vira", "Curva de retenção por rede", "Cadastro em 7 dias por rede"]
AUSENTES = ["vw_singular_campanha_dia` vazia ou inexistente", "Falha ao ler `vw_singular_campanha_dia`", "Coortes ainda indisponíveis"]
at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, NOVOS, AUSENTES)
n_df, n_pl = len(at.dataframe), len(at.get("plotly_chart"))
print(f"   dataframes {n_df} · plotly {n_pl}")
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês"):
    sys.exit(1)
ok = checa(at, NOVOS, AUSENTES) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
