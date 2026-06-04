from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
PROJECTION_COLOR = "#f97316"
FILTER_CONTEXT_KEY = "filter_context"
LAST_APPLIED_QUERY_SIGNATURE_KEY = "last_applied_query_signature"
LAST_WRITTEN_QUERY_SIGNATURE_KEY = "last_written_query_signature"
SELECTED_CITIES_KEY = "selected_cities"
SELECTED_CANDIDATES_KEY = "selected_candidates"
PROJECTION_INPUT_KEY = "projection_input"
PROJECTION_PERCENT_KEY = "projection_percent"
PROJECTION_SCOPE_KEY = "projection_scope"
LAST_WRITTEN_PROJECTION_QUERY_KEY = "last_written_projection_query"
QUERY_YEAR_KEY = "ano"
QUERY_STATE_KEY = "estado"
QUERY_TURN_KEY = "turno"
QUERY_POSITION_KEY = "cargo"
QUERY_CITIES_KEY = "cidades"
QUERY_CANDIDATES_KEY = "candidatos"
QUERY_PROJECTION_KEY = "projecao"
QUERY_PROJECTION_SCOPE_KEY = "projecao_em"
PROJECTION_SCOPE_OPTIONS = {
    "Cidades e total": "ambos",
    "Somente cidades": "cidades",
    "Somente total": "total",
}


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
    query_filters = _read_query_filters()
    _sync_projection_state(query_filters["projection"], query_filters["projection_scope"])

    with st.sidebar:
        st.header("Filtros")
        years = list_available_years()
        default_year = _first_valid_option(query_filters["year"], years, 2022)
        year = st.selectbox("Ano da eleicao", years, index=years.index(default_year))

    try:
        states = cached_list_states(year)
    except TSEClientError as error:
        st.error(str(error))
        st.stop()

    default_state = _first_valid_option(query_filters["state"], states, states[0])

    with st.sidebar:
        state = st.selectbox("Estado", states, index=states.index(default_state))

    try:
        turns = cached_list_turns(year, state)
    except TSEClientError as error:
        st.error(str(error))
        st.stop()

    with st.sidebar:
        default_turn = _first_valid_option(query_filters["turn"], turns, turns[0])
        turn = st.selectbox(
            "Turno",
            turns,
            index=turns.index(default_turn),
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
        default_position = _first_valid_option(
            query_filters["position"],
            position_options,
            _default_position(position_options),
        )
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

    with st.sidebar:
        city_options = sorted(state_data["cidade"].unique())
        query_cities = _valid_options(query_filters["cities"], city_options)
        query_candidates = _valid_options(query_filters["candidates"], candidate_options, max_items=5)
        _sync_filter_state(
            filter_context,
            state_data,
            candidate_options,
            default_cities=query_cities,
            default_candidates=query_candidates,
            query_signature=_build_query_signature(
                year,
                state,
                turn,
                selected_position,
                query_cities,
                query_candidates,
            ),
        )
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
        projection_percent, projection_scope = render_projection_controls()

    total_projection_percent = projection_percent if _projects_total(projection_scope) else 0.0
    city_projection_percent = projection_percent if _projects_cities(projection_scope) else 0.0

    _update_filter_query_params(
        year=year,
        state=state,
        turn=turn,
        position=selected_position,
        selected_cities=selected_cities,
        selected_candidates=selected_candidates,
        projection_percent=projection_percent,
        projection_scope=projection_scope,
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
    projected_total_by_candidate = _build_projection_totals(
        total_by_candidate,
        total_projection_percent,
    )
    city_candidate_totals = _build_city_candidate_totals(
        filtered_data,
        selected_cities,
        selected_candidates,
    )
    projected_city_candidate_totals = _build_projection_totals(
        city_candidate_totals,
        city_projection_percent,
    )
    summary_projection_data = (
        projected_total_by_candidate
        if _projects_total(projection_scope)
        else _aggregate_projected_city_totals(projected_city_candidate_totals, total_by_candidate)
    )

    render_source(source)
    render_summary(
        comparison_data,
        year,
        state,
        turn,
        selected_cities,
        selected_candidates,
        summary_projection_data,
        projection_percent,
        projection_scope,
    )
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
    render_total_votes_chart(projected_total_by_candidate, year, state, turn, total_projection_percent)
    render_city_chart(projected_city_candidate_totals, selected_cities, city_projection_percent)
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
    projected_total_by_candidate: pd.DataFrame,
    projection_percent: float,
    projection_scope: str,
) -> None:
    scope = f"{len(selected_cities)} cidade(s)" if selected_cities else "todas as cidades"
    st.caption(f"{year} - {state} - {turn} turno - {scope} - {len(selected_candidates)} candidato(s)")

    total_votes = int(data["votos"].sum())
    projected_votes = int(projected_total_by_candidate["votos_projecao"].sum())
    projected_total = int(projected_total_by_candidate["votos_total"].sum())
    cities_count = data["cidade"].nunique()
    candidates_count = data["deputado"].nunique()
    leader = (
        data.groupby("deputado")["votos"].sum().sort_values(ascending=False).index[0]
        if not data.empty
        else "-"
    )
    leader_display = _shorten(leader)

    col_total, col_cities, col_deputies, col_winner = st.columns(4)
    if projection_percent > 0:
        col_total.metric(
            f"Votos filtrados + Projecao de {_format_percent(projection_percent)}",
            _format_integer(projected_total),
            delta=f"+{_format_integer(projected_votes)} projetados",
        )
    else:
        col_total.metric("Votos filtrados", _format_integer(total_votes))
    col_cities.metric("Cidades", cities_count)
    col_deputies.metric("Candidatos", candidates_count)
    col_winner.metric("Maior votacao", leader_display)
    if projection_percent > 0:
        st.caption(f"Base da projecao: {_projection_scope_label(projection_scope)}")
    render_projection_detail(projected_total_by_candidate, projection_percent)


def render_projection_controls() -> tuple[float, str]:
    st.divider()
    st.number_input(
        "Projecao (%)",
        min_value=0.0,
        max_value=1000.0,
        step=1.0,
        key=PROJECTION_INPUT_KEY,
    )
    selected_scope_label = st.selectbox(
        "Aplicar projecao em",
        options=list(PROJECTION_SCOPE_OPTIONS.keys()),
        index=_projection_scope_index(st.session_state.get(PROJECTION_SCOPE_KEY, "ambos")),
    )
    st.session_state[PROJECTION_SCOPE_KEY] = PROJECTION_SCOPE_OPTIONS[selected_scope_label]

    apply_button, clear_button = st.columns(2)
    apply_button.button("Aplicar projecao", width="stretch", on_click=_apply_projection)
    clear_button.button("Limpar", width="stretch", on_click=_clear_projection)

    projection_percent = _normalize_projection_percent(
        st.session_state.get(PROJECTION_PERCENT_KEY, 0.0)
    )
    if projection_percent > 0:
        st.caption(
            f"Projecao aplicada: {_format_percent(projection_percent)} "
            f"em {_projection_scope_label(st.session_state[PROJECTION_SCOPE_KEY]).lower()}"
        )

    return projection_percent, st.session_state[PROJECTION_SCOPE_KEY]


def _apply_projection() -> None:
    st.session_state[PROJECTION_PERCENT_KEY] = _normalize_projection_percent(
        st.session_state.get(PROJECTION_INPUT_KEY, 0.0)
    )


def _clear_projection() -> None:
    st.session_state[PROJECTION_PERCENT_KEY] = 0.0
    st.session_state[PROJECTION_INPUT_KEY] = 0.0


def render_projection_detail(projected_total_by_candidate: pd.DataFrame, projection_percent: float) -> None:
    if projection_percent <= 0:
        return

    detail = projected_total_by_candidate[
        ["deputado", "votos_reais", "votos_projecao", "votos_total"]
    ].rename(
        columns={
            "deputado": "candidato",
            "votos_reais": "votos reais",
            "votos_projecao": f"projecao {_format_percent(projection_percent)}",
            "votos_total": "total projetado",
        }
    ).copy()
    for column in ["votos reais", f"projecao {_format_percent(projection_percent)}", "total projetado"]:
        detail[column] = detail[column].map(_format_integer)

    st.dataframe(detail, width="stretch", hide_index=True)


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


def render_total_votes_chart(
    total_by_candidate: pd.DataFrame,
    year: int,
    state: str,
    turn: int,
    projection_percent: float,
) -> None:
    st.subheader("Comparativo de votos por candidato")
    chart_data = total_by_candidate.copy()
    chart_data["legenda"] = chart_data.apply(_format_candidate_label, axis=1)
    chart_data["votos_formatados"] = chart_data["votos"].map(_format_integer)

    if projection_percent > 0:
        fig = _build_projected_total_chart(chart_data, year, state, turn, projection_percent)
        event = st.plotly_chart(
            fig,
            width="stretch",
            key="total_votes_chart",
            on_select="rerun",
            selection_mode="points",
        )
        _render_selected_bar_total(event)
        return

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
    projection_percent: float,
) -> None:
    st.subheader("Votos por cidade")
    chart_data = city_data.copy()
    chart_data["votos_formatados"] = chart_data["votos"].map(_format_integer)

    if projection_percent > 0:
        fig = _build_projected_city_chart(chart_data, selected_cities, projection_percent)
        event = st.plotly_chart(
            fig,
            width="stretch",
            key="city_votes_chart",
            on_select="rerun",
            selection_mode="points",
        )
        _render_selected_bar_total(event)
        render_city_projection_detail(chart_data, projection_percent)
        return

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


