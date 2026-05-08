import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import json
import urllib.request
import ssl

# 1. Configure the page 
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")

# --- AUTHENTICATION SECTION ---
def check_password():
    """Returns `True` if the user has the correct password."""
    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 Dashboard Login")
    password = st.text_input("Please enter the password:", type="password")

    if password:
        if password == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun() 
        else:
            st.error("😕 Password incorrect. Please try again.")
            
    return False

if not check_password():
    st.stop()

# --- MAIN DASHBOARD SECTION ---
st.title("📊 Vendas Dashboard")

try:
    conn = st.connection("mysql", type="sql")
except Exception as e:
    st.error(f"Failed to connect to the database: {e}")
    st.stop()

# --- MAP HELPER FUNCTION ---
@st.cache_data(ttl=86400) # Cache map file for 24 hours
def get_brazil_geojson():
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url_geo = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
        with urllib.request.urlopen(url_geo, context=ctx) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return None

brazil_geo = get_brazil_geojson()

# --- 1. DATA LOAD FUNCTION (Reads from the new, fast table) ---
@st.cache_data(ttl=43200) 
def load_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    
    # Notice there is no GROUP BY or COUNT() here anymore. 
    # We are just downloading the pre-calculated numbers!
    query = f"""
    SELECT 
        data_venda, 
        uf, 
        tipo_venda, 
        Vendas
    FROM RESUMO_VENDAS_DIARIAS 
    WHERE data_venda >= '{start_of_last_year}'
    """
    
    df = conn.query(query)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    return df

df = load_data()

# --- 2. TIME LOGIC ---
reference_date = datetime.date.today() - datetime.timedelta(days=1)
ref_datetime = pd.to_datetime(reference_date)

this_week_start = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D')
this_month_start = ref_datetime.replace(day=1)
this_year_start = ref_datetime.replace(month=1, day=1)

def filter_by_date(dataframe, start_date, end_date):
    mask = (dataframe['data_venda'] >= start_date) & (dataframe['data_venda'] <= end_date)
    return dataframe.loc[mask]

def format_br(num):
    return f"{int(num):,}".replace(",", ".")

# --- UI: TABS FOR ORGANIZATION ---
tab1, tab2, tab3 = st.tabs(["📈 Desempenho de Vendas (KPIs)", "🗺️ Mapa Regional (UF)", "🛒 Tipo de Venda"])

