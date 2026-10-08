"""R64 (08/10/2026) — 📞 sub-aba 3 (HubSpot): (1) nomenclatura para o time de Televendas — "Contatos" viram **"Leads enviados ao
televendas"** no KPI 1 e no funil unificado (a nota diz que são Contatos do HubSpot), "Discados no Escallo" vira "Leads discados no Escallo",
para que "quantos leads foram enviados / ligados / converteram" seja lido direto no funil; (2) controle de duplicados FORA do funil
(caption 🔁): leads enviados × leads com telefone × números únicos (tel-8) × leads que dividem telefone com outro lead do período
(métricas R64 do s11: leads_com_telefone, telefones_unicos, leads_telefone_repetido). Idempotente (marker 'Leads enviados ao televendas').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\patch_r64_leads_enviados_duplicados.py
"""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
MARKER = "Leads enviados ao televendas"
if MARKER in text:
    print("  = R64 já aplicada")
    sys.exit(0)


def replace_once(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        print(f"ERRO: {label}: ancora encontrada {n}x")
        sys.exit(1)
    text = text.replace(old, new)
    print(f"  + {label}")


# 1) KPI 1 da sub-aba 3
replace_once('''        _tv_kpi(k1, "🚪", "Contatos que entraram no fluxo" + ("" if _t5_fe else " (no expediente)"), _tv_n(fluxo),
                f"data_de_entrada_no_fluxo_do_televendas no período · "''',
             '''        _tv_kpi(k1, "🚪", "Leads enviados ao televendas" + ("" if _t5_fe else " (no expediente)"), _tv_n(fluxo),
                f"Contatos do HubSpot com data_de_entrada_no_fluxo_do_televendas no período · "''',
             "1a) KPI 1")
replace_once('''                f"{_tv_pct(_ent['LEAD'], fluxo)} dos Contatos do fluxo viraram um Negócio no período (1º estágio da esteira, LEAD)")''',
             '''                f"{_tv_pct(_ent['LEAD'], fluxo)} dos leads enviados viraram um Negócio no período (1º estágio da esteira, LEAD)")''',
             "1b) KPI 2 caption")

# 2) funil unificado — rótulos
replace_once('''        u_atrib = _tv_val(S11, 'vendas_atrib_discados'); u_hum = _tv_val(S11, 'vendas_ctn_discados_tv_humano')   # R63
''', '''        u_atrib = _tv_val(S11, 'vendas_atrib_discados'); u_hum = _tv_val(S11, 'vendas_ctn_discados_tv_humano')   # R63
        u_tel_c = _tv_val(S11, 'leads_com_telefone'); u_tel_u = _tv_val(S11, 'telefones_unicos'); u_tel_rep = _tv_val(S11, 'leads_telefone_repetido')   # R64
''', "2a) vars duplicados")
replace_once('''            _tv_funil("🔗 Funil unificado · do Contato no HubSpot à venda no CTN (passando pela discagem)", [
                ("🚪", "Contatos no fluxo do televendas (no expediente)", u_ne,
                 f"entraram no fluxo no período; {_tv_n(u_fe)} fora do expediente ficam fora · {_tv_pct(u_tel, u_ne)} destes com telefone na ponte "
                 f"tel-8 (alex_tv_contato_tel: phone / WhatsApp com ≥ 8 dígitos) — só esses podem ser casados com o Escallo e o CTN"),
                ("🤝", "↳ Contatos com Negócio que entrou em LEAD no período", u_lead,
                 "fatia dos Contatos (conta Contatos, não Negócios — o funil do pipeline abaixo conta Negócios de qualquer Contato/coorte)", 0),
                ("📞", "Discados no Escallo (ativo, mesmo período)", u_disc,
                 f"tel-8 do Contato × ESCALLO_LEADS_MES ATIVO · {_tv_n(u_disc_neg)} deles com Negócio LEAD no período, "
                 f"{_tv_n((u_disc or 0) - (u_disc_neg or 0)) if u_disc is not None else '—'} sem · seq. = % dos Contatos", 0),''',
             '''            _tv_funil("🔗 Funil unificado · do lead enviado ao televendas (Contato no HubSpot) à venda no CTN", [
                ("🚪", "Leads enviados ao televendas (no expediente)", u_ne,
                 f"Contatos do HubSpot que entraram no fluxo do televendas no período; {_tv_n(u_fe)} fora do expediente ficam fora · "
                 f"{_tv_pct(u_tel, u_ne)} destes com telefone na ponte tel-8 (phone / WhatsApp com ≥ 8 dígitos) — só esses podem ser casados com o Escallo e o CTN"),
                ("🤝", "↳ Leads com Negócio que entrou em LEAD no período", u_lead,
                 "fatia dos leads enviados (conta Contatos, não Negócios — o funil do pipeline abaixo conta Negócios de qualquer Contato/coorte)", 0),
                ("📞", "Leads discados no Escallo (ativo, mesmo período)", u_disc,
                 f"tel-8 do lead × ESCALLO_LEADS_MES ATIVO · {_tv_n(u_disc_neg)} deles com Negócio LEAD no período, "
                 f"{_tv_n((u_disc or 0) - (u_disc_neg or 0)) if u_disc is not None else '—'} sem · seq. = % dos leads enviados", 0),''',
             "2b) funil · rótulos")
replace_once('''            st.caption("Por que 'com Negócio LEAD' aqui difere de 'Viraram Negócio na esteira' no funil do pipeline (abaixo): aqui a unidade é o "
                       "Contato que entrou no fluxo neste período e no expediente, contado uma vez mesmo com vários Negócios; lá a unidade é o "''',
             '''            if u_tel_u is not None:
                st.caption(f"🔁 Controle de duplicados (fora do funil): {_tv_n(u_ne)} leads enviados → {_tv_n(u_tel_c)} com telefone → "
                           f"<b>{_tv_n(u_tel_u)} números únicos</b> (tel-8); {_tv_n(u_tel_rep)} leads ({_tv_pct(u_tel_rep, u_tel_c)}) dividem o telefone "
                           f"com outro lead enviado no mesmo período — mesma pessoa entrando mais de uma vez (automação, formulário repetido, "
                           f"cadastro duplicado). O funil conta Contatos; o Escallo disca números.", unsafe_allow_html=True)
            st.caption("Por que 'com Negócio LEAD' aqui difere de 'Viraram Negócio na esteira' no funil do pipeline (abaixo): aqui a unidade é o "
                       "lead (Contato do HubSpot) que entrou no fluxo neste período e no expediente, contado uma vez mesmo com vários Negócios; lá a unidade é o "''',
             "2c) caption duplicados + unidade")
replace_once('''            st.caption(f"Um Contato só, do HubSpot ao CTN: entrou no fluxo → (Negócio) → foi discado no Escallo → conversou → tabulação → filiou. "
                       f"Fora do funil: {_tv_n(u_v_nd)} Contatos do fluxo filiaram no período sem discagem ativa (site, WhatsApp, receptivo, campo); "''',
             '''            st.caption(f"Um lead só (Contato do HubSpot), do HubSpot ao CTN: foi enviado ao televendas → (Negócio) → foi discado no Escallo → conversou → tabulação → filiou. "
                       f"Fora do funil: {_tv_n(u_v_nd)} leads enviados filiaram no período sem discagem ativa (site, WhatsApp, receptivo, campo); "''',
             "2d) caption leitura")

write_app(text, bom, crlf)
print("R64 aplicada")