def render_city_projection_detail(city_data: pd.DataFrame, projection_percent: float) -> None:
    detail = city_data[
        ["cidade", "deputado", "votos_reais", "votos_projecao", "votos_total"]
    ].rename(
        columns={
            "deputado": "candidato",
            "votos_reais": "votos reais",
            "votos_projecao": f"projecao {_format_percent(projection_percent)}",
            "votos_total": "total projetado",
        }
    ).copy()
    for column in ["votos reais", f"projecao {_format_percent(projection_percent)}", "total projetado"]:
        detail[column] = detail[column].map(_format_integer)

    st.dataframe(detail, width="stretch", hide_index=True)


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


def _build_projected_total_chart(
    chart_data: pd.DataFrame,
    year: int,
    state: str,
    turn: int,
    projection_percent: float,
) -> go.Figure:
    fig = go.Figure()
    projection_label = f"Projecao {_format_percent(projection_percent)}"

    for index, row in chart_data.reset_index(drop=True).iterrows():
        color = COLOR_SEQUENCE[index % len(COLOR_SEQUENCE)]
        customdata = [[
            _format_integer(row["votos_total"]),
            row["deputado"],
            _format_integer(row["votos_reais"]),
            _format_integer(row["votos_projecao"]),
        ]]
        fig.add_bar(
            x=[row["legenda"]],
            y=[row["votos_reais"]],
            name=row["deputado"],
            marker_color=color,
            text=[_format_integer(row["votos_reais"])],
            textposition="inside",
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "Reais: %{customdata[2]} votos<br>"
                f"{projection_label}: %{{customdata[3]}} votos<br>"
                "Total: %{customdata[0]} votos<extra></extra>"
            ),
        )

    projection_customdata = [
        [
            _format_integer(row["votos_total"]),
            row["deputado"],
            _format_integer(row["votos_reais"]),
            _format_integer(row["votos_projecao"]),
        ]
        for _, row in chart_data.iterrows()
    ]
    fig.add_bar(
        x=chart_data["legenda"],
        y=chart_data["votos_projecao"],
        name=projection_label,
        marker_color=PROJECTION_COLOR,
        text=chart_data["votos_projecao"].map(_format_integer),
        textposition="outside",
        customdata=projection_customdata,
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "Reais: %{customdata[2]} votos<br>"
            f"{projection_label}: %{{customdata[3]}} votos<br>"
            "Total: %{customdata[0]} votos<extra></extra>"
        ),
    )
    fig.update_layout(
        barmode="stack",
        title=f"Votos totais em {state} - {year} - {turn} turno",
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
        xaxis_title=None,
        yaxis_title="Votos",
        legend_title_text="Camada",
    )
    return fig


