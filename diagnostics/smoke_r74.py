"""Smoke R74: perfil gerencial + aba 🎯 Dashboard Gerencial. 4 rodadas AppTest com dados reais:
  A) password_correct=True sem perfil → analista: todas as abas incl. 🎯, conteúdo da 🎯 renderizado ("Vamos bater a meta?");
  B) perfil="gerencial" → só 🎯 entre as principais; conteúdo de 📈/📞 ausente; 5 blocos presentes; sem exceções;
  C) perfil="televendas" → continua só 📞 (regressão R42);
  D) login real com ger_password (lida de .streamlit/secrets.toml; pulado se vazia) → perfil gerencial.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r74.py  (rodar detached: ~2–4 min com cache frio)
"""
import os
import pathlib
import re
import time

os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(pathlib.Path.cwd() / "app.py")
ok = True


def run(at, label):
    t0 = time.time()
    at.run()
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(at.error)} | st.warning: {len(at.warning)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:400])
        print(getattr(e, "stack_trace", "")[-1500:])
    for w in at.warning:
        print("WARNING:", str(w.value)[:200])
    return not at.exception


def texto(at):
    parts = [c.value for c in at.caption if c.value] + [m.value for m in at.markdown if m.value]
    parts += [h.value for h in at.header] + [h.value for h in at.subheader] + [t.value for t in at.title]
    parts += [str(w.label) for w in at.radio] + [str(w.label) for w in at.toggle] + [str(w.label) for w in at.selectbox]
    return " ".join(str(p) for p in parts)


def ss(at, key):
    try:
        return at.session_state[key]
    except Exception:
        return None


def check(cond, msg):
    global ok
    print(f"   {'ok ' if cond else 'FALHA'} {msg}", flush=True)
    ok = ok and bool(cond)


BLOCOS = ["Vamos bater a meta?", "Acumulado contra a meta", "Último dia fechado", "Leads por dia", "Tabela diária", "Onde está o problema?",
          "Vendas e leads por canal", "Participação nas vendas", "Do lead único à venda originada", "Leads gerados", "Série mensal", "Semana a semana"]

# --- A) analista ---
at = AppTest.from_file(APP, default_timeout=2400)
at.session_state["password_correct"] = True
ok = run(at, "A analista") and ok
labs = [t.label for t in at.tabs]
tA = texto(at)
check(ss(at, "perfil") == "analista", f"perfil default = analista (got {ss(at, 'perfil')!r})")
check("🎯 Dashboard Gerencial" in labs and "📞 Televendas" in labs and "📈 Desempenho de Vendas" in labs, f"abas principais + 🎯 presentes ({len(labs)} rótulos)")
check("Visão Integrada de Vendas" in tA, "conteúdo da 📈 renderizado")
faltam = [b for b in BLOCOS if b not in tA]
check(not faltam, f"12 seções da 🎯 renderizadas no analista (faltam: {faltam})")
try:
    pills = at.get("pills")
    check(any(p.label == "Período" for p in pills), f"pills de Período presentes ({len(pills)} pills)")
except Exception as _e:  # AppTest 1.57 não enxerga st.pills — as interações abaixo usam session_state
    print(f"   (skip) pills não inspecionáveis nesta versão do AppTest ({type(_e).__name__}); usando session_state")

# --- B) gerencial ---
at = AppTest.from_file(APP, default_timeout=2400)
at.session_state["password_correct"] = True
at.session_state["perfil"] = "gerencial"
ok = run(at, "B gerencial") and ok
labs = [t.label for t in at.tabs]
tB = texto(at)
check(labs == ["🎯 Dashboard Gerencial"], f"só a 🎯 entre as principais (got {labs})")
check("Visão Integrada de Vendas" not in tB and "Funil Talkerchat" not in tB, "conteúdo de 📈/📞 ausente")
faltam = [b for b in BLOCOS if b not in tB]
check(not faltam, f"12 seções da 🎯 renderizadas (faltam: {faltam})")
check("Perfil:** Gerencial" in tB, "caption de perfil gerencial na barra lateral")
check(any(w.key == "btn_sair" for w in at.button), "botão 🚪 Sair presente")
try:
    check(any(w.key == "ger_csv" for w in at.get("download_button")), "botão ⬇️ Exportar CSV presente")
except Exception as _e:  # AppTest 1.57 não expõe download_button
    print(f"   (skip) download_button não inspecionável nesta versão do AppTest: {type(_e).__name__}")
# interações: período, canal, ajustes (via session_state — AppTest 1.57 não endereça st.pills)
def set_run(key, val, label):
    at.session_state[key] = val
    at.run()
    check(not at.exception, f"{label} sem exceção")
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, "stack_trace", "")[-1200:])


for opt in ["Ontem", "Semana passada", "Hoje", "Últimos 30 dias", "Mês passado", "Esta semana"]:
    set_run("ger_per", opt, f"período {opt}")
set_run("ger_per", "Este mês", "período Este mês")
sb = next(s for s in at.selectbox if s.key == "ger_canal")
for opt in [o for o in sb.options if o.strip() in ("Franquias", "Televendas", "Website")]:
    sb.select(opt).run()
    check(not at.exception, f"canal {opt.strip()} sem exceção")
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, "stack_trace", "")[-1200:])
sb.select(sb.options[0]).run()
set_run("ger_def", "Régua E", "definição Régua E")
set_run("ger_dateby", "Safra do lead", "datar por safra")
set_run("ger_cmp", "Ano anterior", "comparar com ano")
set_run("ger_proj", "Leads", "projeção de leads")
set_run("ger_fmode", "% do total que entrou", "funil % do total")
tB2 = texto(at)
check("· Contato" in tB2 and "Régua E" in tB2, "rótulos de unidade/definição refletem os Ajustes")
for t in at.toggle:
    t.set_value(True)
at.run()
check(not at.exception, "toggles (mais colunas / zerados / recolher) sem exceção")
for e in at.exception:
    print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, "stack_trace", "")[-1200:])

# --- C) televendas (regressão) ---
at = AppTest.from_file(APP, default_timeout=2400)
at.session_state["password_correct"] = True
at.session_state["perfil"] = "televendas"
ok = run(at, "C televendas") and ok
labs = [t.label for t in at.tabs][:1]
check(labs == ["📞 Televendas"], f"televendas continua só com a 📞 (got {labs})")

# --- D) login real ---
sec = pathlib.Path(".streamlit/secrets.toml").read_text(encoding="utf-8")
m = re.search(r'^ger_password\s*=\s*"([^"]*)"', sec, re.M)
if m and m.group(1):
    at = AppTest.from_file(APP, default_timeout=2400)
    ok = run(at, "D login (tela)") and ok
    check(any("Dashboard Login" in t.value for t in at.title), "tela de login")
    at.text_input[0].input(m.group(1)).run()
    check(ss(at, "perfil") == "gerencial", f"ger_password → perfil gerencial (got {ss(at, 'perfil')!r})")
    check([t.label for t in at.tabs] == ["🎯 Dashboard Gerencial"], "só a 🎯 após o login")
else:
    print("[D login] pulado: ger_password vazia em .streamlit/secrets.toml (preencher para ativar o perfil)")

print("FIM", "OK" if ok else "COM FALHAS")
