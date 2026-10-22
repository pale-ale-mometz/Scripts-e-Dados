"""Tema visual Cartão de Todos para os gráficos Plotly do Vendas Dashboard.

Dois templates registrados em plotly.io.templates (escolha do Álex em 26/08, folheto de estilos):
  cdt_a  — "Economist-like": título à esquerda com aba verde + linha fina (desenhados em HTML por `header()`),
           eixo Y à direita, só grade horizontal, linha do eixo X escura, legenda no topo à esquerda,
           rótulos em k sobre as colunas. Usar em séries mensais (colunas) e barras horizontais.
  cdt_b  — "Datawrapper-like": grade pontilhada discreta, sem legenda — cada linha recebe o nome na
           ponta direita (`rotular_pontas()`), título maior com subtítulo cinza. Usar em gráficos de linha (taxas).

Uso:
    import cdt_theme
    cdt_theme.register()                                   # uma vez, no topo do app
    st.markdown(cdt_theme.header("Título", "subtítulo", "A"), unsafe_allow_html=True)
    fig.update_layout(template="cdt_a")                    # ou "cdt_b"
Todos os gráficos de mesma natureza devem usar o mesmo estilo (regra da casa).
"""
import plotly.graph_objects as go
import plotly.io as pio

GREENS = ['#166534', '#2e8a4f', '#57a86f', '#8cc79e', '#c8e3cf']
AMBER = '#b45309'
GREY = '#94a3b8'
INK = '#0f172a'
MUTED = '#64748b'
# ordem das séries: verde escuro, verde médio, âmbar (destaque), verde claro, cinza, tinta
COLORWAY = ['#166534', '#57a86f', '#b45309', '#8cc79e', '#94a3b8', '#0f172a', '#c8e3cf']
FONT = "Inter, 'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif"


def register() -> None:
    a = go.layout.Template()
    a.layout = go.Layout(
        font=dict(family=FONT, size=12.5, color=INK),
        paper_bgcolor='#ffffff', plot_bgcolor='#ffffff', colorway=COLORWAY,
        xaxis=dict(showgrid=False, showline=True, linecolor=INK, linewidth=1.2, ticks='outside',
                   tickcolor=INK, ticklen=4, zeroline=False, title_text='', tickfont=dict(size=11.5)),
        yaxis=dict(showgrid=True, gridcolor='#d9dde3', gridwidth=1, showline=False, zeroline=False,
                   side='right', ticks='', tickfont=dict(size=11, color='#334155'), title_text=''),
        legend=dict(orientation='h', x=0, xanchor='left', y=1.02, yanchor='bottom',
                    font=dict(size=11.5), title_text=''),
        margin=dict(l=10, r=48, t=34, b=30), bargap=0.25, bargroupgap=0.06,
        hoverlabel=dict(font_family=FONT, font_size=12),
    )
    b = go.layout.Template()
    b.layout = go.Layout(
        font=dict(family=FONT, size=12.5, color='#1f2937'),
        paper_bgcolor='#ffffff', plot_bgcolor='#ffffff', colorway=COLORWAY,
        xaxis=dict(showgrid=False, showline=True, linecolor='#cbd5e1', ticks='', zeroline=False,
                   title_text='', tickfont=dict(size=11.5, color='#475569')),
        yaxis=dict(showgrid=True, gridcolor='#e5e7eb', griddash='dot', showline=False, zeroline=False,
                   ticks='', title_text='', tickfont=dict(size=11, color='#475569')),
        showlegend=False,
        margin=dict(l=45, r=120, t=16, b=30),
        hoverlabel=dict(font_family=FONT, font_size=12),
    )
    pio.templates['cdt_a'] = a
    pio.templates['cdt_b'] = b


def header(title: str, subtitle: str = '', style: str = 'A') -> str:
    """Cabeçalho HTML do gráfico (o título fica fora da figura para ter posição estável).
    A: aba verde + linha fina acima do título (assinatura do estilo). B: título maior, subtítulo cinza."""
    if style.upper() == 'A':
        return (f"<div style='margin:6px 0 2px;'>"
                f"<div style='height:5px;width:34px;background:{GREENS[0]};margin-bottom:-1px;'></div>"
                f"<div style='border-top:1px solid {INK};padding-top:6px;'>"
                f"<div style='font-size:15px;font-weight:800;color:{INK};line-height:1.2;'>{title}</div>"
                + (f"<div style='font-size:11.5px;color:{MUTED};margin-top:2px;'>{subtitle}</div>" if subtitle else "")
                + "</div></div>")
    return (f"<div style='margin:6px 0 0;'>"
            f"<div style='font-size:16px;font-weight:800;color:#111827;line-height:1.2;'>{title}</div>"
            + (f"<div style='font-size:11.5px;color:{MUTED};margin-top:2px;'>{subtitle}</div>" if subtitle else "")
            + "</div>")


def fonte(texto: str) -> str:
    """Rodapé de fonte (estilo A) — usar logo abaixo do gráfico."""
    return f"<div style='font-size:10.5px;color:{MUTED};margin:-2px 0 10px;'>Fonte: {texto}</div>"


def rotular_pontas(fig: go.Figure, xshift: int = 8) -> go.Figure:
    """Estilo B: escreve o nome de cada série na ponta direita da linha (substitui a legenda)."""
    for tr in fig.data:
        xs = getattr(tr, 'x', None)
        ys = getattr(tr, 'y', None)
        if xs is None or ys is None or len(xs) == 0 or len(ys) == 0:
            continue
        if all(v is None for v in ys):
            continue
        color = None
        try:
            color = tr.line.color or tr.marker.color
        except Exception:
            pass
        fig.add_annotation(x=tr.x[-1], y=tr.y[-1], text=tr.name, showarrow=False, xanchor='left',
                           xshift=xshift, font=dict(size=11.5, color=color or INK))
    fig.update_layout(showlegend=False)
    return fig


def fmt_k(v) -> str:
    """Rótulo curto para colunas: 35,7k · 123k · 842 (pt-BR)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v != v:  # NaN
        return ""
    if abs(v) >= 100000:
        return f"{v / 1000:.0f}k"
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}k".replace('.', ',')
    return f"{int(round(v)):,}".replace(',', '.')