def _build_projected_city_chart(
    chart_data: pd.DataFrame,
    selected_cities: list[str],
    projection_percent: float,
) -> go.Figure:
    fig = go.Figure()
    projection_label = f"Projecao {_format_percent(projection_percent)}"
    candidates = chart_data["deputado"].drop_duplicates().tolist()

    for index, candidate in enumerate(candidates):
        candidate_data = chart_data[chart_data["deputado"] == candidate].copy()
        color = COLOR_SEQUENCE[index % len(COLOR_SEQUENCE)]
        customdata = [
            [
                _format_integer(row["votos_total"]),
                row["deputado"],
                _format_integer(row["votos_reais"]),
                _format_integer(row["votos_projecao"]),
            ]
            for _, row in candidate_data.iterrows()
        ]

        fig.add_bar(
            x=candidate_data["cidade"],
            y=candidate_data["votos_reais"],
            name=candidate,
            marker_color=color,
            offsetgroup=candidate,
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "Cidade: %{x}<br>"
                "Reais: %{customdata[2]} votos<br>"
                f"{projection_label}: %{{customdata[3]}} votos<br>"
                "Total: %{customdata[0]} votos<extra></extra>"
            ),
        )
        fig.add_bar(
            x=candidate_data["cidade"],
            y=candidate_data["votos_projecao"],
            name=projection_label,
            marker_color=PROJECTION_COLOR,
            text=candidate_data["votos_projecao"].map(_format_integer),
            textposition="outside",
            offsetgroup=candidate,
            legendgroup="projection",
            showlegend=index == 0,
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "Cidade: %{x}<br>"
                "Reais: %{customdata[2]} votos<br>"
                f"{projection_label}: %{{customdata[3]}} votos<br>"
                "Total: %{customdata[0]} votos<extra></extra>"
            ),
        )

    fig.update_layout(
        barmode="relative",
        title="Distribuicao de votos nas cidades selecionadas"
        if selected_cities
        else "Distribuicao de votos por cidade",
        margin={"l": 24, "r": 24, "t": 56, "b": 24},
        xaxis_title=None,
        yaxis_title="Votos",
        legend_title_text="Candidato",
    )
    return fig


