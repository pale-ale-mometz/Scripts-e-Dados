# -*- coding: utf-8 -*-
"""🎯 Dashboard Gerencial — aba do Vendas Dashboard (R74, 21/10/2026).

Porta para o Streamlit o blueprint "Metas Comerciais CDT v6" (Claude Design, 21/10/2026): 5 blocos que respondem, nesta ordem,
"Vamos bater a meta?" (01 Meta do mês), "Estamos melhorando ou piorando?" (02 Dia a dia), "Onde está o problema?" (03 Canais),
"Os leads estão chegando e convertendo?" (04 Leads e funil) e "Como chegamos até aqui?" (05 Histórico), com barra própria de
Período · Canal · Ajustes · Legenda · Exportar CSV. É a única aba do perfil "gerencial" (senha `ger_password`) e também aparece
para o perfil analista.

Fontes (todas já carregadas pelo app.py ou agregadas por pipeline — nada pesado roda ao vivo):
  vendas ............ df_raw (RESUMO_VENDAS_DIARIAS por dia × tipo_venda, 3 anos) — a mesma régua de todas as abas de vendas.
  metas de vendas ... df_goals (alex_metas, mensal, por canal); meta parcial = meta × dias ÷ dias do mês (linear).
  leads / pipe / transbordados (meta de outubro) ... alex_leads_diario (Leads Únicos = Contato; "Pipe Televendas" = Negócios que
                      entraram na distribuição [D5]; "Transbordados Franquia" = Negócios, 1ª entrada em Distribuição/Validador).
  jornada por dia ... alex_ger_dash_dia (pipeline gt7 run gerencial_dash, sobre alex_funil_journey): leads/encaminhados/transbordados/
                      vendas do lead por dia × bucket de origem (Contato) — funil, heatmap, "Vendas originadas de lead" e as
                      definições alternativas de lead (Régua E, sem importação).
  projeção .......... df_fcst (FORECAST_VENDAS_CANAL, Prophet, cenário balanced) para vendas; ritmo por dia da semana (mediana dos
                      últimos 28 dias) para leads — a mesma regra do e-mail "Metas de outubro".
  calendário ........ df_cal (dim_calendario: is_uno / is_duo → "1 Isenção" / "Dupla Isenção" por semana).

Unidades sempre explícitas nos rótulos: Contato (pessoa no HubSpot) · Negócio (card do HubSpot) · Venda (CTN, NOMINAL).
Uso no app.py:  import gerencial_tab; gerencial_tab.render(df_raw=..., df_goals=..., df_fcst=..., df_cal=..., cquery=cquery,
                reference_date=reference_date, perfil=_PERFIL)
"""
from __future__ import annotations

import calendar
import datetime as dt
import html as _html
import math

import numpy as np
import pandas as pd
import streamlit as st

VERSAO = "R74 · 21/10/2026"

# ------------------------------------------------------------------------------------------------ tokens visuais do blueprint
BG, INK, MUTED, MUTED2, LINE, CARD, SOFT = "#DFE1D6", "#151515", "#5C5A50", "#737065", "#E2E1D9", "#FFFFFF", "#F4F3EE"
GREEN, DARK, GREY, LIGHT, LIME, SAND, BAR = "#00A463", "#302F29", "#8A877B", "#D6D4C8", "#DDFB44", "#A29F91", "#E2E1D9"
TONE = {"ok": ("#006B41", "#E3FFED"), "warn": ("#9D6000", "#FFF5EB"), "bad": ("#B7453B", "#FFF4F2"), "neu": ("#46453D", "#EDECE6")}
HEAT = ["#C2453A", "#F4B9AF", "#F2D46B", "#A6E1BC", "#00A463"]
ICON = {"ok": "✓", "warn": "!", "bad": "✕"}
DOW = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]          # weekday() 0 = segunda
MES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MES_PT_LONGO = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
HATCH = "repeating-linear-gradient(45deg,#A29F91 0 1.5px,#FFFFFF 1.5px 6px)"

# ------------------------------------------------------------------------------------------------ árvore de canais
# (id, nome, pai, tipo_venda no RESUMO (minúsculas), grupo do Prophet em FORECAST_VENDAS_CANAL, coluna da alex_metas)
CH = [
    ("cdt", "CDT (Total)", None, None, None, "CDT (Total)"),
    ("nac", "Nacional", "cdt", None, None, "Canais Nacionais"),
    ("dig", "Digital", "nac", None, None, None),
    ("web", "Website", "dig", "website", "website", "Site"),
    ("apf", "App do Filiado", "dig", "app do filiado", "app do filiado (no-spend)", "App"),
    ("out", "Outros", "nac", None, None, None),
    ("b2b", "Digital B2B2C", "out", "digital b2b2c", "digital b2b2c", "B2b2c Digital"),
    ("mgm", "MGM", "out", "mgm", "mgm", None),
    ("son", "CDT Sonhos", "out", "cdt sonhos", "outros", None),
    ("smt", "CDT Sonhos Maistodos", "out", "cdt sonhos maistodos", "outros", None),
    ("b2c", "B2B2C", "out", "b2b2c", "outros", None),
    ("inf", "Influenciadores", "out", "influenciadores", "outros", None),
    ("tut", "Tutti", "out", "tutti", "outros", None),
    ("cma", "Carlinhos Maia", "out", "carlinhos maia", "outros", None),
    ("tel", "Televendas", "nac", "televendas", "televendas", "Televendas"),
    ("fra", "Franquias", "cdt", None, "franquias", "Franquias"),
    ("pap", "Porta a Porta", "fra", "porta a porta", "franquias", "PAP"),
    ("lnk", "Link do Vendedor", "fra", "link do vendedor", "franquias", "Link do Vendedor"),
    ("apv", "App do Vendedor", "fra", "app do vendedor", "franquias", "App do Vendedor"),
]
NODE = {}
for _id, _nm, _p, _tipo, _fc, _meta in CH:
    NODE[_id] = dict(id=_id, name=_nm, p=_p, tipo=_tipo, fc=_fc, metacol=_meta, kids=[])
for _c in CH:
    if _c[2]:
        NODE[_c[2]]["kids"].append(_c[0])
for _id, _n in NODE.items():
    d, p = 0, _n["p"]
    while p:
        d += 1
        p = NODE[p]["p"]
    _n["level"] = d
    _n["leaf"] = not _n["kids"]


def leaves_of(cid):
    n = NODE[cid]
    return [cid] if n["leaf"] else [x for k in n["kids"] for x in leaves_of(k)]


def tipos_of(cid):
    return [NODE[x]["tipo"] for x in leaves_of(cid)]


def group_of(cid):
    n = NODE[cid]
    while n["p"] and n["p"] != "cdt":
        n = NODE[n["p"]]
    return None if cid == "cdt" else n["id"]        # 'nac' | 'fra'


def dot_of(cid):
    g = group_of(cid)
    return GREY if g == "fra" else DARK if g == "nac" else INK


LEAVES = [c[0] for c in CH if NODE[c[0]]["leaf"]]
FRA_TIPOS = set(tipos_of("fra"))

# Metas de leads por mês (régua do e-mail "Metas de outubro", 05/10/2026). Fora daqui cai nas colunas da alex_metas
# ('Leads unicos Total' / 'Leads transbordado'), que são OUTRA régua — por isso o mês fica marcado como "régua alex_metas".
METAS_LEADS = {"2026-10": {"leads": 300000, "tr": 145000}}

MNAME = {"vendas": "Vendas", "leads": "Leads Únicos", "enc": "Encaminhados para a distribuição", "tr": "Transbordados para franquias",
         "vo": "Vendas originadas de lead", "web": "Vendas Site", "apf": "Vendas App"}
MSHORT = {"vendas": "Vendas", "leads": "Leads Únicos", "enc": "Pipe Televendas", "tr": "Transbordados Franquia",
          "vo": "Vendas originadas", "web": "Vendas Site", "apf": "Vendas App"}
UNIT = {"vendas": "Venda", "leads": "Contato", "enc": "Negócio", "tr": "Negócio", "vo": "Contato", "web": "Venda", "apf": "Venda"}
BUCKETS_ALL = ["core", "tim", "franquia_promotor", "franquia_facebook", "franquia_cms", "regional", "importacao", "sem_canal", "ruptura"]
BUCKET_NAME = {"core": "Nacional (core)", "tim": "B2B2C – TIM", "franquia_promotor": "Franquia – ID Promotor",
               "franquia_facebook": "Franquia – Facebook", "franquia_cms": "Franquia – CMS", "regional": "Regional",
               "importacao": "Importação (carga de base)", "sem_canal": "Sem canal", "ruptura": "Ruptura"}
LEADDEF = {
    "abr": ("Abrangente", "Oficial (28/09/2026): todos os Contatos criados, de todas as origens, inclusive importação e TIM. "
                          "Leads = alex_leads_diario (Contato); Pipe e Transbordados = Negócios."),
    "e": ("Régua E", "Sugerida, não oficial: exclui B2B2C – TIM e os leads de promotor de franquia (ID Promotor). "
                     "Contagens em Contato pela jornada única."),
    "semimp": ("Sem importação", "Abrangente menos os Contatos criados por carga de base (hs_object_source IMPORT). "
                                 "Contagens em Contato pela jornada única."),
}
LEADDEF_BUCKETS = {"abr": BUCKETS_ALL, "e": [b for b in BUCKETS_ALL if b not in ("tim", "franquia_promotor")],
                   "semimp": [b for b in BUCKETS_ALL if b != "importacao"]}


# ------------------------------------------------------------------------------------------------ formatação
def f0(n):
    try:
        if n is None or (isinstance(n, float) and (math.isnan(n) or math.isinf(n))):
            return "—"
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def fp(x, d=1):
    try:
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return "—"
        return (f"{x * 100:.{d}f}").replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "—"


def fk(n):
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "—"
    a = abs(n)
    if a < 1000:
        return f0(n)
    v = n / 1000
    return (f"{v:.0f}" if a >= 10000 else f"{v:.1f}").replace(".", ",") + " mil"


def fa(n):
    a = abs(n)
    if a < 1000:
        return f0(n)
    v = n / 1000
    s = f"{v:.0f}" if a >= 10000 else f"{v:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + "k"


def sg(d):
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return "—"
    return ("+" if d >= 0 else "−") + fp(abs(d))


def dfmt(d):
    return f"{d.day:02d}/{d.month:02d}"


def drange(a, b):
    if a == b:
        return dfmt(a)
    if a.month == b.month and a.year == b.year:
        return f"{a.day:02d}–{dfmt(b)}"
    return f"{dfmt(a)}–{dfmt(b)}"


def esc(s):
    return _html.escape(str(s), quote=True)


def tip(lines):
    """Tooltip nativo (title=) a partir de uma lista de linhas; linhas vazias são descartadas."""
    return esc("\n".join(str(x) for x in lines if x is not None and str(x) != ""))


def nice(mx):
    raw = max(mx, 1) / 4
    p = 10 ** math.floor(math.log10(raw))
    m = raw / p
    s = 1 if m <= 1 else 2 if m <= 2 else 2.5 if m <= 2.5 else 5 if m <= 5 else 10
    return s * p


def smooth(pts):
    if not pts:
        return ""
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
        d += f" C{c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d, k):
    y, m = d.year, d.month + k
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def weeks_of_month(m0):
    """Semanas seg→dom do mês: 'Pré' (dias antes da 1ª segunda), S1..Sn. Lista de dicts {id, a, b}."""
    n = calendar.monthrange(m0.year, m0.month)[1]
    end = m0.replace(day=n)
    out, cur = [], m0
    first_mon = m0 + dt.timedelta(days=(7 - m0.weekday()) % 7)
    if first_mon > m0:
        out.append({"id": "Pré", "a": m0, "b": min(first_mon - dt.timedelta(days=1), end)})
        cur = first_mon
    k = 1
    while cur <= end:
        b = min(cur + dt.timedelta(days=6), end)
        out.append({"id": f"S{k}", "a": cur, "b": b})
        cur = b + dt.timedelta(days=1)
        k += 1
    return out


# ------------------------------------------------------------------------------------------------ chips HTML
def chip(tone, text, dashed=False, tp=None, icon=None):
    fg, bg = TONE[tone]
    style = (f"display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 9px;border-radius:9999px;font:600 12px/1 Inter,system-ui,sans-serif;"
             f"white-space:nowrap;color:{fg};background:{'transparent' if dashed else bg};border:1.5px {'dashed' if dashed else 'solid'} {fg if dashed else 'transparent'}")
    ic = f"<b style='font-weight:800'>{ICON[icon]}</b>" if icon else ""
    return f"<span class='g-chip' title=\"{tip(tp or [text])}\" style=\"{style}\">{ic}{esc(text)}</span>"


def st_chip(real, meta, tp=None):
    """Chip de % da meta: ≥100 ok · 90–99 atenção · <90 abaixo."""
    if meta is None or not meta or (isinstance(meta, float) and math.isnan(meta)):
        return chip("neu", "—", False, ["Sem meta", "Canal fora do % do grupo."])
    r = (real or 0) / meta
    tone = "ok" if r >= 1 else "warn" if r >= .9 else "bad"
    return chip(tone, fp(r), False, tp or [fp(r) + " da meta", f0(real) + " de " + f0(meta)], tone)


def d_chip(cur, base, label="", dashed=False, tp_t=None):
    """Chip Δ% contra uma base; None quando não há base informada."""
    if base is None or (isinstance(base, float) and math.isnan(base)):
        return None
    t = tp_t or ("Mesmo trecho" if dashed else "Período anterior inteiro")
    if round(base) == 0:
        if (cur or 0) > 0:
            return chip("neu", "novo" + (" " + label if label else ""), dashed, [t, "Base zero: sem volume no período de comparação"])
        return chip("neu", "—", dashed, [t, "Sem base: nenhum volume nos dois períodos"])
    d = (cur or 0) / base - 1
    return chip("ok" if d >= 0 else "bad", ("+" if d >= 0 else "−") + fp(abs(d)) + (" " + label if label else ""), dashed,
                [t, "Atual " + f0(cur), "Base " + f0(base)])


def d_c(cur, base, label="", dashed=False, tp_t=None):
    return d_chip(cur, base, label, dashed, tp_t) or chip("neu", "—", dashed, [tp_t or "", "Sem base informada"])


# ------------------------------------------------------------------------------------------------ loaders (cache do Streamlit)
@st.cache_data(ttl=7200, show_spinner=False)
def _load_leads_diario(_cquery):
    d = _cquery("SELECT dia, leads_unicos, enviados_engajamento, transb_franquias, atualizado_em FROM alex_leads_diario ORDER BY dia")
    d["dia"] = pd.to_datetime(d["dia"]).dt.date
    return d


@st.cache_data(ttl=7200, show_spinner=False)
def _load_ger(_cquery):
    d = _cquery("SELECT dia, secao, dim, metrica, valor, atualizado_em FROM alex_ger_dash_dia")
    d["dia"] = pd.to_datetime(d["dia"]).dt.date
    return d


