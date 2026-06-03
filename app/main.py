from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from report import build_pdf_report
from tse_client import (
    TSEClientError,
    list_available_years,
    list_states,
    list_turns,
    load_tse_votes,
)


st.set_page_config(
    page_title="Dados de Eleicoes",
    page_icon=":bar_chart:",
    layout="wide",
)

COLOR_SEQUENCE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#f97316"]
FILTER_CONTEXT_KEY = "filter_context"
SELECTED_CITIES_KEY = "selected_cities"
SELECTED_CANDIDATES_KEY = "selected_candidates"


@st.cache_data(show_spinner=False)
def cached_list_states(year: int) -> list[str]:
    return list_states(year)


@st.cache_data(show_spinner=False)
def cached_list_turns(year: int, state: str) -> list[int]:
    return list_turns(year, state)


@st.cache_data(show_spinner=False)
def cached_load_tse_data(year: int, state: str, turn: int) -> tuple[pd.DataFrame, dict[str, str]]:
    data, resource = load_tse_votes(year, state, turn)
    return data, {
        "name": resource.name,
        "url": resource.url,
        "dataset_url": resource.dataset_url,
    }


def main() -> None:
    apply_theme()
    st.title("Dados de Eleicoes")

    with st.sidebar:
        st.header("Filtros")
        years = list_available_years()
        year = st.selectbox("Ano da eleicao", years, index=years.index(2022))

    try:
        states = cached_list_states(year)
    except TSEClientError as error:
        st.error(str(error))
        st.stop()

    default_state = states[0]

    with st.sidebar:
        state = st.selectbox("Estado", states, index=states.index(default_state))

    try:
        turns = cached_list_turns(year, state)
    except TSEClientError as error:
        st.error(str(error))
        st.stop()

    with st.sidebar:
        turn = st.selectbox(
            "Turno",
            turns,
            format_func=lambda value: f"{value} turno",
        )

    try:
        with st.spinner("Consultando e processando boletins oficiais do TSE..."):
            data, source = cached_load_tse_data(year, state, turn)
    except TSEClientError as error:
        st.error(str(error))
        st.stop()

    with st.sidebar:
        position_options = sorted(data["cargo"].unique())
        default_position = _default_position(position_options)
        selected_position = st.selectbox(
            "Cargo",
            position_options,
            index=position_options.index(default_position),
        )

    state_data = data[data["cargo"] == selected_position]
    candidate_options = (
        state_data.groupby("deputado", as_index=False)["votos"]
        .sum()
        .sort_values("votos", ascending=False)
        ["deputado"]
        .tolist()
    )
    filter_context = (year, state, turn, selected_position)
    _sync_filter_state(filter_context, state_data, candidate_options)

    with st.sidebar:
        city_options = sorted(state_data["cidade"].unique())
        _prune_session_selection(SELECTED_CITIES_KEY, city_options)
        selected_cities = st.multiselect(
            "Cidades",
            options=city_options,
            key=SELECTED_CITIES_KEY,
            placeholder="Todas as cidades",
        )

    filtered_data = state_data
    if selected_cities:
        filtered_data = filtered_data[filtered_data["cidade"].isin(selected_cities)]

    with st.sidebar:
        _prune_session_selection(SELECTED_CANDIDATES_KEY, candidate_options, max_items=5)
        selected_candidates = st.multiselect(
            "Candidatos para comparar",
            options=candidate_options,
            key=SELECTED_CANDIDATES_KEY,
            max_selections=5,
            placeholder="Selecione ate 5 candidatos",
        )

    if not selected_candidates:
        st.info("Selecione pelo menos um candidato para gerar os graficos.")
        st.stop()

    comparison_data = filtered_data[filtered_data["deputado"].isin(selected_candidates)]
    total_by_candidate = _build_selected_candidate_totals(
        state_data,
        comparison_data,
        selected_candidates,
    )
    city_candidate_totals = _build_city_candidate_totals(
        filtered_data,
        selected_cities,
        selected_candidates,
    )

    render_source(source)
    render_summary(comparison_data, year, state, turn, selected_cities, selected_candidates)
    render_pdf_export(
        year=year,
        state=state,
        turn=turn,
        position=selected_position,
        selected_cities=selected_cities,
        selected_candidates=selected_candidates,
        total_by_candidate=total_by_candidate,
        city_candidate_totals=city_candidate_totals,
        source=source,
    )
    render_total_votes_chart(total_by_candidate, year, state, turn)
    render_city_chart(city_candidate_totals, selected_cities)
    render_data_table(comparison_data)


def render_source(source: dict[str, str]) -> None:
    st.caption(
        f"Fonte oficial: Portal de Dados Abertos do TSE - "
        f"Arquivo: [{source['name']}]({source['url']})"
    )