with tab1:
    st.header("Visão de Vendas")
    
    view_option = st.radio("Selecione o período:", ["Semana Atual", "Mês Atual", "Ano Atual"], horizontal=True)
    
    # --- DATE LOGIC: PARTIAL AND FULL PERIODS ---
    days_elapsed = (ref_datetime - current_start).days if 'current_start' in locals() else 0 # Fallback, calculated below
    
    if view_option == "Semana Atual":
        current_start = this_week_start
        days_elapsed = (ref_datetime - current_start).days
        
        prev_start = current_start - pd.DateOffset(weeks=1)
        prev_full_end = current_start - pd.DateOffset(days=1)
        prev_partial_end = prev_start + pd.DateOffset(days=days_elapsed)
        
        last_year_start = current_start - pd.DateOffset(weeks=52)
        last_year_full_end = last_year_start + pd.DateOffset(days=6)
        last_year_partial_end = last_year_start + pd.DateOffset(days=days_elapsed)
        
    elif view_option == "Mês Atual":
        current_start = this_month_start
        
        prev_start = current_start - pd.DateOffset(months=1)
        prev_full_end = current_start - pd.DateOffset(days=1)
        prev_partial_end = min(ref_datetime - pd.DateOffset(months=1), prev_full_end)
        
        last_year_start = current_start - pd.DateOffset(years=1)
        last_year_full_end = last_year_start + pd.DateOffset(months=1) - pd.DateOffset(days=1)
        last_year_partial_end = min(ref_datetime - pd.DateOffset(years=1), last_year_full_end)
        
    else: # Ano Atual
        current_start = this_year_start
        
        prev_start = current_start - pd.DateOffset(years=1)
        prev_full_end = current_start - pd.DateOffset(days=1) 
        prev_partial_end = min(ref_datetime - pd.DateOffset(years=1), prev_full_end)
        
        last_year_start = prev_start 
        last_year_full_end = prev_full_end
        last_year_partial_end = prev_partial_end

    def fmt_date(d):
        return d.strftime('%d/%m/%Y')

    # Create descriptive labels for tooltips
    atual_label = f"{fmt_date(current_start)} a {fmt_date(ref_datetime)}"
    prev_partial_label = f"{fmt_date(prev_start)} a {fmt_date(prev_partial_end)}"
    prev_full_label = f"{fmt_date(prev_start)} a {fmt_date(prev_full_end)}"
    last_partial_label = f"{fmt_date(last_year_start)} a {fmt_date(last_year_partial_end)}"
    last_full_label = f"{fmt_date(last_year_start)} a {fmt_date(last_year_full_end)}"

    # --- 1. TOTAL SALES CALCULATIONS ---
    df_current = filter_by_date(df, current_start, ref_datetime)
    df_prev_partial = filter_by_date(df, prev_start, prev_partial_end)
    df_prev_full = filter_by_date(df, prev_start, prev_full_end)
    df_last_partial = filter_by_date(df, last_year_start, last_year_partial_end)
    df_last_full = filter_by_date(df, last_year_start, last_year_full_end)
    
    sales_current = df_current['Vendas'].sum() if not df_current.empty else 0
    sales_prev_partial = df_prev_partial['Vendas'].sum() if not df_prev_partial.empty else 0
    sales_prev_full = df_prev_full['Vendas'].sum() if not df_prev_full.empty else 0
    sales_last_partial = df_last_partial['Vendas'].sum() if not df_last_partial.empty else 0
    sales_last_full = df_last_full['Vendas'].sum() if not df_last_full.empty else 0
    
    # Delta compares apples-to-apples (Current vs Partial)
    delta_prev = f"{((sales_current - sales_prev_partial) / sales_prev_partial * 100):.1f}%" if sales_prev_partial > 0 else "N/A"
    delta_last_year = f"{((sales_current - sales_last_partial) / sales_last_partial * 100):.1f}%" if sales_last_partial > 0 else "N/A"

    # --- RENDER KPI METRICS ---
    st.markdown("##### 📅 Datas de Referência")
    st.caption(f"**Atual:** {atual_label}")
    st.divider()

    st.markdown("###### 🌐 Vendas Totais")
    col1, col2, col3 = st.columns(3)
    col1.metric(f"Total ({view_option})", format_br(sales_current), help=atual_label)
    
    # We combine the partial and full values into one string: "Partial | Full"
    col2.metric("Anterior (Parcial | Total)", f"{format_br(sales_prev_partial)} | {format_br(sales_prev_full)}", delta_prev, help=f"Parcial: {prev_partial_label} \n Total: {prev_full_label}")
    
    if view_option != "Ano Atual":
        col3.metric("Ano Passado (Parcial | Total)", f"{format_br(sales_last_partial)} | {format_br(sales_last_full)}", delta_last_year, help=f"Parcial: {last_partial_label} \n Total: {last_full_label}")

    st.write("") 
    st.divider()

    # --- 2. SPECIFIC CHANNELS CALCULATIONS ---
    st.markdown("###### 📱 Canais Específicos")
    opcoes_canais = ['Website', 'App do Filiado', 'Televendas']
    canais_selecionados = st.multiselect("Filtre os canais desejados:", options=opcoes_canais, default=opcoes_canais)
    
    canais_alvo = [c.lower() for c in canais_selecionados]
    
    def get_canais_sales(df_period):
        if df_period.empty or 'tipo_venda' not in df_period.columns or not canais_alvo:
            return 0
        mask = df_period['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)
        return df_period.loc[mask, 'Vendas'].sum()

    canais_current = get_canais_sales(df_current)
    canais_prev_partial = get_canais_sales(df_prev_partial)
    canais_prev_full = get_canais_sales(df_prev_full)
    canais_last_partial = get_canais_sales(df_last_partial)
    canais_last_full = get_canais_sales(df_last_full)

    delta_canais_prev = f"{((canais_current - canais_prev_partial) / canais_prev_partial * 100):.1f}%" if canais_prev_partial > 0 else "N/A"
    delta_canais_last_year = f"{((canais_current - canais_last_partial) / canais_last_partial * 100):.1f}%" if canais_last_partial > 0 else "N/A"

    col4, col5, col6 = st.columns(3)
    col4.metric(f"Canais Selecionados", format_br(canais_current), help=atual_label)
    col5.metric("Anterior (Parcial | Total)", f"{format_br(canais_prev_partial)} | {format_br(canais_prev_full)}", delta_canais_prev, help=f"Parcial: {prev_partial_label} \n Total: {prev_full_label}")
    if view_option != "Ano Atual":
        col6.metric("Ano Passado (Parcial | Total)", f"{format_br(canais_last_partial)} | {format_br(canais_last_full)}", delta_canais_last_year, help=f"Parcial: {last_partial_label} \n Total: {last_full_label}")

    st.divider()
    
    # --- COMPARISON CHART ---
    st.subheader("Comparativo Gráfico")
    
    chart_view = st.radio("Selecione os dados para o gráfico:", ["Vendas Totais", "Canais Selecionados"], horizontal=True)
    
    if chart_view == "Vendas Totais":
        v_curr, v_pp, v_pf, v_lp, v_lf = sales_current, sales_prev_partial, sales_prev_full, sales_last_partial, sales_last_full
    else:
        v_curr, v_pp, v_pf, v_lp, v_lf = canais_current, canais_prev_partial, canais_prev_full, canais_last_partial, canais_last_full

    # Expand the chart to show all 5 bars
    if view_option != "Ano Atual":
        periodos = ["Atual", "Anterior (Parcial)", "Anterior (Total)", "Ano Passado (Parcial)", "Ano Passado (Total)"]
        vendas_plot = [v_curr, v_pp, v_pf, v_lp, v_lf]
        intervalos = [atual_label, prev_partial_label, prev_full_label, last_partial_label, last_full_label]
    else:
        # If it's Ano Atual, Anterior and Ano Passado are the exact same thing
        periodos = ["Atual", "Ano Passado (Parcial)", "Ano Passado (Total)"]
        vendas_plot = [v_curr, v_pp, v_pf]
        intervalos = [atual_label, prev_partial_label, prev_full_label]

    chart_data = pd.DataFrame({
        "Período": periodos,
        "Vendas": vendas_plot,
        "Intervalo de Datas": intervalos
    })
    
    chart_data["Vendas_Formatadas"] = chart_data["Vendas"].apply(format_br)
    
    fig = px.bar(chart_data, x="Período", y="Vendas", color="Período", text="Vendas_Formatadas",
                 hover_data={"Intervalo de Datas": True, "Período": False, "Vendas": False, "Vendas_Formatadas": False},
                 color_discrete_sequence=px.colors.qualitative.Pastel)
    
    fig.update_traces(textposition='auto', hovertemplate="<b>%{x}</b><br>Vendas: %{text}<br>Período: %{customdata[0]}<extra></extra>")
    st.plotly_chart(fig, width='stretch')

with tab2:
    st.header("Análise Geográfica (UF)")
    
    col1, col2 = st.columns(2)
    start_map = col1.date_input("Data de Início", value=this_month_start.date(), key="map_start")
    end_map = col2.date_input("Data de Fim", value=reference_date, key="map_end")
    
    df_map = filter_by_date(df, pd.to_datetime(start_map), pd.to_datetime(end_map))
    
    if not df_map.empty:
        df_map['uf'] = df_map['uf'].str.upper()
        uf_sales = df_map.groupby('uf')['Vendas'].sum().reset_index()
        
        if brazil_geo:
            fig_map = px.choropleth(
                uf_sales, geojson=brazil_geo, locations='uf', featureidkey='properties.sigla',
                color='Vendas', color_continuous_scale="Blues",
                title=f"Vendas por Estado ({start_map.strftime('%d/%m/%Y')} - {end_map.strftime('%d/%m/%Y')})"
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            fig_map.update_traces(customdata=[format_br(v) for v in uf_sales['Vendas']], hovertemplate="<b>%{location}</b><br>Vendas: %{customdata}<extra></extra>")
            st.plotly_chart(fig_map, width='stretch')
        else:
            st.warning("Não foi possível carregar o mapa do Brasil. Exibindo apenas o gráfico de barras.")
        
        df_sorted = uf_sales.sort_values(by='Vendas', ascending=True).copy()
        df_sorted["Vendas_Formatadas"] = df_sorted["Vendas"].apply(format_br)
        
        fig_bar_uf = px.bar(df_sorted, x='Vendas', y='uf', orientation='h', title="Ranking por UF", text="Vendas_Formatadas")
        fig_bar_uf.update_traces(textposition='auto', hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
        st.plotly_chart(fig_bar_uf, width='stretch')
    else:
        st.info("Nenhuma venda encontrada para o período selecionado.")

with tab3:
    st.header("Composição por Tipo de Venda")
    
    col1, col2 = st.columns(2)
    start_tipo = col1.date_input("Data de Início", value=this_month_start.date(), key="tipo_start")
    end_tipo = col2.date_input("Data de Fim", value=reference_date, key="tipo_end")
    
    df_tipo = filter_by_date(df, pd.to_datetime(start_tipo), pd.to_datetime(end_tipo))
    
    if not df_tipo.empty:
        df_tipo['tipo_venda_clean'] = df_tipo['tipo_venda'].fillna("Não Informado").astype(str).str.title()
        tipo_sales = df_tipo.groupby('tipo_venda_clean')['Vendas'].sum().reset_index()
        tipo_sales = tipo_sales.sort_values(by='Vendas', ascending=False).copy()
        tipo_sales["Vendas_Formatadas"] = tipo_sales["Vendas"].apply(format_br)
        
        fig_pie = px.pie(tipo_sales, names='tipo_venda_clean', values='Vendas', 
                         title=f"Distribuição de Vendas ({start_tipo.strftime('%d/%m/%Y')} - {end_tipo.strftime('%d/%m/%Y')})",
                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Vendas: %{value}<extra></extra>")
        
        fig_bar_tipo = px.bar(tipo_sales.sort_values(by='Vendas', ascending=True), 
                              x='Vendas', y='tipo_venda_clean', orientation='h', 
                              title="Ranking por Tipo de Venda", text="Vendas_Formatadas", color_discrete_sequence=['#92C5DE'])
        fig_bar_tipo.update_traces(textposition='auto', hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
        
        col_chart1, col_chart2 = st.columns([1, 1])
        with col_chart1:
            st.plotly_chart(fig_pie, width='stretch')
        with col_chart2:
            st.plotly_chart(fig_bar_tipo, width='stretch')
            
    else:
        st.info("Nenhuma venda encontrada para o período selecionado.")