def _format_candidate_label(row: pd.Series) -> str:
    if row["partido"]:
        return f"{row['deputado']} ({row['partido']})"
    return row["deputado"]


def _sync_filter_state(
    filter_context: tuple[int, str, int, str],
    state_data: pd.DataFrame,
    candidate_options: list[str],
    default_cities: list[str],
    default_candidates: list[str],
    query_signature: tuple[object, ...],
) -> None:
    context_changed = st.session_state.get(FILTER_CONTEXT_KEY) != filter_context
    external_query_changed = _external_query_changed(query_signature)

    if not context_changed and not external_query_changed:
        return

    if context_changed and not external_query_changed:
        default_cities = []
        default_candidates = []

    st.session_state[FILTER_CONTEXT_KEY] = filter_context
    st.session_state[LAST_APPLIED_QUERY_SIGNATURE_KEY] = query_signature
    st.session_state[SELECTED_CITIES_KEY] = default_cities
    st.session_state[SELECTED_CANDIDATES_KEY] = default_candidates or _top_candidates(
        state_data,
        candidate_options,
    )


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


def _read_query_filters() -> dict[str, object]:
    return {
        "year": _parse_int(st.query_params.get(QUERY_YEAR_KEY)),
        "state": st.query_params.get(QUERY_STATE_KEY),
        "turn": _parse_int(st.query_params.get(QUERY_TURN_KEY)),
        "position": st.query_params.get(QUERY_POSITION_KEY),
        "cities": st.query_params.get_all(QUERY_CITIES_KEY),
        "candidates": st.query_params.get_all(QUERY_CANDIDATES_KEY),
        "projection": _parse_float(st.query_params.get(QUERY_PROJECTION_KEY)),
        "projection_scope": _valid_projection_scope(st.query_params.get(QUERY_PROJECTION_SCOPE_KEY)),
    }


def _update_filter_query_params(
    *,
    year: int,
    state: str,
    turn: int,
    position: str,
    selected_cities: list[str],
    selected_candidates: list[str],
    projection_percent: float,
    projection_scope: str,
) -> None:
    expected_params = {
        QUERY_YEAR_KEY: str(year),
        QUERY_STATE_KEY: state,
        QUERY_TURN_KEY: str(turn),
        QUERY_POSITION_KEY: position,
        QUERY_CITIES_KEY: selected_cities,
        QUERY_CANDIDATES_KEY: selected_candidates,
        QUERY_PROJECTION_KEY: _format_query_float(projection_percent),
        QUERY_PROJECTION_SCOPE_KEY: _valid_projection_scope(projection_scope),
    }
    expected_signature = _build_query_signature(
        year,
        state,
        turn,
        position,
        selected_cities,
        selected_candidates,
    )

    st.session_state[LAST_WRITTEN_QUERY_SIGNATURE_KEY] = expected_signature
    st.session_state[LAST_WRITTEN_PROJECTION_QUERY_KEY] = (
        f"{_format_query_float(projection_percent)}:{_valid_projection_scope(projection_scope)}"
    )

    if _query_params_match(expected_params):
        st.session_state[LAST_APPLIED_QUERY_SIGNATURE_KEY] = expected_signature
        return

    st.query_params.update(expected_params)


def _query_params_match(expected_params: dict[str, str | list[str]]) -> bool:
    for key, expected_value in expected_params.items():
        current_value = st.query_params.get_all(key)
        expected_values = expected_value if isinstance(expected_value, list) else [expected_value]
        if current_value != [str(value) for value in expected_values]:
            return False

    return True