def load_fontes(cquery):
    """(leads_diario, ger, erros) — nunca levanta; a aba mostra o erro no lugar do número."""
    erros = {}
    try:
        ld = _load_leads_diario(cquery)
    except Exception as e:  # noqa: BLE001
        ld, erros["alex_leads_diario"] = pd.DataFrame(columns=["dia", "leads_unicos", "enviados_engajamento", "transb_franquias", "atualizado_em"]), f"{type(e).__name__}: {str(e)[:300]}"
    try:
        ger = _load_ger(cquery)
    except Exception as e:  # noqa: BLE001
        ger, erros["alex_ger_dash_dia"] = pd.DataFrame(columns=["dia", "secao", "dim", "metrica", "valor", "atualizado_em"]), f"{type(e).__name__}: {str(e)[:300]}"
    return ld, ger, erros


# ------------------------------------------------------------------------------------------------ motor de dados
class Dados:
    """Séries diárias por métrica para o canal/definições escolhidos. Tudo indexado por data (Timestamp, 00:00)."""

    def __init__(self, df_raw, df_goals, df_fcst, df_cal, ld, ger, reference_date, hoje, channel="cdt",
                 leaddef="abr", dateby="evento", compare="mes"):
        self.D1 = reference_date                       # último dia fechado (Dados até)
        self.hoje = hoje
        self.M0, self.Mend = month_start(reference_date), month_end(reference_date)
        self.N = (self.Mend - self.M0).days + 1
        self.nd = reference_date.day                   # dias fechados no mês
        self.rem = self.N - self.nd
        self.channel, self.leaddef, self.dateby, self.compare = channel, leaddef, dateby, compare
        self.node = NODE[channel]
        self.tipos = tipos_of(channel)
        self.buckets = LEADDEF_BUCKETS[leaddef]
        self.idx = pd.date_range(dt.date(self.M0.year - 1, 1, 1), self.Mend, freq="D")
        self.T1 = pd.Timestamp(reference_date)
        self._cache = {}
        self.df_goals, self.df_fcst = df_goals, df_fcst
        # vendas: data × tipo (minúsculas)
        v = df_raw[["data_venda", "tipo_venda", "Vendas"]].copy() if not df_raw.empty else pd.DataFrame(columns=["data_venda", "tipo_venda", "Vendas"])
        if not v.empty:
            v["tipo"] = v["tipo_venda"].astype(str).str.lower().str.strip()
            v["data_venda"] = pd.to_datetime(v["data_venda"]).dt.normalize()
            self.V = v.pivot_table(index="data_venda", columns="tipo", values="Vendas", aggfunc="sum").reindex(self.idx).fillna(0.0)
        else:
            self.V = pd.DataFrame(index=self.idx)
        # leads diário (Negócio/Contato, régua da meta)
        self.LD = pd.DataFrame(index=self.idx)
        if ld is not None and not ld.empty:
            l2 = ld.copy()
            l2.index = pd.to_datetime(l2["dia"])
            self.LD = l2[["leads_unicos", "enviados_engajamento", "transb_franquias"]].astype(float).reindex(self.idx)
        self.ld_upd = ld["atualizado_em"].max() if ld is not None and not ld.empty else None
        # jornada por dia × bucket (Contato) e vo por bucket|tipo
        self.J, self.VO = {}, {}
        self.ger_upd = ger["atualizado_em"].max() if ger is not None and not ger.empty else None
        self.ger_min = ger["dia"].min() if ger is not None and not ger.empty else None
        if ger is not None and not ger.empty:
            g = ger.copy()
            g["ts"] = pd.to_datetime(g["dia"])
            for met, sub in g[g["secao"] == "jornada"].groupby("metrica"):
                self.J[met] = sub.pivot_table(index="ts", columns="dim", values="valor", aggfunc="sum").reindex(self.idx)
            vo = g[g["secao"] == "vo"].copy()
            if not vo.empty:
                sp = vo["dim"].str.split("|", n=1, expand=True)
                vo["bucket"], vo["tipo"] = sp[0], sp[1].fillna("")
                for met, sub in vo.groupby("metrica"):
                    self.VO[met] = sub
        # calendário (promoções)
        self.cal = pd.DataFrame(index=self.idx)
        if df_cal is not None and not df_cal.empty:
            c = df_cal.copy()
            c.index = pd.to_datetime(c["data_ref"]).dt.normalize()
            c = c[~c.index.duplicated()]
            self.cal = c.reindex(self.idx)
        self.weeks = weeks_of_month(self.M0)
        for w in self.weeks:
            w["per"] = drange(w["a"], w["b"])
            w["acao"] = self.acao(w["a"], w["b"])
            w["dias"] = (w["b"] - w["a"]).days + 1

    # ---------------------------------------------------------------- calendário
    def acao(self, a, b):
        if self.cal.empty or "promo_dupla" not in self.cal:
            return "—"
        sl = self.cal.loc[pd.Timestamp(a):pd.Timestamp(b)]
        du, un = float(sl["promo_dupla"].fillna(0).sum()), float(sl["promo_uno"].fillna(0).sum())
        if du and du >= un:
            return "Dupla Isenção"
        if un or du:
            return "1 Isenção" if not du else "1 Isenção / Dupla"
        return "—"

    def is_we(self, d):
        return d.weekday() >= 5

    # ---------------------------------------------------------------- séries completas
    def _journey(self, met):
        """Soma por dia dos buckets permitidos (Contato). NaN antes da cobertura da tabela."""
        if met not in self.J:
            return pd.Series(np.nan, index=self.idx)
        tb = self.J[met]
        cols = [b for b in self.buckets if b in tb.columns]
        if not cols:
            return pd.Series(np.nan, index=self.idx)
        s = tb[cols].sum(axis=1, min_count=1).fillna(0.0)
        if self.ger_min is not None:
            s[s.index < pd.Timestamp(self.ger_min)] = np.nan
        return s

    def _vo(self):
        met = "vo_foto" if self.dateby == "evento" else "vo_safra"
        if met not in self.VO:
            return pd.Series(np.nan, index=self.idx)
        sub = self.VO[met]
        sub = sub[sub["bucket"].isin(self.buckets)]
        if self.channel != "cdt":
            sub = sub[sub["tipo"].isin(self.tipos)]
        s = sub.groupby("ts")["valor"].sum().reindex(self.idx).fillna(0.0)
        if self.ger_min is not None:
            s[s.index < pd.Timestamp(self.ger_min)] = np.nan
        return s

    def full(self, m):
        """Série diária completa da métrica (NaN = sem dado). Dias depois de D1 ficam NaN."""
        if m in self._cache:
            return self._cache[m]
        if m == "vendas":
            cols = [t for t in self.tipos if t in self.V.columns]
            s = self.V[cols].sum(axis=1) if cols else pd.Series(0.0, index=self.idx)
        elif m in ("web", "apf"):
            t = NODE[m]["tipo"]
            s = self.V[t] if (t in self.V.columns and m in leaves_of(self.channel)) else pd.Series(np.nan, index=self.idx)
        elif m in ("leads", "enc", "tr"):
            oficial = self.leaddef == "abr" and (m == "leads" or self.dateby == "evento")
            if oficial and not self.LD.empty:
                col = {"leads": "leads_unicos", "enc": "enviados_engajamento", "tr": "transb_franquias"}[m]
                s = self.LD[col] if col in self.LD else pd.Series(np.nan, index=self.idx)
            else:
                suf = "_foto" if self.dateby == "evento" else "_safra"
                s = self._journey("leads" if m == "leads" else m + suf)
        elif m == "vo":
            s = self._vo()
        else:
            s = pd.Series(np.nan, index=self.idx)
        s = s.astype(float).copy()
        s[s.index > self.T1] = np.nan
        self._cache[m] = s
        return s

    def s(self, m, a, b):
        """Soma de a..b (datas), limitada a D1. None quando não há dado algum no intervalo."""
        if a is None or b is None:
            return None
        b = min(b, self.D1)
        if a > b:
            return None
        sl = self.full(m).loc[pd.Timestamp(a):pd.Timestamp(b)]
        if sl.notna().sum() == 0:
            return None
        return float(sl.sum(skipna=True))

    def s_hist(self, m, a, b):
        """Como s(), mas para leads/enc/tr cai na jornada (Contato, foto) quando a alex_leads_diario não cobre o período
        (ela começa em 16/07/2026). Devolve (valor, origem) — origem 'oficial' | 'jornada' | None."""
        v = self.s(m, a, b)
        if v is not None or m not in ("leads", "enc", "tr"):
            return v, ("oficial" if v is not None else None)
        key = "leads" if m == "leads" else m + ("_foto" if self.dateby == "evento" else "_safra")
        j = self._journey(key)
        b = min(b, self.D1)
        if a > b:
            return None, None
        sl = j.loc[pd.Timestamp(a):pd.Timestamp(b)]
        if sl.notna().sum() == 0:
            return None, None
        return float(sl.sum(skipna=True)), "jornada"

    def at(self, m, d):
        if d is None or d > self.D1:
            return None
        v = self.full(m).get(pd.Timestamp(d), np.nan)
        return None if pd.isna(v) else float(v)

    def arr_month(self, m, m0):
        """Array com 1 valor por dia do mês m0 (NaN onde não há dado / futuro)."""
        me = month_end(m0)
        return self.full(m).loc[pd.Timestamp(m0):pd.Timestamp(me)].to_numpy(dtype=float)

    # ---------------------------------------------------------------- metas
    def goals_row(self, m0):
        if self.df_goals is None or self.df_goals.empty or "mes_ano" not in self.df_goals:
            return None
        r = self.df_goals[self.df_goals["mes_ano"] == pd.Timestamp(m0)]
        return None if r.empty else r.iloc[0]

    def node_meta(self, cid, m0=None):
        """Meta mensal de vendas do nó: coluna própria da alex_metas ou soma dos filhos com meta (None se nenhum)."""
        row = self.goals_row(m0 or self.M0)
        n = NODE[cid]
        if row is not None and n["metacol"] and n["metacol"] in row.index:
            v = row[n["metacol"]]
            if v is not None and not pd.isna(v) and float(v) > 0:
                return float(v)
            if n["leaf"]:
                return None
        if n["leaf"]:
            return None
        ks = [self.node_meta(k, m0) for k in n["kids"]]
        ks = [k for k in ks if k]
        return sum(ks) if ks else None

    def node_has_own_meta(self, cid, m0=None):
        row = self.goals_row(m0 or self.M0)
        n = NODE[cid]
        return bool(row is not None and n["metacol"] and n["metacol"] in row.index and not pd.isna(row[n["metacol"]]) and float(row[n["metacol"]]) > 0)

    def lead_meta(self, m, m0=None):
        """Meta mensal de leads/transbordados (só CDT, definição Abrangente). (valor, origem) ou (None, motivo)."""
        m0 = m0 or self.M0
        if self.channel != "cdt":
            return None, "Leads não se abrem por canal de venda"
        if self.leaddef != "abr":
            return None, "Meta só na definição Abrangente"
        key = f"{m0.year}-{m0.month:02d}"
        if key in METAS_LEADS and m in METAS_LEADS[key]:
            return float(METAS_LEADS[key][m]), "meta de " + MES_PT[m0.month - 1] + "/" + str(m0.year)[2:]
        row = self.goals_row(m0)
        col = {"leads": "Leads unicos Total", "tr": "Leads transbordado"}.get(m)
        if row is not None and col and col in row.index and not pd.isna(row[col]) and float(row[col]) > 0:
            return float(row[col]), "régua alex_metas"
        return None, "Sem meta carregada"

    def meta_total(self, m, m0=None):
        """Meta do mês da métrica m (vendas por canal; web/apf; leads/tr). None = sem meta."""
        m0 = m0 or self.M0
        if m == "vendas":
            return self.node_meta(self.channel, m0)
        if m in ("web", "apf"):
            return self.node_meta(m, m0) if m in leaves_of(self.channel) else None
        if m in ("leads", "tr"):
            return self.lead_meta(m, m0)[0]
        return None

    def meta_daily(self, m, m0=None):
        m0 = m0 or self.M0
        mt = self.meta_total(m, m0)
        if mt is None:
            return None
        n = calendar.monthrange(m0.year, m0.month)[1]
        return np.full(n, mt / n)

    def meta_sum(self, m, a, b):
        """Meta linear acumulada entre a e b (datas dentro do mês corrente ou de outro mês com meta)."""
        if a is None or b is None or a > b:
            return None
        tot, any_ = 0.0, False
        cur = month_start(a)
        while cur <= b:
            md = self.meta_daily(m, cur)
            if md is not None:
                lo, hi = max(a, cur), min(b, month_end(cur))
                tot += md[0] * ((hi - lo).days + 1)
                any_ = True
            cur = add_months(cur, 1)
        return tot if any_ else None

    # ---------------------------------------------------------------- projeção
    def _share90(self, leaf):
        """Fatia do canal-folha dentro do seu grupo do Prophet nos últimos 90 dias fechados."""
        grp = NODE[leaf]["fc"]
        peers = [l for l in LEAVES if NODE[l]["fc"] == grp]
        if len(peers) == 1:
            return 1.0
        a = pd.Timestamp(self.D1 - dt.timedelta(days=89))
        tot = {p: float(self.V[NODE[p]["tipo"]].loc[a:self.T1].sum()) if NODE[p]["tipo"] in self.V.columns else 0.0 for p in peers}
        s = sum(tot.values())
        return tot[leaf] / s if s else 1.0 / len(peers)

    def forecast_daily(self, cid):
        """Previsão Prophet (balanced) por dia > D1 para o nó, ou None se não há snapshot."""
        if self.df_fcst is None or self.df_fcst.empty:
            return None
        f = self.df_fcst[self.df_fcst["scenario"] == "balanced"]
        if f.empty:
            return None
        f = f.copy()
        f["grp"] = f["channel_group"].astype(str).str.lower().str.strip()
        by = f.groupby(["ds", "grp"])["yhat"].sum().unstack(fill_value=0.0)
        out = pd.Series(0.0, index=by.index)
        for leaf in leaves_of(cid):
            grp = NODE[leaf]["fc"]
            if grp in by.columns:
                out = out + by[grp] * self._share90(leaf)
        out = out[out.index > self.T1]
        return out if not out.empty else None

    def ritmo(self, m):
        """Ritmo por dia da semana: mediana dos últimos 28 dias fechados (regra do e-mail de metas). dict weekday → valor."""
        s = self.full(m).loc[pd.Timestamp(self.D1 - dt.timedelta(days=27)):self.T1].dropna()
        if s.empty:
            return None
        return {wd: float(np.median(s[s.index.weekday == wd])) if (s.index.weekday == wd).any() else float(s.median()) for wd in range(7)}

    def projecao(self, m):
        """Acumulado do mês: realizado até D1 + projeção. Devolve dict(cum, meta_cum, fonte, real_mtd, proj_total, sem_dado_dias)."""
        cur = self.arr_month(m, self.M0)
        real = np.nan_to_num(cur[: self.nd], nan=0.0)
        has_data = np.isfinite(cur[: self.nd]).any()
        cum = np.zeros(self.N)
        cum[: self.nd] = np.cumsum(real)
        fonte, faltam = None, 0
        fc = self.forecast_daily(self.channel) if m == "vendas" else None
        rt = None if fc is not None else self.ritmo(m)
        acc = cum[self.nd - 1] if self.nd else 0.0
        for i in range(self.nd, self.N):
            d = self.M0 + dt.timedelta(days=i)
            v = None
            if fc is not None:
                v = fc.get(pd.Timestamp(d))
                if v is None or pd.isna(v):
                    v = None
            if v is None and rt is None and fc is not None:
                rt = self.ritmo(m)
            if v is None and rt is not None:
                v = rt[d.weekday()]
                faltam += 1
            acc += (v or 0.0)
            cum[i] = acc
        if m == "vendas" and fc is not None:
            fonte = "Prophet, cenário balanced" + (f" · {faltam} dia(s) sem previsão → ritmo" if faltam else "")
        else:
            fonte = "ritmo por dia da semana (mediana 28 d)"
        md = self.meta_daily(m)
        meta_cum = np.cumsum(md) if md is not None else None
        return dict(cum=cum, meta_cum=meta_cum, fonte=fonte, real_mtd=float(cum[self.nd - 1]) if self.nd else 0.0,
                    proj_total=float(cum[-1]), has_data=has_data, has_fc=fc is not None)

    # ---------------------------------------------------------------- períodos
    def period(self, p, custom=None):
        """(a, b, rótulo curto, rótulo longo) do período escolhido."""
        D1, hoje, M0 = self.D1, self.hoje, self.M0
        mon = hoje - dt.timedelta(days=hoje.weekday())
        if p == "hoje":
            return hoje, hoje, f"Hoje · {dfmt(hoje)} ({DOW[hoje.weekday()]}) · dia em andamento", dfmt(hoje)
        if p == "ontem":
            return D1, D1, f"Último dia fechado · {dfmt(D1)} ({DOW[D1.weekday()]})", dfmt(D1)
        if p == "semana":
            return mon, mon + dt.timedelta(days=6), f"Esta semana · {drange(mon, mon + dt.timedelta(days=6))}", drange(mon, mon + dt.timedelta(days=6))
        if p == "semana_ant":
            a, b = mon - dt.timedelta(days=7), mon - dt.timedelta(days=1)
            return a, b, f"Semana passada · {drange(a, b)}", drange(a, b)
        if p == "mes":
            return M0, self.Mend, f"{MES_PT_LONGO[M0.month - 1]}/{M0.year} · dados até {dfmt(D1)}", drange(M0, self.Mend)
        if p == "mes_ant":
            a = add_months(M0, -1)
            return a, month_end(a), f"{MES_PT_LONGO[a.month - 1]}/{a.year} · mês fechado", drange(a, month_end(a))
        if p == "d30":
            a = D1 - dt.timedelta(days=29)
            return a, D1, f"Últimos 30 dias · {drange(a, D1)}", drange(a, D1)
        if p == "d90":
            a = D1 - dt.timedelta(days=89)
            return a, D1, f"Últimos 90 dias · {drange(a, D1)}", drange(a, D1)
        a, b = custom if custom else (M0, D1)
        if a > b:
            a, b = b, a
        b = min(b, D1)
        return a, b, f"Personalizado · {drange(a, b)} · {(b - a).days + 1} dias", drange(a, b)

    def week_of(self, d):
        for w in self.weeks:
            if w["a"] <= d <= w["b"]:
                return w
        return None

    # ---------------------------------------------------------------- KPI (espelha kpi() do blueprint)
    def kpi(self, m, p, custom=None):
        a, b, _, _ = self.period(p, custom)
        D1, M0 = self.D1, self.M0
        ano = self.compare == "ano"
        real, meta, solid, dashed, m_lbl, wk = None, None, None, None, "", None
        no_meta, empty = "Sem meta para este canal", False
        if m in ("leads", "enc", "tr") and self.channel != "cdt":
            no_meta = "Leads não se abrem por canal de venda · visão CDT"
        if m == "enc":
            no_meta = "Meta em revisão"
        if m in ("leads", "tr") and self.channel == "cdt" and self.leaddef == "abr":
            # metas de leads só existem no mês (e, proporcionalmente, na semana); não há meta diária nem de janela livre
            if p in ("hoje", "ontem"):
                no_meta = "Sem meta diária · meta do mês " + f0(self.meta_total(m))
            elif p in ("d30", "d90", "custom"):
                no_meta = "Sem meta para este período · meta do mês " + f0(self.meta_total(m))
        _lead_daily_block = m in ("leads", "tr") and p in ("hoje", "ontem", "d30", "d90", "custom")
        if p == "mes":
            real = self.s(m, M0, D1)
            meta = self.meta_sum(m, M0, D1)
            m_lbl = "Meta parcial"
            pm0, ya = add_months(M0, -1), add_months(M0, -12)
            if ano:
                solid = (self.s(m, ya, month_end(ya)), f"vs {MES_PT[ya.month - 1]}/{str(ya.year)[2:]}", f"{MES_PT_LONGO[ya.month - 1]}/{str(ya.year)[2:]} inteiro")
                dashed = (self.s(m, ya, min(ya + dt.timedelta(days=self.nd - 1), month_end(ya))), f"vs {drange(ya, ya + dt.timedelta(days=self.nd - 1))}/{str(ya.year)[2:]}", "Mesmo trecho do ano anterior")
            else:
                solid = (self.s(m, pm0, month_end(pm0)), f"vs {MES_PT[pm0.month - 1]}", f"{MES_PT_LONGO[pm0.month - 1]} inteiro")
                pb = min(pm0 + dt.timedelta(days=self.nd - 1), month_end(pm0))
                dashed = (self.s(m, pm0, pb), f"vs {drange(pm0, pb)}", f"Mesmo trecho de {MES_PT[pm0.month - 1]} ({drange(pm0, pb)})")
        elif p == "ontem":
            real = self.at(m, D1)
            meta = self.meta_sum(m, D1, D1)
            m_lbl = "Meta do dia"
            d7 = D1 - dt.timedelta(days=7)
            solid = (self.at(m, d7), "vs D-7", f"D-7 · {dfmt(d7)} ({DOW[d7.weekday()]})")
            a7 = self.s(m, D1 - dt.timedelta(days=7), D1 - dt.timedelta(days=1))
            dashed = (None if a7 is None else a7 / 7, "vs média 7d", f"Média {drange(D1 - dt.timedelta(days=7), D1 - dt.timedelta(days=1))}")
        elif p == "hoje":
            empty = True
            meta = self.meta_sum(m, self.hoje, self.hoje)
            m_lbl = "Meta do dia"
        elif p == "semana":
            w = self.week_of(a) if a >= M0 else None
            if b > D1 and a > D1:
                empty = True
            else:
                real = self.s(m, max(a, M0), b)
            meta = self.meta_sum(m, a, b)
            m_lbl = f"Meta {w['id']}" if w else "Meta da semana"
            wk = w
        elif p == "semana_ant":
            real = self.s(m, a, b)
            meta = self.meta_sum(m, a, b)
            w = self.week_of(a)
            m_lbl = f"Meta {w['id']}" if w else "Meta da semana"
            wk = w
            pa, pb = a - dt.timedelta(days=7), b - dt.timedelta(days=7)
            pw = self.week_of(pa)
            solid = (self.s(m, pa, pb), f"vs {pw['id'] if pw else 'sem. ant.'}", drange(pa, pb))
        elif p == "mes_ant":
            real = self.s(m, a, b)
            meta = self.meta_sum(m, a, b)
            m_lbl = "Meta do mês"
            if meta is None:
                no_meta = f"Sem meta carregada para {MES_PT[a.month - 1]}/{str(a.year)[2:]}"
            pa = add_months(a, -1)
            solid = (self.s(m, pa, month_end(pa)), f"vs {MES_PT[pa.month - 1]}", f"{MES_PT_LONGO[pa.month - 1]} inteiro")
        else:
            ln = (b - a).days + 1
            real = self.s(m, a, b)
            meta = self.meta_sum(m, a, b)
            m_lbl = "Meta do período"
            if meta is None:
                no_meta = "Sem meta para este período"
            pa, pb = a - dt.timedelta(days=ln), a - dt.timedelta(days=1)
            solid = (self.s(m, pa, pb), f"vs {ln} dias ant.", drange(pa, pb))
            if ano:
                ya, yb = add_months(a, -12), add_months(b, -12)
                dashed = (self.s(m, ya, yb), f"vs {drange(ya, yb)}/{str(ya.year)[2:]}", "Mesmo trecho do ano anterior")
        if _lead_daily_block:
            meta = None
        chips = []
        if not empty and real is not None:
            if solid:
                c = d_chip(real, solid[0], solid[1], False, solid[2])
                if c:
                    chips.append(c)
            if dashed:
                c = d_chip(real, dashed[0], dashed[1], True, dashed[2])
                if c:
                    chips.append(c)
        if empty:
            stc = chip("neu", "sem dados", False, ["Dia em andamento" if p == "hoje" else "Nenhum dia fechado nesta semana", f"Dados disponíveis até {dfmt(D1)}"])
        elif real is None:
            stc = chip("neu", "—", False, ["Sem dado para a métrica neste período"])
        elif meta is not None:
            stc = st_chip(real, meta)
        else:
            stc = chip("neu", "—", False, [no_meta])
        if meta is not None:
            meta_txt = f"{m_lbl} {f0(meta)}"
        else:
            meta_txt = no_meta
        return dict(value="—" if (empty or real is None) else f0(real), real=real, meta=meta, empty=empty,
                    empty_title="Dia em andamento" if p == "hoje" else "Nenhum dia fechado na semana",
                    empty_sub=f"Dados disponíveis até {dfmt(D1)}", meta_txt=meta_txt, st=stc, chips=chips, wk=self.week_bars(m))

    def week_bars(self, m):
        """Mini-barras S1..Sn do mês corrente (valor da semana até D1); semanas futuras tracejadas."""
        vals = [self.s(m, w["a"], w["b"]) if w["a"] <= self.D1 else None for w in self.weeks]
        mx = max([v for v in vals if v] + [1.0])
        last = max([i for i, v in enumerate(vals) if v is not None], default=-1)
        out = []
        for i, w in enumerate(self.weeks):
            v = vals[i]
            fut = v is None
            hi = i == last
            mt = self.meta_sum(m, w["a"], w["b"])
            if fut:
                tp = [f"{w['id']} · {w['per']}", f"Meta {f0(mt) if mt else '—'}", "Semana atual · sem dias fechados" if w["a"] <= self.hoje <= w["b"] or w["a"] <= self.D1 + dt.timedelta(days=1) <= w["b"] else "Semana futura · sem dados"]
            else:
                r = (v / mt - 1) if mt else None
                pv = vals[i - 1] if i > 0 else None
                wo = (v / pv - 1) if pv else None
                parcial = w["b"] > self.D1
                tp = [f"{w['id']} · {w['per']}", f"{MSHORT[m]} {f0(v)}", f"Meta {f0(mt) if mt else '—'}",
                      f"vs meta {sg(r) if mt else '—'}", f"WoW {sg(wo) if pv else '—'}", "Semana em andamento (até " + dfmt(self.D1) + ")" if parcial else "Semana fechada"]
            out.append(dict(t=w["id"], h=100 if fut else max(6.0, v / mx * 100), fut=fut, hi=hi, tp=tp))
        return out


