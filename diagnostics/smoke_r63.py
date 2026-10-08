"""Smoke R63: 📞 Televendas — 'Vendas (CTN) atribuídas' (IDPV humano + no dia da ligação) × 'Vendas assistidas' nas sub-abas 1, 2 e 3;
bloco 'Vendas confirmadas (janela do contato)' fora da sub-aba 2. Exige o televendas_dash R63 recarregado (s1, s10, s11).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r63.py
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
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    for k in ("Vendas (CTN) atribuídas", "Vendas assistidas — dos discados"):
        i = t.find(k); print("   ", t[i:i + 150] if i >= 0 else f"   (sem {k!r})", flush=True)
    return ok


NOVOS = ["Vendas (CTN) atribuídas", "Vendas assistidas", "Vendas (CTN) atribuídas — dos discados", "Vendas assistidas — dos discados",
         "no dia de uma ligação atendida"]
ANTIGOS = ["Vendas confirmadas (janela do contato) por canal creditado", "Vendas encontradas (janela do contato",
           "Vendas (CTN) — dos discados"]   # '└ com tipo Televendas (CTN)' continua na 🧲 (escada R34) — não testar

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, NOVOS, ANTIGOS)
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26)"):
    sys.exit(1)
# Televendas_REL002 (receptivo) só guarda o mês corrente (carga da TI) → set/26 não tem vendas_atrib no s10: a sub-aba 2 fica no
# layout R45 nesse período (sem 'no dia de uma ligação atendida'); as sub-abas 1 e 3 têm a régua nova.
ok = checa(at, [s for s in NOVOS if s != "no dia de uma ligação atendida"], ANTIGOS) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
