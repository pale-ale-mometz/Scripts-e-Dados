"""Smoke R77: explicadores (📡 7 guia + utm_source top 3 · 🎯 5 consistência · 📣 8 guia e conciliação Jampp · 📨 CRM aviso AQUI e de-para)
— Semana Atual e Último Mês; sem exceções e com os textos novos presentes.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r77.py
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
        print("ST.ERROR:", e.value[:200])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    t += " " + " ".join(i.value for i in at.info if i.value)
    t += " " + " ".join(x.label for x in at.expander if getattr(x, 'label', None))
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes=()):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    return ok


NOVOS = ["Como esta sub-aba é construída",                       # 📡 7 expander
         "Os dois SDKs contam",                                    # 📡 7 nota 📏 nova
         "Mesma definição do funil",                               # 🎯 5
         "Guia desta sub-aba",                                     # 📣 8 expander
         "Singular = campanhas de Download (+ RTGT da Jampp)",     # 📣 8 bloco D subtítulo
         "E · O que a instalação vira",                            # 📣 8 bloco E
         "Número (de-para)"]                                       # 📨 CRM legenda da tabela por UTM
AUSENTES = ["Coortes ainda indisponíveis", "Falha ao ler `vw_singular_campanha_dia`"]
at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, NOVOS, AUSENTES)
# tabela 'Mídia (utm_source agrupado)' com a coluna nova e aviso AQUI na 📨 (depende de haver disparos 'CDT - AQUI' nos últimos 12 meses)
t = texto(at)
print("   " + ("OK " if "utm_source (top 3)" in t else "AVISO sem") + " coluna 'utm_source (top 3)' (_st_mt renderiza em markdown/HTML)")
print("   " + ("OK " if "Templates de aquisição fora da régua GT7" in t else "AVISO sem") + " aviso AQUI fora da régua (📨)")
print(f"   dataframes {len(at.dataframe)} · plotly {len(at.get('plotly_chart'))}")
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês"):
    sys.exit(1)
ok = checa(at, NOVOS, AUSENTES) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