# ------------------------------------------------------------------------------------------------ CSS
def _css(perfil):
    base = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    .g-wrap, .g-wrap * {{ box-sizing:border-box; }}
    .g-wrap p {{ margin:0; }}
    .g-wrap {{ font-family:Inter,system-ui,sans-serif; color:{INK}; font-variant-numeric:tabular-nums; }}
    .g-h1 {{ margin:0; font:500 40px/44px Inter,system-ui,sans-serif; letter-spacing:-.045em; display:flex; align-items:baseline; gap:14px; }}
    .g-h1 .n {{ color:{SAND}; }}
    .g-h2 {{ margin:4px 0 0; font:500 20px/26px Inter,system-ui,sans-serif; letter-spacing:-.03em; }}
    .g-p {{ margin:0; font:400 16px/24px Inter,system-ui,sans-serif; color:#46453D; max-width:980px; }}
    .g-p b {{ font-weight:500; color:{INK}; }}
    .g-card {{ background:{CARD}; border-radius:24px; padding:24px; }}
    .g-card h3, .g-h3 {{ margin:0; font:500 18px/24px Inter,system-ui,sans-serif; letter-spacing:-.025em; }}
    .g-sub {{ font:400 13px/18px Inter,system-ui,sans-serif; color:{MUTED2}; }}
    .g-cap {{ font:400 12px/16px Inter,system-ui,sans-serif; color:{MUTED2}; }}
    .g-grid3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; }}
    @media (max-width:1100px) {{ .g-grid3 {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    .g-kpi {{ background:{CARD}; border-radius:24px; padding:24px; display:flex; flex-direction:column; gap:8px; min-height:280px; transition:transform .2s ease, box-shadow .2s ease; }}
    .g-kpi:hover {{ transform:translateY(-2px); box-shadow:0 12px 28px rgba(30,32,22,.08); }}
    .g-kpi .lbl {{ font:500 13px/18px Inter,system-ui,sans-serif; display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
    .g-kpi .lbl a {{ width:36px; height:36px; border-radius:50%; background:{SOFT}; color:{INK}; display:flex; align-items:center; justify-content:center; text-decoration:none; margin:-6px -6px 0 0; font-size:16px; }}
    .g-kpi .lbl a:hover {{ background:{BAR}; }}
    .g-kpi .val {{ font:400 44px/48px Inter,system-ui,sans-serif; letter-spacing:-.05em; white-space:nowrap; }}
    .g-kpi .meta {{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; font:400 13px/18px Inter,system-ui,sans-serif; color:{MUTED}; }}
    .g-kpi .chips {{ display:flex; flex-wrap:wrap; gap:6px; min-height:24px; }}
    .g-kpi .wk {{ margin-top:auto; padding-top:16px; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; align-items:end; height:88px; }}
    .g-kpi .wk > div {{ display:flex; flex-direction:column; justify-content:flex-end; gap:6px; height:100%; }}
    .g-kpi .wk span.b {{ display:block; border-radius:6px; min-height:4px; }}
    .g-kpi .wk span.t {{ font:500 11px/14px Inter,system-ui,sans-serif; text-align:center; }}
    .g-empty {{ display:flex; align-items:center; gap:12px; min-height:48px; }}
    .g-empty .ic {{ width:40px; height:40px; border-radius:50%; background:{SOFT}; display:flex; align-items:center; justify-content:center; color:{MUTED}; font-size:18px; }}
    .g-table {{ width:100%; border-collapse:separate; border-spacing:0; font:400 13px/18px Inter,system-ui,sans-serif; }}
    .g-table th {{ text-align:right; font:500 12px/16px Inter,system-ui,sans-serif; color:{MUTED2}; padding:8px 10px; border-bottom:1px solid {LINE}; white-space:nowrap; }}
    .g-table th:first-child, .g-table td:first-child {{ text-align:left; }}
    .g-table td {{ text-align:right; padding:9px 10px; border-bottom:1px solid #F1F0EA; white-space:nowrap; vertical-align:middle; }}
    .g-table tr:last-child td {{ border-bottom:0; }}
    .g-table tr:hover td {{ background:#FAFAF7; }}
    .g-scroll {{ overflow-x:auto; }}
    .g-legend {{ display:flex; flex-wrap:wrap; gap:16px; font:400 13px/18px Inter,system-ui,sans-serif; color:{MUTED}; align-items:center; }}
    .g-legend span {{ display:inline-flex; align-items:center; gap:8px; }}
    .g-sw {{ display:inline-block; width:20px; height:3px; border-radius:9999px; }}
    .g-dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; }}
    .g-nav {{ display:flex; flex-wrap:wrap; gap:4px; }}
    .g-nav a {{ height:36px; padding:0 14px; border-radius:9999px; display:inline-flex; align-items:center; gap:10px; font:500 13px Inter,system-ui,sans-serif; color:{INK}; text-decoration:none; background:rgba(255,255,255,.55); }}
    .g-nav a:hover {{ background:#FFFFFF; box-shadow:0 1px 3px rgba(58,54,38,.12); }}
    .g-nav a b {{ font-weight:600; color:{SAND}; }}
    .g-hl {{ background:{CARD}; border-radius:24px; padding:20px 24px; display:flex; flex-direction:column; gap:12px; }}
    .g-hl .it {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:8px 0; border-top:1px solid #F1F0EA; }}
    .g-hl .it:first-of-type {{ border-top:0; }}
    .g-hl .it .nm {{ font:500 13px/18px Inter,system-ui,sans-serif; }}
    .g-hl .it .sb {{ font:400 12px/16px Inter,system-ui,sans-serif; color:{MUTED2}; }}
    .g-mix {{ display:grid; grid-template-columns:200px 1fr 64px 90px; gap:8px 14px; align-items:center; font:400 13px/18px Inter,system-ui,sans-serif; }}
    .g-fun {{ display:flex; flex-direction:column; gap:6px; }}
    .g-fun .st {{ display:grid; grid-template-columns:260px 1fr; gap:16px; align-items:center; padding:10px 0; }}
    .g-fun .rate {{ font:500 12px/16px Inter,system-ui,sans-serif; color:{MUTED}; padding-left:276px; }}
    .g-heat {{ display:grid; gap:3px; font:400 12px/16px Inter,system-ui,sans-serif; }}
    .g-heat .c {{ height:22px; border-radius:5px; }}
    .g-heat .r {{ display:flex; align-items:center; gap:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .g-wk {{ display:grid; gap:0; font:400 12px/16px Inter,system-ui,sans-serif; }}
    .g-wk .hd {{ color:{MUTED2}; font-weight:500; padding:6px 8px; border-bottom:1px solid {LINE}; white-space:nowrap; }}
    .g-wk .cl {{ padding:8px 8px; border-bottom:1px solid #F1F0EA; white-space:nowrap; display:flex; align-items:center; gap:6px; }}
    .g-pill {{ display:inline-flex; align-items:center; height:28px; padding:0 12px; border-radius:9999px; background:{SOFT}; font:500 12px Inter,system-ui,sans-serif; color:{MUTED}; }}
    .g-dark {{ background:#161615; color:#FFFFFF; border-radius:24px; padding:24px; display:flex; flex-direction:column; gap:24px; }}
    .g-dark .lb {{ font:400 12px/16px Inter,system-ui,sans-serif; color:#B9B6A9; }}
    .g-dark .big {{ font:400 52px/56px Inter,system-ui,sans-serif; letter-spacing:-.05em; white-space:nowrap; margin-top:12px; }}
    .g-dark .bar {{ flex:1; height:10px; border-radius:9999px; background:#2E2D28; overflow:hidden; }}
    .g-dark .bar span {{ display:block; height:100%; border-radius:9999px; }}
    .g-note {{ font:400 12px/16px Inter,system-ui,sans-serif; color:{MUTED2}; }}
    button[data-variant="pills"], button[kind^="pills"], button[kind^="segmented_control"] {{ border-radius:9999px !important; }}
    button[kind="pillsActive"], button[kind="segmented_controlActive"], button[data-variant="pills"][aria-checked="true"], button[data-variant="segmented_control"][aria-checked="true"], button[role="radio"][data-selected="true"] {{ background:{INK} !important; color:#FFFFFF !important; border-color:{INK} !important; }}
    button[kind="pillsActive"] *, button[kind="segmented_controlActive"] *, button[role="radio"][data-selected="true"] *, button[data-variant="pills"][aria-checked="true"] * {{ color:#FFFFFF !important; }}
    </style>"""
    if perfil == "gerencial":
        base += f"""
        <style>
        .stApp {{ background:{BG}; }}
        header[data-testid="stHeader"] {{ background:transparent; }}
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {{ display:none; }}
        .block-container {{ max-width:1400px; padding-top:1.2rem; }}
        h1, h2, h3, p, label, .stMarkdown {{ font-family:Inter,system-ui,sans-serif; }}
        </style>"""
    import textwrap
    css = "\n".join(ln.strip() for ln in textwrap.dedent(base).splitlines())
    st.markdown(css, unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------ pedaços de HTML
def _header(num, titulo, pergunta, lead, texto, anchor):
    return (f"<div class='g-wrap' id='{anchor}' style='padding-top:28px;display:flex;flex-direction:column;gap:12px'>"
            f"<div class='g-h1'><span class='n'>{num}</span><span>{esc(titulo)}</span></div>"
            f"<div class='g-h2'>{esc(pergunta)}</div><p class='g-p'><b>{esc(lead)}</b> {esc(texto)}</p></div>")


def _kpi_card(label, k, anchor, go_label):
    wk = "".join(
        f"<div title=\"{tip(w['tp'])}\"><span class='b' style='height:{w['h']:.1f}%;background:{'transparent' if w['fut'] else (DARK if w['hi'] else BAR)};"
        f"border:{'1.5px dashed ' + BAR if w['fut'] else '0'}'></span><span class='t' style='color:{INK if w['hi'] else MUTED2}'>{esc(w['t'])}</span></div>"
        for w in k["wk"])
    if k["empty"]:
        val = (f"<div class='g-empty'><span class='ic'>⧗</span><span style='display:flex;flex-direction:column;gap:2px'>"
               f"<span style='font:500 14px/20px Inter'>{esc(k['empty_title'])}</span><span class='g-cap'>{esc(k['empty_sub'])}</span></span></div>")
    else:
        val = f"<div class='val'>{esc(k['value'])}</div>"
    return (f"<div class='g-kpi'><div class='lbl'><span>{esc(label)}</span><a href='#{anchor}' title='{esc(go_label)}'>↘</a></div>{val}"
            f"<div class='meta'><span>{esc(k['meta_txt'])}</span>{k['st']}</div><div class='chips'>{''.join(k['chips'])}</div>"
            f"<div class='wk'>{wk}</div></div>")


def _svg_grid(ys, ytop, step, x1, x2, tx, fa_fn=fa):
    g, v = [], 0.0
    while v <= ytop + 1e-9:
        y = ys(v)
        g.append(f"<line x1='{x1}' x2='{x2}' y1='{y:.1f}' y2='{y:.1f}' stroke='#EDECE6' stroke-width='1'/>"
                 f"<text x='{tx}' y='{y + 5:.1f}' text-anchor='end' font-size='11' fill='{MUTED2}' font-family='Inter,system-ui,sans-serif'>{esc(fa_fn(v))}</text>")
        v += step
    return "".join(g)


# ------------------------------------------------------------------------------------------------ BLOCO 01 — Meta do mês
def _bloco1(D: Dados, p, custom):
    M0, D1, N, nd, rem = D.M0, D.D1, D.N, D.nd, D.rem
    mes = MES_PT_LONGO[M0.month - 1]
    pj = D.projecao("vendas")
    metaT = D.meta_total("vendas")
    # ---- texto do cabeçalho
    if metaT and pj["has_data"]:
        proj, real = pj["proj_total"], pj["real_mtd"]
        need = (metaT - real) / rem if rem else None
        avg = real / nd if nd else 0
        bate = proj >= metaT
        lead = f"No ritmo atual, {mes.lower()} {'bate' if bate else 'não bate'} a meta."
        prox_dupla = (next((w for w in D.weeks if w["b"] > D1 and w["acao"] == "Dupla Isenção"), None)
                      or next((w for w in D.weeks if w["b"] > D1 and "Dupla" in w["acao"]), None))
        txt = f"A projeção ({pj['fonte']}) fecha em {fp(proj / metaT)} dos {fk(metaT)}."
        if rem and need is not None:
            if need > avg and avg > 0:
                txt += (f" Para chegar lá, os {rem} dias que faltam precisariam render {fk(need)} vendas por dia, "
                        f"{('o dobro' if need / avg >= 1.9 and need / avg <= 2.1 else fp(need / avg - 1, 0) + ' acima')} da média de {fk(avg)}")
                txt += (f", e a {prox_dupla['id']} ({prox_dupla['acao']}) ainda está por vir." if prox_dupla else ".")
            elif need is not None and need <= avg:
                txt += f" A média atual de {fk(avg)} vendas por dia já cobre o necessário de {fk(need)} por dia nos {rem} dias restantes."
        else:
            txt += " Mês encerrado."
    elif not metaT:
        lead = f"{D.node['name']} não tem meta de vendas cadastrada para {mes.lower()}."
        txt = "A projeção aparece sem o farol de meta; os canais com meta estão no bloco 03."
    else:
        lead = "Sem vendas carregadas para o mês."
        txt = "Confira a RESUMO_VENDAS_DIARIAS."
    st.markdown(_header("01", "Meta do mês", "Vamos bater a meta?", lead, txt, "b1"), unsafe_allow_html=True)

    # ---- KPIs
    a, b, pl, _ = D.period(p, custom)
    title = pl + ("" if D.channel == "cdt" else " · " + D.node["name"])
    cards = [("Leads Únicos · Contato", "leads", "b4", "Ver funil"), ("Pipe Televendas · Negócio", "enc", "b4", "Ver funil"),
             ("Transbordados Franquia · Negócio", "tr", "b4", "Ver funil"), ("Vendas Site", "web", "b3", "Ver canais"),
             ("Vendas App", "apf", "b3", "Ver canais"), ("Vendas CDT" if D.channel == "cdt" else "Vendas · " + D.node["name"], "vendas", "b3", "Ver canais")]
    if D.leaddef != "abr" or D.dateby != "evento":
        cards[1] = ("Pipe Televendas · Contato", "enc", "b4", "Ver funil")
        cards[2] = ("Transbordados Franquia · Contato", "tr", "b4", "Ver funil")
    html = [f"<div class='g-wrap' style='display:flex;flex-direction:column;gap:16px;margin-top:28px'>",
            f"<div style='display:flex;justify-content:flex-end'><span class='g-sub'>{esc(title)}</span></div><div class='g-grid3'>"]
    for label, m, anchor, go in cards:
        html.append(_kpi_card(label, D.kpi(m, p, custom), anchor, go))
    html.append("</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _bloco1_proj(D: Dados, pm):
    M0, D1, N, nd, rem = D.M0, D.D1, D.N, D.nd, D.rem
    PS = D.projecao(pm)
    cum, mc = PS["cum"], PS["meta_cum"]
    has_m = mc is not None
    PL, PR, PT, PB = 72, 880, 24, 318
    pmax = max((mc[-1] if has_m else 0), cum[-1], 1) * 1.08
    pstep = nice(pmax)
    ptop = math.ceil(pmax / pstep) * pstep
    xs = lambda i: PL + (i + 1) * (PR - PL) / N          # noqa: E731
    py = lambda v: PB - (v / ptop) * (PB - PT)            # noqa: E731
    meta_pts = [(PL, PB)]
    if has_m:
        for i in range(N):
            meta_pts.append((meta_pts[-1][0], py(mc[i])))
            meta_pts.append((xs(i), py(mc[i])))
    real_pts = [(PL, PB)] + [(xs(i), py(cum[i])) for i in range(nd)]
    proj_pts = [(xs(i), py(cum[i])) for i in range(max(nd - 1, 0), N)]
    series_pts = real_pts + proj_pts[1:]
    gap = ""
    if has_m:
        gap = ("<path d='M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in meta_pts) + " L" +
               " L".join(f"{x:.1f} {y:.1f}" for x, y in reversed(series_pts)) + " Z' fill='url(#g-ph)' stroke='none'/>")
    meta_path = ("<path d='M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in meta_pts) + f"' fill='none' stroke='{GREY}' stroke-width='2'/>") if has_m else ""
    metaT_m, projT = (mc[-1] if has_m else None), cum[-1]
    real_mtd = cum[nd - 1] if nd else 0.0
    hov = []
    for i in range(N):
        d = M0 + dt.timedelta(days=i)
        lines = [f"{dfmt(d)} ({DOW[d.weekday()]})", (f"Realizado acum. {f0(cum[i])}" if i < nd else f"Projeção acum. {f0(cum[i])}"),
                 (f"Meta acum. {f0(mc[i])}" if has_m else "Sem meta"),
                 (("Distância " if i < nd else "Distância projetada ") + f0(cum[i] - mc[i])) if has_m else ""]
        hov.append(f"<rect x='{xs(i) - (PR - PL) / N:.1f}' y='24' width='{(PR - PL) / N:.1f}' height='294' fill='transparent'><title>{tip(lines)}</title></rect>")
    xl = "".join(f"<text x='{xs(i) - (PR - PL) / N / 2:.1f}' y='344' text-anchor='middle' font-size='11' fill='{MUTED2}' font-family='Inter,system-ui,sans-serif'>{dfmt(M0 + dt.timedelta(days=i))}</text>"
                 for i in sorted({0, 4, 11, 18, 25, N - 1}) if i < N)
    end_lbl = f"<text x='{xs(N - 1) - 12:.1f}' y='{py(projT) + (24 if (has_m and projT < metaT_m) else -14):.1f}' text-anchor='end' font-size='12' font-weight='600' fill='{INK}' font-family='Inter,system-ui,sans-serif'>Projeção {esc(f0(projT))}</text>"
    meta_lbl = (f"<text x='{xs(N - 1) - 12:.1f}' y='{py(metaT_m) + (-12 if projT < metaT_m else 24):.1f}' text-anchor='end' font-size='12' fill='{GREY}' font-family='Inter,system-ui,sans-serif'>Meta {esc(f0(metaT_m))}</text>") if has_m else ""
    d1_lbl = (f"<circle cx='{xs(nd - 1):.1f}' cy='{py(real_mtd):.1f}' r='5' fill='{INK}'/><text x='{xs(nd - 1) - 12:.1f}' y='{py(real_mtd) - 14:.1f}' text-anchor='end' font-size='12' fill='{INK}' font-family='Inter,system-ui,sans-serif'>{esc(f0(real_mtd))} · {dfmt(D1)}</text>") if nd else ""
    svg = (f"<svg viewBox='0 0 900 360' width='100%' style='display:block;overflow:visible'>"
           f"<defs><pattern id='g-ph' width='6' height='6' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><rect width='6' height='6' fill='#FFFFFF'/><rect width='1.5' height='6' fill='{SAND}'/></pattern></defs>"
           + _svg_grid(py, ptop, pstep, PL, PR, 62) + gap + meta_path
           + f"<path d='{smooth(real_pts)}' fill='none' stroke='{INK}' stroke-width='3' stroke-linecap='round'/>"
           + f"<path d='{smooth(proj_pts)}' fill='none' stroke='{INK}' stroke-width='2.5' stroke-dasharray='6 6' stroke-linecap='round'/>"
           + f"<circle cx='{xs(N - 1):.1f}' cy='{py(projT):.1f}' r='5' fill='#FFFFFF' stroke='{INK}' stroke-width='2.5'/>" + end_lbl + meta_lbl + d1_lbl + xl + "".join(hov) + "</svg>")
    # painel escuro
    need = ((metaT_m - real_mtd) / rem) if (has_m and rem) else None
    avg = real_mtd / nd if nd else 0.0
    mxw = max(need or 0, avg) or 1
    if has_m:
        pst = st_chip(projT, metaT_m)
        gapv = projT - metaT_m
        panel = [("Realizado até " + dfmt(D1), f0(real_mtd), fp(real_mtd / mc[nd - 1]) + " da meta parcial" if nd else "—"),
                 ("Gap no fechamento", ("+" if gapv >= 0 else "−") + f0(abs(gapv)), "Acima da meta" if gapv >= 0 else "Faltam para a meta")]
        sub = f"Meta do mês {f0(metaT_m)}"
    else:
        pst = ""
        panel = [("Realizado até " + dfmt(D1), f0(real_mtd), "Sem meta parcial"), ("Gap no fechamento", "—", "Sem meta para comparar")]
        sub = "Sem meta para comparar" if pm in ("vendas", "web", "apf") or D.channel != "cdt" else ("Meta em revisão" if pm == "enc" else "Sem meta carregada")
    if need is None:
        need_txt = "Sem meta parcial: o necessário por dia não é calculado."
    elif rem == 0:
        need_txt = "Mês encerrado."
    else:
        prox = [w["id"] + " (" + w["acao"] + ")" for w in D.weeks if w["b"] > D1 and w["acao"] not in ("—",)]
        need_txt = (f"Faltam {rem} dias até {dfmt(D.Mend)}" + (", incluindo " + prox[-1] if prox else "") + ". "
                    + (f"O necessário por dia é {fp(need / avg - 1, 0)} maior que a média atual." if avg and need > avg else "A média atual já cobre o necessário."))
    proj_lbl = f"Projeção · {MSHORT[pm]} ({PS['fonte']})"
    dark = (f"<div class='g-dark' style='flex:0 1 340px;min-width:300px'><div style='display:flex;flex-direction:column;gap:4px'>"
            f"<span style='font:500 13px/18px Inter'>{esc(proj_lbl)}</span><span class='big'>{esc(f0(projT))}</span>"
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:4px;font:400 13px/18px Inter;color:#B9B6A9'><span>{esc(sub)}</span>{pst}</div></div>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px 20px'>"
            + "".join(f"<div style='display:flex;flex-direction:column;gap:2px'><span class='lb'>{esc(l)}</span><span style='font:500 18px/24px Inter;letter-spacing:-.025em'>{esc(v)}</span><span class='lb'>{esc(s)}</span></div>" for l, v, s in panel)
            + f"</div><div style='display:flex;flex-direction:column;gap:10px'><span class='lb'>Necessário por dia × média atual</span>"
            f"<div style='display:flex;align-items:center;gap:12px'><span class='lb' style='width:80px'>Necessário</span><span class='bar'><span style='width:{(need / mxw * 100) if need else 0:.1f}%;background:{LIME}'></span></span><span style='width:60px;text-align:right;font:500 13px Inter'>{esc(f0(need) if need is not None else '—')}</span></div>"
            f"<div style='display:flex;align-items:center;gap:12px'><span class='lb' style='width:80px'>Média atual</span><span class='bar'><span style='width:{avg / mxw * 100:.1f}%;background:{GREY}'></span></span><span style='width:60px;text-align:right;font:500 13px Inter'>{esc(f0(avg))}</span></div>"
            f"<span class='lb'>{esc(need_txt)}</span></div></div>")
    legend = (f"<div class='g-legend'><span><span class='g-sw' style='background:{INK}'></span>Realizado</span>"
              f"<span><span class='g-sw' style='height:0;border-top:2.5px dashed {INK};border-radius:0'></span>Projeção até {dfmt(D.Mend)}</span>"
              f"<span><span class='g-sw' style='background:{GREY};height:2px'></span>Meta linear (meta × dias ÷ {N})</span>"
              f"<span><span style='display:inline-block;width:24px;height:14px;border-radius:9999px;background:{HATCH};border:1px solid {LINE}'></span>Distância até a meta</span></div>")
    chart = f"<div class='g-card' style='flex:1 1 560px;min-width:0;display:flex;flex-direction:column;gap:16px'><div class='g-h3'>Acumulado contra a meta</div>{legend}{svg}</div>"
    st.markdown(f"<div class='g-wrap' id='sec-proj' style='display:flex;flex-wrap:wrap;gap:20px;margin-top:20px'>{dark}{chart}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------ BLOCO 02 — Dia a dia
def _th(cols):
    return "".join(f"<th title=\"{tip([c[0]] + list(c[1:]))}\">{esc(c[0])}</th>" for c in cols)


def _bloco2(D: Dados):
    M0, D1, N, nd = D.M0, D.D1, D.N, D.nd
    pm = add_months(M0, -1)
    # ---- texto
    wk_closed = [w for w in D.weeks if w["b"] <= D1 and w["id"] != "Pré"]
    lead, txt = "Semana a semana.", ""
    if wk_closed:
        w2 = wk_closed[-1]
        s2 = D.s("vendas", w2["a"], w2["b"])
        m2 = D.meta_sum("vendas", w2["a"], w2["b"])
        w1 = wk_closed[-2] if len(wk_closed) > 1 else None
        s1 = D.s("vendas", w1["a"], w1["b"]) if w1 else None
        if s2 is not None and m2:
            lead = "A semana passada bateu a meta." if s2 >= m2 else "A semana passada ficou abaixo da meta."
            txt = f"A {w2['id']} ({w2['per']}) fechou com {fk(s2)} vendas, {fp(s2 / m2)} da meta da semana" + (f" e {sg(s2 / s1 - 1)} vs {w1['id']}." if s1 else ".")
        elif s2 is not None:
            lead = f"A {w2['id']} fechou com {fk(s2)} vendas."
    lt, lt7 = D.at("leads", D1), D.at("leads", D1 - dt.timedelta(days=7))
    if lt is not None:
        txt += f" {'No ' + DOW[D1.weekday()] if D1.weekday() in (5, 6) else 'Em ' + DOW[D1.weekday()]}, {dfmt(D1)}, entraram {fk(lt)} leads" + (f", {sg(lt / lt7 - 1)} vs o mesmo dia da semana anterior." if lt7 else ".")
    st.markdown(_header("02", "Dia a dia", "Estamos melhorando ou piorando?", lead, txt.strip(), "b2"), unsafe_allow_html=True)

    # ---- último dia fechado
    d7 = D1 - dt.timedelta(days=7)
    head = [("Indicador",), (dfmt(D1), f"Resultado do último dia fechado, {DOW[D1.weekday()]} {dfmt(D1)}.", "É o dado mais recente disponível."),
            ("vs D-7", f"Compara {dfmt(D1)} com o mesmo dia da semana anterior: {dfmt(d7)} ({DOW[d7.weekday()]}).", "Mesmo dia da semana porque fim de semana rende menos que dia útil."),
            ("vs média 7d", f"Compara {dfmt(D1)} com a média diária de {drange(D1 - dt.timedelta(days=7), D1 - dt.timedelta(days=1))}.", "Mostra se o dia ficou acima ou abaixo do ritmo recente."),
            ("Meta do dia",), ("% meta do dia", "Realizado do dia ÷ meta do dia (meta do mês ÷ dias do mês)."),
            (f"Mês até {dfmt(D1)}", f"Total acumulado de {drange(M0, D1)}."), ("Meta parcial", f"Meta do mês × {nd} ÷ {N}.", "Distribui a meta igualmente pelos dias."),
            ("% parcial", f"Mês até {dfmt(D1)} ÷ meta parcial.", "Abaixo de 100% = estamos atrás do ritmo.")]
    rows = []
    for m in ("vendas", "leads", "enc", "tr", "vo"):
        v, b7 = D.at(m, D1), D.at(m, d7)
        a7 = D.s(m, D1 - dt.timedelta(days=7), D1 - dt.timedelta(days=1))
        av = a7 / 7 if a7 is not None else None
        md = D.meta_sum(m, D1, D1) if m in ("vendas", "web", "apf") else None
        mt, mp = D.s(m, M0, D1), D.meta_sum(m, M0, D1)
        mat = m == "vo"
        unit = UNIT[m] if not (m in ("enc", "tr") and (D.leaddef != "abr" or D.dateby != "evento")) else "Contato"
        vcell = (f"<span title=\"{tip(['Em maturação', 'Vendas de leads recentes ainda estão sendo cruzadas (CPF × venda, 30 d)'])}\" style='background:{HATCH};padding:3px 6px;border-radius:9999px;font-weight:600'><span style='background:#FFFFFF;padding:0 5px;border-radius:9999px'>{esc(f0(v))}</span></span>" if mat else esc(f0(v)))
        rows.append(f"<tr><td style='font-weight:500'>{esc(MSHORT[m])} <span class='g-cap'>· {unit}</span></td><td>{vcell}</td>"
                    f"<td>{d_c(v, b7, '', False, f'D-7 · {dfmt(d7)} ({DOW[d7.weekday()]})') if v is not None else '—'}</td>"
                    f"<td>{d_c(v, av, '', True, 'Média 7 dias') if v is not None else '—'}</td><td>{esc(f0(md) if md is not None else '—')}</td>"
                    f"<td>{st_chip(v, md) if (v is not None and md) else chip('neu', '—', False, ['Sem meta diária'])}</td>"
                    f"<td>{esc(f0(mt))}</td><td>{esc(f0(mp) if mp is not None else '—')}</td><td>{st_chip(mt, mp) if (mt is not None and mp) else chip('neu', '—', False, ['Sem meta parcial'])}</td></tr>")
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:28px'><div style='display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap'>"
                f"<div class='g-h3'>Último dia fechado · {dfmt(D1)} ({DOW[D1.weekday()]})</div><span class='g-sub'>dados até {dfmt(D1)}</span></div>"
                f"<div class='g-scroll' style='margin-top:12px'><table class='g-table'><thead><tr>{_th(head)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>", unsafe_allow_html=True)

    # ---- leads por dia (barras + curvas)
    sl, se, stt, svd = (D.arr_month(m, M0) for m in ("leads", "enc", "tr", "vendas"))
    prev_l = D.arr_month("leads", pm)
    L, RR, TT, BB = 56, 1264, 64, 340
    SW = (RR - L) / N
    allv = np.concatenate([np.nan_to_num(sl), np.nan_to_num(prev_l), np.nan_to_num(se), np.nan_to_num(stt), np.nan_to_num(svd)])
    ymax = max(float(np.max(allv)) if allv.size else 1.0, 1.0) * 1.12
    step = nice(ymax)
    ytop = math.ceil(ymax / step) * step
    ys = lambda v: BB - (v / ytop) * (BB - TT)   # noqa: E731
    cx = lambda i: L + SW * i + SW / 2           # noqa: E731
    parts = [f"<svg viewBox='0 0 1280 400' width='100%' style='display:block;overflow:visible'>"]
    for i in range(N):
        d = M0 + dt.timedelta(days=i)
        if D.is_we(d):
            parts.append(f"<rect x='{L + SW * i + 1:.1f}' y='64' width='{SW - 2:.1f}' height='276' rx='8' fill='#F4F3EE'/>")
    for w in D.weeks:
        ia, ib = (w["a"] - M0).days, (w["b"] - M0).days
        cur = w["a"] <= D1 + dt.timedelta(days=1) <= w["b"]
        lbl = "Pré-S1" if w["id"] == "Pré" else f"{w['id']} · {w['acao']}"
        parts.append(f"<rect x='{L + SW * ia + 3:.1f}' y='12' width='{SW * (ib - ia + 1) - 6:.1f}' height='32' rx='16' fill='{INK if cur else SOFT}'/>"
                     f"<text x='{L + SW * (ia + ib + 1) / 2:.1f}' y='33' text-anchor='middle' font-size='12' font-weight='500' fill='{'#FFFFFF' if cur else MUTED}' font-family='Inter,system-ui,sans-serif'>{esc(lbl)}</text>")
    parts.append(_svg_grid(ys, ytop, step, L, RR, 48))
    for i in range(nd):
        v = sl[i]
        if not np.isnan(v):
            hd = i == nd - 1
            parts.append(f"<rect x='{cx(i) - 12:.1f}' y='{ys(v):.1f}' width='24' height='{max(0.0, BB - ys(v)):.1f}' rx='8' fill='{'url(#g-dh)' if hd else BAR}' stroke='{SAND if hd else 'none'}'/>")
    def _line(arr, color, dash="", width=2.5, n=None):
        pts = [(cx(i), ys(arr[i])) for i in range(n if n is not None else len(arr)) if i < len(arr) and not np.isnan(arr[i])]
        return f"<path d='{smooth(pts)}' fill='none' stroke='{color}' stroke-width='{width}' stroke-dasharray='{dash}' stroke-linecap='round'/>" if pts else ""
    parts.append(f"<defs><pattern id='g-dh' width='6' height='6' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><rect width='6' height='6' fill='#FFFFFF'/><rect width='1.5' height='6' fill='{SAND}'/></pattern></defs>")
    parts.append(_line(prev_l, LIGHT, "4 4", 2, min(len(prev_l), N)))
    parts.append(_line(se, GREY, "", 2.5, nd))
    parts.append(_line(stt, DARK, "", 2.5, nd))
    parts.append(_line(svd, GREEN, "", 2.5, nd))
    if nd and not np.isnan(sl[nd - 1]):
        pt = f0(sl[nd - 1])
        pw = len(pt) * 9 + 24
        parts.append(f"<rect x='{cx(nd - 1) - pw / 2:.1f}' y='{ys(sl[nd - 1]) - 40:.1f}' width='{pw}' height='28' rx='14' fill='{INK}'/>"
                     f"<text x='{cx(nd - 1):.1f}' y='{ys(sl[nd - 1]) - 21:.1f}' text-anchor='middle' font-size='12' font-weight='600' fill='#FFFFFF' font-family='Inter,system-ui,sans-serif'>{esc(pt)}</text>")
    if M0 <= D.hoje <= D.Mend:
        ih = (D.hoje - M0).days
        parts.append(f"<line x1='{L + SW * ih:.1f}' x2='{L + SW * ih:.1f}' y1='64' y2='340' stroke='{INK}' stroke-dasharray='3 4'/>"
                     f"<text x='{L + SW * ih:.1f}' y='58' text-anchor='middle' font-size='11' font-weight='500' fill='{INK}' font-family='Inter,system-ui,sans-serif'>hoje · {dfmt(D.hoje)}</text>")
    if nd < N:
        gapd = (D.hoje - D1).days - 1
        parts.append(f"<text x='{L + SW * (nd + (N - nd) / 2):.1f}' y='200' text-anchor='middle' font-size='12' fill='{MUTED2}' font-family='Inter,system-ui,sans-serif'>Dias ainda não fechados" + (f" · {dfmt(D1 + dt.timedelta(days=1))} ainda sem dado (—)" if gapd >= 1 else "") + "</text>")
    for i in range(N):
        d = M0 + dt.timedelta(days=i)
        parts.append(f"<text x='{cx(i):.1f}' y='364' text-anchor='middle' font-size='11' fill='{GREY if D.is_we(d) else MUTED}' font-family='Inter,system-ui,sans-serif'>{d.day:02d}</text>")
        if i < nd:
            lines = [f"{dfmt(d)} ({DOW[d.weekday()]})", f"Leads Únicos {f0(sl[i])}",
                     f"Pipe Televendas {f0(se[i])}" + (f" · {fp(se[i] / sl[i])}" if sl[i] else ""),
                     f"Transbordados Franquia {f0(stt[i])}" + (f" · {fp(stt[i] / se[i])}" if se[i] else ""), f"Vendas {f0(svd[i])}"]
        else:
            lines = [f"{dfmt(d)} ({DOW[d.weekday()]})", "Sem dado nem previsão: —" if i == nd else "Dia ainda não fechado"]
        parts.append(f"<rect x='{L + SW * i:.1f}' y='64' width='{SW:.1f}' height='276' fill='transparent'><title>{tip(lines)}</title></rect>")
    parts.append(f"<text x='56' y='390' font-size='12' font-weight='500' fill='{MUTED}' font-family='Inter,system-ui,sans-serif'>{MES_PT_LONGO[M0.month - 1].lower()}</text></svg>")
    legend = (f"<div class='g-legend'><span><span class='g-dot' style='background:{BAR};width:12px;height:12px;border-radius:4px'></span>Leads Únicos</span>"
              f"<span><span class='g-sw' style='border-top:2px dashed {LIGHT};height:0;border-radius:0'></span>Leads Únicos em {MES_PT[pm.month - 1]}</span>"
              f"<span><span class='g-sw' style='background:{GREY}'></span>Pipe Televendas</span><span><span class='g-sw' style='background:{DARK}'></span>Transbordados Franquia</span>"
              f"<span><span class='g-sw' style='background:{GREEN}'></span>Vendas</span><span><span style='display:inline-block;width:14px;height:14px;border-radius:4px;background:{SOFT}'></span>Fim de semana</span></div>")
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px;display:flex;flex-direction:column;gap:12px'><div style='display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start'>"
                f"<div><div class='g-h3'>Leads por dia · {drange(M0, D.Mend)}</div><span class='g-sub'>Barra compara o volume do dia; curvas mostram para onde vão (distribuição, franquias) e as vendas</span></div>{legend}</div>{''.join(parts)}</div>", unsafe_allow_html=True)



def _bloco2_tabela(D: Dados, det):
    M0, D1, N, nd = D.M0, D.D1, D.N, D.nd
    sl, se, stt, svd = (D.arr_month(m, M0) for m in ("leads", "enc", "tr", "vendas"))
    svo = D.arr_month("vo", M0)
    head = [("Data",), ("Dia",), ("Leads", "Contato"), ("Δ vs D-7",), ("Encaminhados", "Pipe Televendas"), ("% encam.",), ("Transbordados", "Transbordados Franquia"), ("% transb.",),
            ("Vendas originadas", "Contato com venda em ≤ 30 d"), ("Meta do dia", "Vendas"), ("% meta", "Vendas do dia ÷ meta do dia"), ("Vendas",), ("Acumulado", "Leads Únicos")]
    show = [0, 1, 2, 3, 4, 6, 8, 11] if not det else list(range(len(head)))
    acc = np.nancumsum(np.nan_to_num(sl[:nd]))
    trs = []
    if nd < N:
        trs.append(f"<tr><td colspan='{len(show)}' style='text-align:left;color:{MUTED2}'>📅 {drange(D1 + dt.timedelta(days=1), D.Mend)} · {N - nd} dias ainda não fechados.</td></tr>")
    for i in range(nd - 1, -1, -1):
        d = M0 + dt.timedelta(days=i)
        v = sl[i]
        d7v = D.at("leads", d - dt.timedelta(days=7))
        mat = i >= nd - 10
        md = D.meta_sum("vendas", d, d)
        vd = svd[i]
        vo_cell = (f"<span title=\"{tip(['Em maturação', 'Cruzamento CPF × venda ainda incompleto (janela de 30 d)'])}\" style='background:{HATCH};padding:3px 6px;border-radius:9999px;font-weight:600'><span style='background:#FFFFFF;padding:0 5px;border-radius:9999px'>{esc(f0(svo[i]))}</span></span>" if mat else esc(f0(svo[i])))
        cells = [esc(dfmt(d)), f"<span style='color:{MUTED2 if D.is_we(d) else INK}'>{DOW[d.weekday()]}</span>", esc(f0(v)), d_c(v, d7v, "", False, f"D-7 · {dfmt(d - dt.timedelta(days=7))}") if not np.isnan(v) else "—",
                 esc(f0(se[i])), esc(fp(se[i] / v) if v else "—"), esc(f0(stt[i])), esc(fp(stt[i] / se[i]) if se[i] else "—"), vo_cell,
                 esc(f0(md) if md is not None else "—"), st_chip(vd, md) if (md and not np.isnan(vd)) else chip("neu", "—", False, ["Sem meta diária"]), esc(f0(vd)), esc(f0(acc[i]))]
        _left = " style='text-align:left'"
        trs.append("<tr>" + "".join(f"<td{_left if j in (0, 1) else ''}>{cells[j]}</td>" for j in show) + "</tr>")
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'>"
                f"<div><div class='g-h3'>Tabela diária</div><span class='g-sub'>Vendas originadas dos últimos 10 dias seguem em maturação (CPF × venda, 30 d) · unidade Contato; Encaminhados/Transbordados em {'Negócio' if (D.leaddef == 'abr' and D.dateby == 'evento') else 'Contato'}</span></div></div>"
                f"<div class='g-scroll' style='margin-top:12px'><table class='g-table'><thead><tr>{_th([head[j] for j in show])}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
                f"<div class='g-cap' style='margin-top:10px'>Exibindo 1–{nd} de {nd} dias fechados · fim da lista</div></div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------ BLOCO 03 — Canais
def _tree_stats(D: Dados):
    """Métricas por nó da árvore para o mês corrente (vendas, metas, trechos anterior/ano, projeção, leads do lead)."""
    M0, D1, nd = D.M0, D.D1, D.nd
    pm0 = add_months(M0, -1)
    pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
    ya = add_months(M0, -12)
    yb = min(ya + dt.timedelta(days=nd - 1), month_end(ya))
    tot_prev_full = None
    out = {}
    for cid in NODE:
        n = NODE[cid]
        tipos = [t for t in tipos_of(cid) if t in D.V.columns]
        def ssum(a, b):
            if not tipos:
                return 0.0
            return float(D.V[tipos].loc[pd.Timestamp(a):pd.Timestamp(min(b, D1))].sum().sum()) if a <= min(b, D1) else 0.0
        real = ssum(M0, D1)
        prevT = ssum(pm0, pb)
        prevF = ssum(pm0, month_end(pm0))
        yago = ssum(ya, yb) if ya >= D.idx[0].date() else None
        metaM = D.node_meta(cid)
        own = D.node_has_own_meta(cid)
        metaP = metaM * nd / D.N if metaM else None
        out[cid] = dict(id=cid, name=n["name"], level=n["level"], leaf=n["leaf"], real=real, prevT=prevT, prevF=prevF, yago=yago,
                        metaM=metaM, metaP=metaP, own=own, dot=dot_of(cid))
    for cid, r in out.items():
        n = NODE[cid]
        if r["own"] or n["leaf"]:
            r["realPct"] = r["real"]
        else:
            kids_meta = [out[k] for k in leaves_of(cid) if out[k]["metaP"]]
            r["realPct"] = sum(k["real"] for k in kids_meta) if kids_meta else r["real"]
    # projeção por nó: Prophet do nó quando há, senão rateio pelo realizado do CDT
    pj_cdt = D.projecao("vendas") if D.channel == "cdt" else None
    tot = out["cdt"]["real"] or 1.0
    for cid, r in out.items():
        fc = D.forecast_daily(cid)
        if fc is not None:
            r["proj"] = r["real"] + float(fc.loc[[pd.Timestamp(M0 + dt.timedelta(days=i)) for i in range(nd, D.N) if pd.Timestamp(M0 + dt.timedelta(days=i)) in fc.index]].sum())
            r["proj_src"] = "Prophet balanced"
        elif pj_cdt is not None:
            r["proj"] = r["real"] * pj_cdt["proj_total"] / tot
            r["proj_src"] = "rateado pelo realizado"
        else:
            r["proj"] = None
            r["proj_src"] = "—"
    # vendas por lead (vendas originadas, Contato) por tipo
    vo_by_tipo = {}
    met = "vo_foto" if D.dateby == "evento" else "vo_safra"
    if met in D.VO:
        sub = D.VO[met]
        sub = sub[(sub["bucket"].isin(D.buckets)) & (sub["ts"] >= pd.Timestamp(M0)) & (sub["ts"] <= D.T1)]
        vo_by_tipo = sub.groupby("tipo")["valor"].sum().to_dict()
    for cid, r in out.items():
        tipos = tipos_of(cid)
        r["vo"] = sum(vo_by_tipo.get(t, 0.0) for t in tipos) if vo_by_tipo else None
    return out


def _bloco3(D: Dados, show_zero):
    M0, D1, nd = D.M0, D.D1, D.nd
    pm0 = add_months(M0, -1)
    pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
    tr_lbl = f"{drange(pm0, pb)}"
    T = _tree_stats(D)
    # ---- texto
    cdt, fra, nac = T["cdt"], T["fra"], T["nac"]
    lead, txt = "Leitura por canal.", ""
    if cdt["real"]:
        share_f = fra["real"] / cdt["real"]
        groups = [(g, T[g]) for g in ("fra", "nac") if T[g]["metaP"]]
        worst = min(groups, key=lambda g: g[1]["realPct"] / g[1]["metaP"]) if groups else None
        if worst:
            g, r = worst
            lead = f"O atraso está {'nas Franquias' if g == 'fra' else 'nos canais Nacionais'}." if r["realPct"] / r["metaP"] < 1 else "Os dois grupos estão no ritmo da meta."
            txt = (f"{'Franquias respondem' if g == 'fra' else 'Os Nacionais respondem'} por {fp(share_f if g == 'fra' else 1 - share_f, 0)} das vendas e estão em {fp(r['realPct'] / r['metaP'])} da meta parcial")
            leaves_bad = sorted([T[l] for l in leaves_of(g) if T[l]["metaP"] and T[l]["realPct"] / T[l]["metaP"] < .9], key=lambda x: x["metaP"] - x["real"], reverse=True)
            if leaves_bad:
                lb = leaves_bad[0]
                txt += f"; só o {lb['name']} está {fk(lb['metaP'] - lb['real'])} vendas abaixo do ritmo."
            else:
                txt += "."
            other = T["nac" if g == "fra" else "fra"]
            if other["metaP"]:
                txt += f" {other['name']} está em {fp(other['realPct'] / other['metaP'])}."
            acima = [T[l]["name"] for l in LEAVES if T[l]["metaP"] and T[l]["realPct"] / T[l]["metaP"] >= 1]
            if acima:
                txt += f" {' e '.join(acima[:3])} {'é o único canal' if len(acima) == 1 else 'são os canais'} acima da meta parcial."
    st.markdown(_header("03", "Canais", "Onde está o problema?", lead, txt, "b3"), unsafe_allow_html=True)

    # ---- destaques
    lv = [T[l] for l in LEAVES if show_zero or T[l]["real"] > 0]
    def item(r, c, sub):
        return (f"<div class='it' title=\"{tip([r['name'], 'Vendas ' + f0(r['real']), f'{MES_PT[pm0.month - 1]}, mesmo trecho: ' + f0(r['prevT'])])}\">"
                f"<div><div class='nm'><span class='g-dot' style='background:{r['dot']};margin-right:8px'></span>{esc(r['name'])}</div><div class='sb'>{esc(sub)}</div></div>{c}</div>")
    below = sorted([r for r in lv if r["metaP"] and r["real"] / r["metaP"] < .9], key=lambda r: r["real"] / r["metaP"])
    withd = [(r, r["real"] / r["prevT"] - 1) for r in lv if r["prevT"] > 0]
    ups = sorted([x for x in withd if x[1] > 0], key=lambda x: -x[1])[:3]
    downs = sorted([x for x in withd if x[1] < 0], key=lambda x: x[1])[:3]
    hls = [("Abaixo do ritmo (<90%)", "% da meta parcial · somente canais", [item(r, st_chip(r["real"], r["metaP"]), f"{f0(r['real'])} de {f0(r['metaP'])} · {fk(r['metaP'] - r['real'])} abaixo") for r in below]),
           ("Maiores altas", f"Vendas vs mesmo trecho de {MES_PT[pm0.month - 1]} ({tr_lbl})", [item(r, d_chip(r["real"], r["prevT"], "", True, "Mesmo trecho do mês anterior"), f"{f0(r['real'])} vendas") for r, _ in ups]),
           ("Maiores quedas", f"Vendas vs mesmo trecho de {MES_PT[pm0.month - 1]} ({tr_lbl})", [item(r, d_chip(r["real"], r["prevT"], "", True, "Mesmo trecho do mês anterior"), f"{f0(r['real'])} vendas") for r, _ in downs])]
    html = "".join(f"<div class='g-hl'><div><div class='g-h3'>{esc(t)}</div><div class='g-sub'>{esc(s)}</div></div>{''.join(items) if items else '<div class=g-cap>Nenhum canal nesta lista.</div>'}</div>" for t, s, items in hls)
    st.markdown(f"<div class='g-wrap g-grid3' style='margin-top:28px'>{html}</div>", unsafe_allow_html=True)
    return T



def _bloco3_tabela(D: Dados, show_zero, det, only_groups):
    M0, D1, nd = D.M0, D.D1, D.nd
    pm0 = add_months(M0, -1)
    pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
    tr_lbl = f"{drange(pm0, pb)}"
    T = _tree_stats(D)
    lv = [T[l] for l in LEAVES if show_zero or T[l]["real"] > 0]
    head = [("Canal", "Hierarquia sem duplicidade"), ("Vendas", f"Realizado até {dfmt(D1)}"), ("Δ vs anterior", f"Mesmo trecho de {MES_PT[pm0.month - 1]} ({tr_lbl})"),
            ("Meta parcial", f"Meta do mês × {nd} ÷ {D.N}"), ("% parcial", "Canais sem meta ficam fora do % do grupo"), ("Meta total", "Meta do mês civil"),
            ("Projeção", "Prophet balanced por grupo; canais sem previsão própria rateados pelo realizado"), ("Δ vs ano passado", "Mesmo trecho do ano anterior"),
            ("Vendas originadas", "Contatos com venda em ≤ 30 d da criação, por tipo de venda · Contato"), ("% das vendas", "Vendas originadas de lead ÷ vendas do canal")]
    show = list(range(len(head))) if det else [0, 1, 2, 3, 4, 8]
    rows, csv_rows = [], []
    for cid in NODE:
        r = T[cid]
        if not (show_zero or r["real"] > 0 or not r["leaf"]):
            continue
        if only_groups and r["level"] > 1:
            continue
        pc_tip = None if not r["metaP"] else [fp(r["realPct"] / r["metaP"]) + " da meta parcial", f0(r["realPct"]) + " de " + f0(r["metaP"]), "Exclui canais sem meta" if r["realPct"] != r["real"] else ""]
        hl = "background:#F4F3EE;" if (cid == D.channel and cid != "cdt") else ""
        name = (f"<div style='display:flex;align-items:center;gap:8px;padding-left:{r['level'] * 22}px;font-weight:{400 if r['leaf'] else 600}'>"
                f"<span class='g-dot' style='background:{r['dot']}'></span><span>{esc(r['name'])}</span></div>")
        cells = [name, esc(f0(r["real"])), d_c(r["real"], r["prevT"], "", True, f"Mesmo trecho de {MES_PT[pm0.month - 1]} ({tr_lbl})"),
                 esc(f0(r["metaP"]) if r["metaP"] else "—"), st_chip(r["realPct"], r["metaP"], pc_tip), esc(f0(r["metaM"]) if r["metaM"] else "—"),
                 f"<span title=\"{tip([r['proj_src']])}\">{esc(f0(r['proj']) if r['proj'] is not None else '—')}</span>",
                 d_c(r["real"], r["yago"], "", False, "Mesmo trecho do ano anterior"), esc(f0(r["vo"]) if r["vo"] is not None else "—"),
                 esc(fp(r["vo"] / r["real"]) if (r["vo"] is not None and r["real"]) else "—")]
        rows.append(f"<tr style='{hl}'>" + "".join(f"<td style='{hl}'>{cells[j]}</td>" for j in show) + "</tr>")
        csv_rows.append(dict(Canal=r["name"], Nivel=r["level"], Vendas=int(r["real"]), MetaParcial=r["metaP"], PctParcial=(r["realPct"] / r["metaP"]) if r["metaP"] else None,
                             MetaTotal=r["metaM"], Projecao=r["proj"], TrechoAnterior=r["prevT"], AnoAnterior=r["yago"], VendasOriginadas=r["vo"]))
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px'><div style='display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap'><div class='g-h3'>Vendas e leads por canal</div>"
                f"<span class='g-sub'>{drange(M0, D1)} · Venda = CPF × DT_FILIACAO no NOMINAL</span></div>"
                f"<div class='g-scroll' style='margin-top:12px'><table class='g-table'><thead><tr>{_th([head[j] for j in show])}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>", unsafe_allow_html=True)

    # ---- participação
    tot, totP = T["cdt"]["real"] or 1.0, T["cdt"]["prevT"] or 1.0
    lv2 = sorted(lv, key=lambda r: -r["real"])
    if lv2:
        mx = max(max(r["real"] / tot, r["prevT"] / totP) for r in lv2) or 1
        mix = []
        for r in lv2:
            s_, ps = r["real"] / tot, r["prevT"] / totP
            d = (s_ - ps) * 100
            tone = "neu" if abs(d) < .05 else "ok" if d > 0 else "bad"
            fg, bg = TONE[tone]
            mix.append(f"<div class='g-wrap' style='display:contents' title=\"{tip([r['name'], f'{MES_PT[M0.month - 1]}: ' + fp(s_) + ' das vendas', f'{MES_PT[pm0.month - 1]}, mesmo trecho: ' + fp(ps)])}\">"
                       f"<span style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis'><span class='g-dot' style='background:{r['dot']};margin-right:8px'></span>{esc(r['name'])}</span>"
                       f"<span style='display:flex;flex-direction:column;gap:3px'><span style='display:block;height:12px;border-radius:9999px;background:{r['dot']};width:{s_ / mx * 100:.1f}%'></span>"
                       f"<span style='display:block;height:4px;border-radius:9999px;background:{LIGHT};width:{ps / mx * 100:.1f}%'></span></span>"
                       f"<span style='text-align:right;font-weight:500'>{esc(fp(s_))}</span><span style='text-align:right'><span style='display:inline-block;padding:2px 8px;border-radius:9999px;font:600 12px Inter;color:{fg};background:{bg}'>{('+' if d >= 0 else '−') + f'{abs(d):.1f}'.replace('.', ',')} p.p.</span></span></div>")
        legend = (f"<div class='g-legend'><span><span class='g-dot' style='background:{DARK}'></span>Nacional · {MES_PT[M0.month - 1]} até {dfmt(D1)}</span>"
                  f"<span><span class='g-dot' style='background:{GREY}'></span>Franquias · {MES_PT[M0.month - 1]} até {dfmt(D1)}</span>"
                  f"<span><span class='g-sw' style='background:{LIGHT};height:4px'></span>{MES_PT[pm0.month - 1]} · mesmo trecho ({tr_lbl})</span></div>")
        st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px;display:flex;flex-direction:column;gap:16px'><div style='display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:center'><div class='g-h3'>Participação nas vendas</div>{legend}</div>"
                    f"<div class='g-mix'>{''.join(mix)}</div></div>", unsafe_allow_html=True)
    return pd.DataFrame(csv_rows)


# ------------------------------------------------------------------------------------------------ BLOCO 04 — Leads e funil
def _bloco4(D: Dados):
    M0, D1, nd, N = D.M0, D.D1, D.nd, D.N
    pm0 = add_months(M0, -1)
    pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
    keys = ["leads", "enc", "tr", "vo"]
    fv = [D.s(m, M0, D1) for m in keys]
    fprev_t = [D.s(m, pm0, pb) for m in keys]
    fprev_f = [D.s(m, pm0, month_end(pm0)) for m in keys]
    # ---- texto
    lead, txt = "Leads e conversão.", ""
    if fv[0] and fprev_t[0]:
        dl = fv[0] / fprev_t[0] - 1
        de = (fv[1] / fprev_t[1] - 1) if (fv[1] is not None and fprev_t[1]) else None
        r_now = fv[1] / fv[0] if fv[1] is not None else None
        r_prev = fprev_t[1] / fprev_t[0] if (fprev_t[1] is not None and fprev_t[0]) else None
        conv = fv[3] / fv[0] if fv[3] is not None else None
        if de is not None and dl > 0 and de < dl - .1:
            lead = "Os leads estão chegando, mas não estão convertendo no mesmo ritmo."
        elif dl >= 0:
            lead = "Os leads estão chegando e a esteira acompanha."
        else:
            lead = "Entraram menos leads que no mesmo trecho do mês anterior."
        txt = f"Entraram {fp(abs(dl), 0)} {'mais' if dl >= 0 else 'menos'} leads que no mesmo trecho de {MES_PT[pm0.month - 1]}"
        if de is not None:
            txt += f", os encaminhados {'cresceram' if de >= 0 else 'caíram'} {fp(abs(de), 0)}"
        if r_now is not None and r_prev is not None:
            txt += f" e a taxa de encaminhamento {'subiu' if r_now >= r_prev else 'caiu'} de {fp(r_prev)} para {fp(r_now)}."
        else:
            txt += "."
        if conv is not None:
            txt += f" As vendas originadas estão em {fp(conv)} dos leads, com parte ainda em maturação."
    st.markdown(_header("04", "Leads e funil", "Os leads estão chegando e convertendo?", lead, txt, "b4"), unsafe_allow_html=True)


def _bloco4_funil(D: Dados, funnel_mode, show_zero):
    M0, D1, nd, N = D.M0, D.D1, D.nd, D.N
    pm0 = add_months(M0, -1)
    pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
    keys = ["leads", "enc", "tr", "vo"]
    fv = [D.s(m, M0, D1) for m in keys]
    fprev_t = [D.s(m, pm0, pb) for m in keys]
    fprev_f = [D.s(m, pm0, month_end(pm0)) for m in keys]
    # ---- funil
    unit_enc = "Negócio" if (D.leaddef == "abr" and D.dateby == "evento") else "Contato"
    names = [("Leads Únicos", "Contatos criados no período"), ("Entraram na distribuição", f"{unit_enc} · pipeline CDT - Distribuição (D5)"),
             ("Transbordados para franquias", f"{unit_enc} · 1ª entrada em Distribuição/Validador"), ("Vendas originadas de lead", "Contato · 1ª venda em ≤ 30 d (CPF → celular)")]
    top = fv[0] or 1.0
    ano = D.compare == "ano"
    stages = []
    for i, m in enumerate(keys):
        v = fv[i]
        last = i == 3
        rate = ""
        if i and v is not None:
            base = fv[i - 1] if funnel_mode == "prev" else fv[0]
            rate = (fp(v / base) + (" da etapa anterior" if funnel_mode == "prev" else " do total que entrou")) if base else "—"
        chips = []
        if v is not None:
            c1 = d_chip(v, fprev_f[i], f"vs {MES_PT[pm0.month - 1]} inteiro", False, f"{MES_PT_LONGO[pm0.month - 1]} inteiro")
            c2 = d_chip(v, fprev_t[i], f"vs {drange(pm0, pb)}", True, f"Mesmo trecho de {MES_PT[pm0.month - 1]}")
            chips = [c for c in (c1, c2) if c]
        w = (v / top * 88) if v else 0
        tp = [names[i][0], f"{f0(v)} até {dfmt(D1)}", (f"{fp(v / fv[i - 1])} da etapa anterior · {fp(v / fv[0])} do total" if (i and v is not None and fv[i - 1]) else "Topo do funil")]
        if last and v is not None and fv[2]:
            tp.append(f"{fp(v / fv[2])} dos transbordados · em maturação (últimos 10 dias ainda cruzando CPF × venda)")
        stages.append((f"<div class='rate'>{('↓ ' + rate) if rate else ''}</div>" if i else "") +
                      f"<div class='st' title=\"{tip(tp)}\"><div><div style='font:500 14px/20px Inter'>{esc(names[i][0])}</div><div class='g-cap'>{esc(names[i][1])}</div></div>"
                      f"<div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'><span style='display:block;height:28px;border-radius:9999px;background:{GREEN if last else DARK};width:{w:.2f}%;min-width:4px'></span>"
                      f"<span style='font:500 18px/24px Inter;letter-spacing:-.025em'>{esc(f0(v))}</span><span style='display:flex;gap:6px;flex-wrap:wrap'>{''.join(chips)}</span></div></div>")
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:28px;display:flex;flex-direction:column;gap:8px'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'>"
                f"<div><div class='g-h3'>Do lead único à venda originada</div><span class='g-sub'>{drange(M0, D1)} · comprimento proporcional ao volume · definição {LEADDEF[D.leaddef][0]}" + ("" if D.channel == "cdt" else f" · vendas originadas filtradas por {D.node['name']}") + "</span></div></div>"
                f"<div class='g-fun'>{''.join(stages)}</div></div>", unsafe_allow_html=True)

    # ---- heatmap dia × bucket de origem (Contato)
    if "leads" in D.J:
        tb = D.J["leads"].loc[pd.Timestamp(M0):D.T1]
        cols = [b for b in BUCKETS_ALL if b in tb.columns and (show_zero or float(tb[b].fillna(0).sum()) > 0)]
        hdr = "".join(f"<span style='text-align:center;color:{GREY if D.is_we(M0 + dt.timedelta(days=i)) else MUTED}'>{(M0 + dt.timedelta(days=i)).day:02d}</span>" for i in range(N))
        rows = []
        for b in cols:
            vals = tb[b].fillna(0.0).to_numpy()
            mean = float(np.mean(vals[:nd])) if nd else 0.0
            cells = []
            for i in range(N):
                d = M0 + dt.timedelta(days=i)
                if i >= nd:
                    cells.append(f"<span class='c' title=\"{tip([BUCKET_NAME.get(b, b) + ' · ' + dfmt(d), 'Dia ainda não fechado'])}\" style='border:1.5px dashed {LINE}'></span>")
                    continue
                v = vals[i] if i < len(vals) else 0.0
                r = v / mean if mean else 0
                k = 0 if r < .75 else 1 if r < .92 else 2 if r < 1.08 else 3 if r < 1.25 else 4
                cells.append(f"<span class='c' title=\"{tip([BUCKET_NAME.get(b, b) + ' · ' + dfmt(d) + ' (' + DOW[d.weekday()] + ')', 'Leads ' + f0(v), ('+' if r >= 1 else '−') + fp(abs(r - 1), 0) + ' vs média do bucket'])}\" style='background:{HEAT[k]};{'border:1px solid #EDECE6' if k == 0 else ''}'></span>")
            excl = b not in D.buckets
            rows.append(f"<div class='r' style='{'opacity:.45;' if excl else ''}' title=\"{tip([BUCKET_NAME.get(b, b), 'Fora da definição ' + LEADDEF[D.leaddef][0] if excl else 'Dentro da definição ' + LEADDEF[D.leaddef][0]])}\"><span class='g-dot' style='background:{GREEN if b == 'core' else GREY if b.startswith('franquia') else DARK}'></span>{esc(BUCKET_NAME.get(b, b))}</div>" + "".join(cells))
        scale = "".join(f"<span style='display:inline-block;width:14px;height:14px;border-radius:4px;background:{c}'></span>" for c in HEAT)
        st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px;display:flex;flex-direction:column;gap:14px'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'>"
                    f"<div><div class='g-h3'>Leads gerados · dia × origem</div><span class='g-sub'>Contatos criados por dia e bucket do canal de origem (HubSpot) · intensidade relativa à média diária de cada bucket · buckets fora da definição escolhida ficam esmaecidos</span></div>"
                    f"<div class='g-legend'><span>abaixo</span>{scale}<span>acima da média</span><span><span style='display:inline-block;width:14px;height:14px;border-radius:4px;border:1.5px dashed {LINE}'></span>dia futuro</span></div></div>"
                    f"<div class='g-scroll'><div class='g-heat' style='grid-template-columns:200px repeat({N},minmax(22px,1fr));min-width:900px'><span></span>{hdr}{''.join(rows)}</div></div></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='g-wrap g-card' style='margin-top:20px'><div class='g-h3'>Leads gerados · dia × origem</div><div class='g-cap' style='margin-top:8px'>Tabela `alex_ger_dash_dia` sem dados — rode `gt7 run gerencial_dash --arg since=2026-05-01` no claude-toolkit e clique em ♻️ Recarregar dados.</div></div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------ BLOCO 05 — Histórico
def _bloco5(D: Dados):
    M0, D1, nd, N = D.M0, D.D1, D.nd, D.N
    months = [add_months(M0, -k) for k in range(5, -1, -1)]
    series = [("Leads Únicos", LIGHT, "leads"), ("Pipe Televendas", GREY, "enc"), ("Transbordados Franquia", DARK, "tr"), ("Vendas", GREEN, "vendas")]
    vals, orig = {}, set()
    for _, _, m in series:
        vals[m] = []
        for mm in months:
            v, o = D.s_hist(m, mm, month_end(mm))
            vals[m].append(v)
            if o == "jornada":
                orig.add(MES_PT[mm.month - 1])
    # ---- texto
    lead, txt = "Série dos últimos meses.", ""
    try:
        conv = [(vals["vendas"][i] / vals["leads"][i]) if (vals["leads"][i] and vals["vendas"][i] is not None) else None for i in range(6)]
        c_ok = [(i, c) for i, c in enumerate(conv[:-1]) if c is not None]
        pm0 = add_months(M0, -1)
        pb = min(pm0 + dt.timedelta(days=nd - 1), month_end(pm0))
        v_now, v_prev_t = vals["vendas"][-1], D.s("vendas", pm0, pb)
        ya = add_months(M0, -12)
        v_yago = D.s("vendas", ya, min(ya + dt.timedelta(days=nd - 1), month_end(ya)))
        if len(c_ok) >= 2:
            (i0, c0), (i1, c1) = c_ok[0], c_ok[-1]
            trend_up = c1 > c0
            mes_atual = MES_PT_LONGO[M0.month - 1]
            if v_now is not None and v_prev_t:
                d_m = v_now / v_prev_t - 1
                lead = (f"{mes_atual} {'quebra' if (trend_up and d_m < 0) else 'mantém' if (trend_up and d_m >= 0) else 'segue'} a tendência {'de melhora' if trend_up else 'de queda'} dos últimos meses.")
                txt = (f"De {MES_PT[months[i0].month - 1]} a {MES_PT[months[i1].month - 1]}, a conversão de lead em venda {'subiu' if trend_up else 'caiu'} de {fp(c0)} para {fp(c1)}"
                       f"{', mesmo com menos leads' if vals['leads'][i1] < vals['leads'][i0] else ''}. Em {MES_PT[M0.month - 1]}, as vendas estão {fp(abs(d_m), 0)} {'abaixo' if d_m < 0 else 'acima'} do mesmo trecho de {MES_PT[pm0.month - 1]}"
                       + (f" e {fp(abs(v_now / v_yago - 1), 0)} {'abaixo' if v_now < v_yago else 'acima'} de {MES_PT[ya.month - 1]}/{str(ya.year)[2:]}." if v_yago else "."))
    except Exception:  # noqa: BLE001
        pass
    st.markdown(_header("05", "Histórico", "Como chegamos até aqui?", lead, txt, "b5"), unsafe_allow_html=True)

    # ---- série mensal
    ML, MR, MT, MB = 80, 1264, 16, 272
    allv = [v for s_ in vals.values() for v in s_ if v is not None]
    mmax = max(allv + [1.0]) * 1.1
    step = nice(mmax)
    mtop = math.ceil(mmax / step) * step
    mys = lambda v: MB - (v / mtop) * (MB - MT)   # noqa: E731
    gw = (MR - ML) / 6
    parts = [f"<svg viewBox='0 0 1280 320' width='100%' style='display:block;overflow:visible'><defs><pattern id='g-mh2' width='6' height='6' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><rect width='2' height='6' fill='rgba(255,255,255,.55)'/></pattern></defs>",
             _svg_grid(mys, mtop, step, ML, MR, 70)]
    for i, mm in enumerate(months):
        for j, (nm, color, m) in enumerate(series):
            v = vals[m][i]
            x = ML + gw * i + gw / 2 - 80 + j * 40
            lbl = f"{nm} · {MES_PT[mm.month - 1]}" + (f" (até {dfmt(D1)})" if i == 5 else "")
            if v is None:
                parts.append(f"<rect x='{x:.1f}' y='{MB - 4}' width='34' height='4' rx='2' fill='{LINE}'><title>{tip([lbl, 'Sem dado'])}</title></rect>")
                continue
            pv = vals[m][i - 1] if i else None
            ch = (v / pv - 1) if pv else None
            parts.append(f"<rect x='{x:.1f}' y='{mys(v):.1f}' width='34' height='{MB - mys(v):.1f}' rx='8' fill='{color}'><title>{tip([lbl, f0(v), (sg(ch) + ' vs ' + MES_PT[months[i - 1].month - 1]) if ch is not None else ''])}</title></rect>")
            if i == 5:
                parts.append(f"<rect x='{x:.1f}' y='{mys(v):.1f}' width='34' height='{MB - mys(v):.1f}' rx='8' fill='url(#g-mh2)' pointer-events='none'/>"
                             f"<text x='{x + 17:.1f}' y='{mys(v) - 8:.1f}' text-anchor='middle' font-size='11' font-weight='500' fill='{INK}' font-family='Inter,system-ui,sans-serif'>{esc(fa(v))}</text>")
    for i, mm in enumerate(months):
        parts.append(f"<text x='{ML + gw * i + gw / 2:.1f}' y='300' text-anchor='middle' font-size='12' fill='{MUTED}' font-family='Inter,system-ui,sans-serif'>{MES_PT[mm.month - 1]}{' (até ' + dfmt(D1) + ')' if i == 5 else ''}</text>")
    parts.append("</svg>")
    legend = "".join(f"<span><span class='g-dot' style='background:{c};width:12px;height:12px;border-radius:4px'></span>{esc(n)}</span>" for n, c, _ in series)
    legend += f"<span><span style='display:inline-block;width:14px;height:14px;border-radius:4px;background:{HATCH}'></span>{MES_PT[M0.month - 1]} incompleto · até {dfmt(D1)}</span>"
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:28px;display:flex;flex-direction:column;gap:12px'><div class='g-h3'>Série mensal · {MES_PT[months[0].month - 1]} a {MES_PT[months[-1].month - 1]}</div>"
                f"<div class='g-legend'>{legend}</div>{''.join(parts)}<div class='g-cap'>Leads Únicos em Contato · Pipe e Transbordados na unidade escolhida nos Ajustes · Vendas = NOMINAL." + (f" Meses sem alex_leads_diario ({', '.join(m for m in MES_PT if m in orig)}) lidos pela jornada única (Contato, leitura foto)." if orig else "") + "</div></div>", unsafe_allow_html=True)

    # ---- semana a semana
    groups = [("Website", "web"), ("App do Filiado", "apf"), ("Leads Únicos", "leads"), ("Pipe Televendas", "enc"), ("Transbordados Franquia", "tr")]
    hdr1 = "<span></span><span></span><span></span><span></span>" + "".join(f"<span class='hd' style='grid-column:span 3;text-align:center;color:{INK}'>{esc(g)}</span>" for g, _ in groups)
    hdr2 = "".join(f"<span class='hd'>{h}</span>" for h in ("Semana", "Período", "Ação", "Peso")) + "".join("<span class='hd' style='text-align:right'>Meta</span><span class='hd' style='text-align:right'>Real</span><span class='hd' style='text-align:right'>%</span>" for _ in groups)
    rows = []
    for w in D.weeks:
        has = w["a"] <= D1
        cur = w["a"] <= D1 + dt.timedelta(days=1) <= w["b"] and w["b"] > D1
        fut = not has
        cells = []
        for _, m in groups:
            mt = D.meta_sum(m, w["a"], w["b"])
            mtx = f0(mt) if mt else "—"
            if not has:
                cells.append(f"<span class='cl' style='justify-content:flex-end;color:{MUTED2}'>{esc(mtx)}</span><span class='cl' style='justify-content:flex-end'>—</span><span class='cl' style='justify-content:flex-end'>—</span>")
                continue
            r = D.s(m, w["a"], w["b"])
            cells.append(f"<span class='cl' style='justify-content:flex-end;color:{MUTED2}'>{esc(mtx)}</span><span class='cl' style='justify-content:flex-end'>{esc(f0(r))}</span>"
                         f"<span class='cl' style='justify-content:flex-end'>{st_chip(r, mt) if (mt and r is not None) else '—'}</span>")
        tp = [f"{w['id']} · {w['per']}", "Semana em andamento" if cur else "Semana futura · sem dados" if fut else ("Pré-semana · meta proporcional" if w["id"] == "Pré" else "Semana fechada"), f"Ação: {w['acao']}", f"Peso {fp(w['dias'] / N, 1)}"]
        rows.append(f"<div style='display:contents' title=\"{tip(tp)}\"><span class='cl' style='font-weight:600;color:{MUTED2 if fut else INK}'>{esc(w['id'])}{' <span class=g-pill>atual</span>' if cur else ''}</span>"
                    f"<span class='cl' style='color:{MUTED2 if fut else INK}'>{esc(w['per'])}</span><span class='cl'>{esc(w['acao'])}</span><span class='cl'>{esc(fp(w['dias'] / N, 1))}</span>{''.join(cells)}</div>")
    st.markdown(f"<div class='g-wrap g-card' style='margin-top:20px'><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'><div class='g-h3'>Semana a semana · metas proporcionais</div>"
                f"<span class='g-sub'>% da semana contra a meta semanal (meta do mês × dias da semana ÷ {N}) · {D.node['name']}" + ("" if D.channel == "cdt" else " (leads sempre CDT)") + "</span></div>"
                f"<div class='g-scroll' style='margin-top:12px'><div class='g-wk' style='grid-template-columns:72px 92px 140px 60px repeat(15,max-content);column-gap:4px'>{hdr1}{hdr2}{''.join(rows)}</div></div></div>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------ barra superior e render
PER_OPTS = [("hoje", "Hoje"), ("ontem", "Ontem"), ("semana", "Esta semana"), ("semana_ant", "Semana passada"), ("mes", "Este mês"),
            ("mes_ant", "Mês passado"), ("d30", "Últimos 30 dias"), ("d90", "Últimos 90 dias"), ("custom", "Personalizado")]
PROJ_OPTS = [("leads", "Leads"), ("enc", "Pipe Televendas"), ("tr", "Transbordados Franquia"), ("vendas", "Vendas")]


def _sel(label, opts, key, default, **kw):
    """st.pills (single) com fallback para st.radio horizontal; devolve a chave interna."""
    labels = [l for _, l in opts]
    back = {l: k for k, l in opts}
    dflt = dict(opts)[default]
    try:
        v = st.pills(label, labels, selection_mode="single", default=dflt, key=key, **kw)
    except Exception:  # noqa: BLE001
        v = st.radio(label, labels, index=labels.index(dflt), horizontal=True, key=key + "_r")
    return back.get(v, default)


def render(df_raw, df_goals, df_fcst, df_cal, cquery, reference_date, perfil="analista"):
    _css(perfil)
    ld, ger, erros = load_fontes(cquery)
    hoje = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()
    if isinstance(reference_date, (pd.Timestamp, dt.datetime)):
        reference_date = reference_date.date()

    # ---- cabeçalho / navegação
    nav = "".join(f"<a href='#{a}'><b>{n}</b>{esc(t)}</a>" for n, t, a in (("01", "Meta do mês", "b1"), ("02", "Dia a dia", "b2"), ("03", "Canais", "b3"), ("04", "Leads e funil", "b4"), ("05", "Histórico", "b5")))
    st.markdown(f"<div class='g-wrap' style='display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap'>"
                f"<span style='font:600 28px/1 Inter;letter-spacing:-.05em'>metas</span><div class='g-nav'>{nav}</div></div>", unsafe_allow_html=True)

    # ---- controles
    p = _sel("Período", PER_OPTS, "ger_per", "mes")
    custom = None
    if p == "custom":
        ca, cb, _ = st.columns([1, 1, 3])
        a0 = ca.date_input("De", value=month_start(reference_date), min_value=dt.date(2025, 1, 1), max_value=reference_date, key="ger_ca")
        b0 = cb.date_input("Até", value=reference_date, min_value=dt.date(2025, 1, 1), max_value=reference_date, key="ger_cb")
        custom = (a0, b0)
    c2, c3, c4, c5, _ = st.columns([2.4, 1.5, 1.3, 1.6, 3.2], vertical_alignment="bottom")
    with c2:
        ch_names = [("    " * NODE[c[0]]["level"]) + c[1] for c in CH]
        ch_sel = st.selectbox("Canal", ch_names, index=0, key="ger_canal")
        channel = CH[ch_names.index(ch_sel)][0]
    with c3:
        with st.popover("⚙️ Ajustes", width="stretch"):
            cmp_ = _sel("Comparar com", [("mes", "Mês anterior"), ("ano", "Ano anterior")], "ger_cmp", "mes")
            ldef = _sel("Definição de Leads", [(k, v[0]) for k, v in LEADDEF.items()], "ger_def", "abr")
            st.caption(LEADDEF[ldef][1])
            dby = _sel("Datar por", [("evento", "Evento"), ("safra", "Safra do lead")], "ger_dateby", "evento")
            st.caption("Evento: cada etapa datada no dia em que aconteceu (foto). Safra: tudo datado pelo dia de entrada do lead (coorte).")
    with c4:
        with st.popover("❔ Legenda", width="stretch"):
            st.markdown(f"<div class='g-wrap' style='display:flex;flex-direction:column;gap:8px;font:400 13px/18px Inter'>"
                        f"<div>{chip('ok', '≥ 100%', False, None, 'ok')} meta batida</div><div>{chip('warn', '90–99%', False, None, 'warn')} atenção</div><div>{chip('bad', '< 90%', False, None, 'bad')} abaixo</div>"
                        f"<div>{chip('ok', '+0,0%')} vs período anterior inteiro</div><div>{chip('ok', '+0,0%', True)} vs mesmo trecho do período anterior</div>"
                        f"<div><span style='display:inline-block;width:40px;height:16px;border-radius:9999px;background:{HATCH};border:1px solid {LINE};vertical-align:middle'></span> incompleto, em maturação ou projeção</div>"
                        f"<div class='g-cap'>— sem meta ou sem base · novo = base zero · Contato = pessoa no HubSpot · Negócio = card do HubSpot · Venda = CTN (NOMINAL)</div></div>", unsafe_allow_html=True)
    D = Dados(df_raw, df_goals, df_fcst, df_cal, ld, ger, reference_date, hoje, channel, ldef, dby, cmp_)
    with c5:
        csv_slot = st.empty()

    # ---- avisos de fonte
    if erros:
        for k, v in erros.items():
            st.warning(f"⚠️ `{k}` indisponível — {v}")
    if ger is None or ger.empty:
        st.info("A tabela `alex_ger_dash_dia` ainda está vazia: funil, heatmap, vendas originadas e definições alternativas aparecem como —. "
                "Rode `gt7 run gerencial_dash --arg since=2026-05-01` no claude-toolkit e clique em ♻️ Recarregar dados.")

    # ---- blocos
    _bloco1(D, p, custom)
    pt = _sel("Acumulado contra a meta — métrica", PROJ_OPTS, "ger_proj", "vendas", label_visibility="collapsed")
    _bloco1_proj(D, pt)
    _bloco2(D)
    det_d = st.toggle("Mais colunas na tabela diária", key="ger_det_d", value=False)
    _bloco2_tabela(D, det_d)
    show_zero_head = st.session_state.get("ger_zero", False)
    _bloco3(D, show_zero_head)
    cc1, cc2, cc3 = st.columns(3)
    show_zero = cc1.toggle("Mostrar canais zerados", key="ger_zero", value=False)
    det_t = cc2.toggle("Mais colunas na tabela de canais", key="ger_det_t", value=False)
    only_groups = cc3.toggle("Recolher (só grupos)", key="ger_groups", value=False)
    csv_df = _bloco3_tabela(D, show_zero, det_t, only_groups)
    _bloco4(D)
    fm = _sel("Funil — taxa", [("prev", "% da etapa anterior"), ("top", "% do total que entrou")], "ger_fmode", "prev", label_visibility="collapsed")
    _bloco4_funil(D, fm, show_zero)
    _bloco5(D)

    # ---- CSV
    if csv_df is not None and not csv_df.empty:
        csv_slot.download_button("⬇️ Exportar CSV", csv_df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                                 file_name=f"metas-cdt-canais-{D.M0:%Y-%m}.csv", mime="text/csv", key="ger_csv", width="stretch")

    # ---- rodapé: fontes e frescor
    st.markdown(f"<div class='g-wrap g-note' style='margin-top:28px;padding:12px 0;border-top:1px solid {LINE}'>"
                f"<b>Fontes</b> · Vendas: RESUMO_VENDAS_DIARIAS (dados até {dfmt(D.D1)}; Venda = CPF × DT_FILIACAO) · Metas de vendas: alex_metas (parcial linear) · "
                f"Leads Únicos / Pipe Televendas / Transbordados (meta de outubro): alex_leads_diario (atualizada {D.ld_upd if D.ld_upd is not None else '—'}) · "
                f"Jornada por dia (funil, heatmap, vendas originadas, definições alternativas): alex_ger_dash_dia ← alex_funil_journey (atualizada {D.ger_upd if D.ger_upd is not None else '—'}) · "
                f"Projeção de vendas: FORECAST_VENDAS_CANAL (Prophet, balanced) · Leads: mediana por dia da semana (28 d). "
                f"Metas de leads de outubro/26: 300.000 Leads Únicos · 145.000 transbordados (e-mail \"Metas de outubro\"). {VERSAO}</div>", unsafe_allow_html=True)