def render_summary(
    data: pd.DataFrame,
    year: int,
    state: str,
    turn: int,
    selected_cities: list[str],
    selected_candidates: list[str],
) -> None:
    scope = f"{len(selected_cities)} cidade(s)" if selected_cities else "todas as cidades"
    st.caption(f"{year} - {state} - {turn} turno - {scope} - {len(selected_candidates)} candidato(s)")

    total_votes = int(data["votos"].sum())
    cities_count = data["cidade"].nunique()
    candidates_count = data["deputado"].nunique()
    leader = (
        data.groupby("deputado")["votos"].sum().sort_values(ascending=False).index[0]
        if not data.empty
        else "-"
    )
    leader_display = _shorten(leader)

    col_total, col_cities, col_deputies, col_winner = st.columns(4)
    col_total.metric("Votos filtrados", f"{total_votes:,}".replace(",", "."))
    col_cities.metric("Cidades", cities_count)
    col_deputies.metric("Candidatos", candidates_count)
    col_winner.metric("Maior votacao", leader_display)


def render_pdf_export(
    *,
    year: int,
    state: str,
    turn: int,
    position: str,
    selected_cities: list[str],
    selected_candidates: list[str],
    total_by_candidate: pd.DataFrame,
    city_candidate_totals: pd.DataFrame,
    source: dict[str, str],
) -> None:
    pdf_bytes = build_pdf_report(
        year=year,
        state=state,
        turn=turn,
        position=position,
        selected_cities=selected_cities,
        selected_candidates=selected_candidates,
        total_by_candidate=total_by_candidate,
        city_candidate_totals=city_candidate_totals,
        source=source,
    )
    file_name = f"relatorio_votos_{year}_{state}_{turn}t.pdf".lower()
    st.download_button(
        "Exportar PDF",
        data=pdf_bytes,
        file_name=file_name,
        mime="application/pdf",
    )


def render_total_votes_chart(total_by_candidate: pd.DataFrame, year: int, state: str, turn: int) -> None:
    st.subheader("Comparativo de votos por candidato")
    chart_data = total_by_candidate.copy()
    chart_data["legenda"] = chart_data.apply(_format_candidate_label, axis=1)
    chart_data["votos_formatados"] = chart_data["votos"].map(_format_integer)

    fig = px.bar(
        chart_data,
        x="legenda",
        y="votos",
        color="deputado",
        color_discrete_sequence=COLOR_SEQUENCE,
        custom_data=["votos_formatados", "deputado"],
        labels={"legenda": "Candidato", "votos": "Quantidade de votos"},
        text="votos_formatados",
        title=f"Votos totais em {state} - {year} - {turn} turno",
    )
    fig.update_layout(
        showlegend=False,
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
        xaxis_title=None,
        yaxis_title="Votos",
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Total: %{customdata[0]} votos<extra></extra>",
    )
    event = st.plotly_chart(
        fig,
        width="stretch",
        key="total_votes_chart",
        on_select="rerun",
        selection_mode="points",
    )
    _render_selected_bar_total(event)


def render_city_chart(
    city_data: pd.DataFrame,
    selected_cities: list[str],
) -> None:
    st.subheader("Votos por cidade")
    chart_data = city_data.copy()
    chart_data["votos_formatados"] = chart_data["votos"].map(_format_integer)

    fig = px.bar(
        chart_data,
        x="cidade",
        y="votos",
        color="deputado",
        barmode="group",
        color_discrete_sequence=COLOR_SEQUENCE,
        custom_data=["votos_formatados", "deputado"],
        labels={"cidade": "Cidade", "votos": "Quantidade de votos", "deputado": "Candidato"},
        text="votos_formatados",
        title="Distribuicao de votos nas cidades selecionadas"
        if selected_cities
        else "Distribuicao de votos por cidade",
    )
    fig.update_layout(
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
        xaxis_title=None,
        yaxis_title="Votos",
        legend_title_text="Candidato",
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{fullData.name}</b><br>Cidade: %{x}<br>Total: %{customdata[0]} votos<extra></extra>",
    )
    event = st.plotly_chart(
        fig,
        width="stretch",
        key="city_votes_chart",
        on_select="rerun",
        selection_mode="points",
    )
    _render_selected_bar_total(event)


def render_data_table(data: pd.DataFrame) -> None:
    st.subheader("Dados filtrados")
    table_data = (
        data.groupby(["ano", "turno", "estado", "cidade", "cargo", "deputado", "partido"], as_index=False)[
            "votos"
        ]
        .sum()
        .sort_values(["cidade", "votos"], ascending=[True, False])
        .rename(columns={"deputado": "candidato"})
    )
    st.dataframe(table_data, width="stretch", hide_index=True)