def _external_query_changed(query_signature: tuple[object, ...]) -> bool:
    return query_signature not in {
        st.session_state.get(LAST_APPLIED_QUERY_SIGNATURE_KEY),
        st.session_state.get(LAST_WRITTEN_QUERY_SIGNATURE_KEY),
    }


def _build_query_signature(
    year: int,
    state: str,
    turn: int,
    position: str,
    selected_cities: list[str],
    selected_candidates: list[str],
) -> tuple[object, ...]:
    return (
        year,
        state,
        turn,
        position,
        tuple(selected_cities),
        tuple(selected_candidates),
    )


def _parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_float(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_valid_option(value: object, options: list[object], fallback: object) -> object:
    return value if value in options else fallback


def _valid_options(values: list[str], options: list[str], max_items: int | None = None) -> list[str]:
    option_set = set(options)
    valid_values = []

    for value in values:
        if value in option_set and value not in valid_values:
            valid_values.append(value)

    if max_items is not None:
        return valid_values[:max_items]

    return valid_values


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


def _sync_projection_state(query_projection: object, query_projection_scope: object) -> None:
    query_projection_percent = _normalize_projection_percent(query_projection)
    query_projection_scope = _valid_projection_scope(query_projection_scope)
    query_token = f"{_format_query_float(query_projection_percent)}:{query_projection_scope}"

    if (
        PROJECTION_PERCENT_KEY not in st.session_state
        or query_token != st.session_state.get(LAST_WRITTEN_PROJECTION_QUERY_KEY)
    ):
        st.session_state[PROJECTION_PERCENT_KEY] = query_projection_percent
        st.session_state[PROJECTION_INPUT_KEY] = query_projection_percent
        st.session_state[PROJECTION_SCOPE_KEY] = query_projection_scope
        st.session_state[LAST_WRITTEN_PROJECTION_QUERY_KEY] = query_token


def _build_projection_totals(data: pd.DataFrame, projection_percent: float) -> pd.DataFrame:
    projected = data.copy()
    projected["votos_reais"] = projected["votos"].astype(int)
    projected["votos_projecao"] = _project_vote_series(
        projected["votos_reais"],
        projection_percent,
    )
    projected["votos_total"] = projected["votos_reais"] + projected["votos_projecao"]
    return projected


def _aggregate_projected_city_totals(
    projected_city_data: pd.DataFrame,
    total_by_candidate: pd.DataFrame,
) -> pd.DataFrame:
    city_totals = (
        projected_city_data.groupby("deputado", as_index=False)[
            ["votos_reais", "votos_projecao", "votos_total"]
        ]
        .sum()
    )
    candidate_parties = total_by_candidate[["deputado", "partido", "votos"]]
    return candidate_parties.merge(city_totals, on="deputado", how="left").fillna(
        {"votos_reais": 0, "votos_projecao": 0, "votos_total": 0}
    )


def _project_vote_series(votes: pd.Series, projection_percent: float) -> pd.Series:
    if projection_percent <= 0:
        return pd.Series(0, index=votes.index, dtype=int)

    return (votes.astype(float) * (projection_percent / 100)).round().astype(int)


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


def _format_percent(value: float) -> str:
    normalized = _normalize_projection_percent(value)
    if normalized.is_integer():
        return f"{int(normalized)}%"
    return f"{normalized:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def _format_query_float(value: float) -> str:
    normalized = _normalize_projection_percent(value)
    if normalized.is_integer():
        return str(int(normalized))
    return f"{normalized:.2f}".rstrip("0").rstrip(".")


def _projects_cities(projection_scope: str) -> bool:
    return _valid_projection_scope(projection_scope) in {"ambos", "cidades"}


def _projects_total(projection_scope: str) -> bool:
    return _valid_projection_scope(projection_scope) in {"ambos", "total"}


def _projection_scope_label(projection_scope: str) -> str:
    normalized = _valid_projection_scope(projection_scope)
    for label, value in PROJECTION_SCOPE_OPTIONS.items():
        if value == normalized:
            return label
    return "Cidades e total"


def _projection_scope_index(projection_scope: str) -> int:
    normalized = _valid_projection_scope(projection_scope)
    options = list(PROJECTION_SCOPE_OPTIONS.values())
    return options.index(normalized) if normalized in options else 0


def _valid_projection_scope(value: object) -> str:
    text = str(value or "ambos").strip().lower()
    if text in PROJECTION_SCOPE_OPTIONS.values():
        return text
    return "ambos"


def _normalize_projection_percent(value: object) -> float:
    parsed_value = _parse_float(value)
    if parsed_value is None or parsed_value < 0:
        return 0.0
    return min(parsed_value, 1000.0)


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