def _format_candidate_label(row: pd.Series) -> str:
    if row["partido"]:
        return f"{row['deputado']} ({row['partido']})"
    return row["deputado"]


def _sync_filter_state(
    filter_context: tuple[int, str, int, str],
    state_data: pd.DataFrame,
    candidate_options: list[str],
) -> None:
    if st.session_state.get(FILTER_CONTEXT_KEY) == filter_context:
        return

    st.session_state[FILTER_CONTEXT_KEY] = filter_context
    st.session_state[SELECTED_CITIES_KEY] = []
    st.session_state[SELECTED_CANDIDATES_KEY] = _top_candidates(state_data, candidate_options)


def _top_candidates(state_data: pd.DataFrame, candidate_options: list[str]) -> list[str]:
    totals = (
        state_data.groupby("deputado", as_index=False)["votos"]
        .sum()
        .sort_values("votos", ascending=False)
    )
    top_candidates = totals["deputado"].head(5).tolist()
    return [candidate for candidate in top_candidates if candidate in candidate_options]


def _prune_session_selection(key: str, options: list[str], max_items: int | None = None) -> None:
    current_selection = st.session_state.get(key, [])
    if not isinstance(current_selection, list):
        current_selection = []

    option_set = set(options)
    pruned_selection = [item for item in current_selection if item in option_set]
    if max_items is not None:
        pruned_selection = pruned_selection[:max_items]

    st.session_state[key] = pruned_selection


def _build_selected_candidate_totals(
    state_data: pd.DataFrame,
    comparison_data: pd.DataFrame,
    selected_candidates: list[str],
) -> pd.DataFrame:
    selected_frame = pd.DataFrame({"deputado": selected_candidates})
    candidate_parties = (
        state_data[state_data["deputado"].isin(selected_candidates)]
        .groupby(["deputado", "partido"], as_index=False)["votos"]
        .sum()
        .sort_values(["deputado", "votos"], ascending=[True, False])
        .drop_duplicates("deputado")[["deputado", "partido"]]
    )
    selected_totals = comparison_data.groupby("deputado", as_index=False)["votos"].sum()

    return (
        selected_frame.merge(candidate_parties, on="deputado", how="left")
        .merge(selected_totals, on="deputado", how="left")
        .fillna({"partido": "", "votos": 0})
        .astype({"votos": int})
    )


def _build_city_candidate_totals(
    filtered_data: pd.DataFrame,
    selected_cities: list[str],
    selected_candidates: list[str],
) -> pd.DataFrame:
    cities = selected_cities or sorted(filtered_data["cidade"].unique())
    grid = pd.MultiIndex.from_product(
        [cities, selected_candidates],
        names=["cidade", "deputado"],
    ).to_frame(index=False)

    city_totals = (
        filtered_data[filtered_data["deputado"].isin(selected_candidates)]
        .groupby(["cidade", "deputado"], as_index=False)["votos"]
        .sum()
    )

    return (
        grid.merge(city_totals, on=["cidade", "deputado"], how="left")
        .fillna({"votos": 0})
        .astype({"votos": int})
        .sort_values(["cidade", "deputado"])
    )


def _render_selected_bar_total(event: object) -> None:
    points = _get_selected_points(event)
    if not points:
        return

    point = points[0]
    city_or_label = _get_point_value(point, "x")
    votes = _get_point_value(point, "y")
    customdata = _get_point_value(point, "customdata") or []
    formatted_votes = customdata[0] if len(customdata) >= 1 else _format_integer(votes)
    candidate = customdata[1] if len(customdata) >= 2 else city_or_label
    label = (
        f"{candidate} - {city_or_label}"
        if candidate and str(candidate) not in str(city_or_label)
        else str(city_or_label)
    )

    st.info(f"{label}: {formatted_votes} votos")


def _get_selected_points(event: object) -> list[object]:
    selection = _get_point_value(event, "selection")
    if not selection:
        return []

    points = _get_point_value(selection, "points")
    return points or []


def _get_point_value(source: object, key: str) -> object:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _shorten(value: str, max_length: int = 28) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."


def _format_integer(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _default_position(position_options: list[str]) -> str:
    for preferred in ("DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"):
        if preferred in position_options:
            return preferred

    for option in position_options:
        if "DEPUTADO" in option:
            return option

    return position_options[0]


def apply_theme() -> None:
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 2rem;
            }

            [data-testid="stMetric"] {
                border: 1px solid #d9e2ec;
                border-radius: 8px;
                padding: 14px 16px;
                background: #ffffff;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.45rem;
            }

            .stPlotlyChart {
                border: 1px solid #d9e2ec;
                border-radius: 8px;
                padding: 10px;
                background: #ffffff;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
