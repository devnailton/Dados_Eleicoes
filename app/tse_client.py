from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests


CKAN_PACKAGE_URL = "https://dadosabertos.tse.jus.br/api/3/action/package_show"
TSE_DATASET_URL = "https://dadosabertos.tse.jus.br/dataset/resultados-{year}-boletim-de-urna"

CACHE_DIR = Path("data/cache/tse")
DOWNLOAD_DIR = CACHE_DIR / "downloads"
AGGREGATED_DIR = CACHE_DIR / "aggregated"

SUPPORTED_YEARS = (2024, 2022, 2020, 2018)
BRAZILIAN_UFS = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
)

TSE_COLUMNS = {
    "estado": ("sg_uf", "uf"),
    "cidade": ("nm_municipio", "municipio"),
    "cargo": ("ds_cargo_pergunta", "cargo"),
    "tipo_votavel": ("ds_tipo_votavel", "tipo_votavel"),
    "deputado": ("nm_votavel", "nome_votavel", "candidato"),
    "partido": ("sg_partido", "partido"),
    "votos": ("qt_votos", "votos"),
}


class TSEClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class TSEBUResource:
    year: int
    uf: str
    turn: int
    name: str
    url: str
    format: str

    @property
    def dataset_url(self) -> str:
        return TSE_DATASET_URL.format(year=self.year)


def list_available_years() -> list[int]:
    return list(SUPPORTED_YEARS)


def list_states(year: int) -> list[str]:
    resources = list_bu_resources(year)
    states = sorted({resource.uf for resource in resources if resource.uf in BRAZILIAN_UFS})
    if not states:
        raise TSEClientError(f"Nenhum boletim de urna foi encontrado para {year}.")
    return states


def list_turns(year: int, uf: str) -> list[int]:
    uf = uf.upper()
    turns = sorted(
        {resource.turn for resource in list_bu_resources(year) if resource.uf == uf}
    )
    if not turns:
        raise TSEClientError(f"Nenhum turno foi encontrado para {uf} em {year}.")
    return turns


def list_bu_resources(year: int) -> list[TSEBUResource]:
    if year not in SUPPORTED_YEARS:
        supported = ", ".join(str(value) for value in SUPPORTED_YEARS)
        raise TSEClientError(f"Ano ainda nao suportado. Anos disponiveis: {supported}.")

    package = _fetch_package(year)
    resources = [
        resource
        for raw_resource in package.get("resources", [])
        if (resource := _parse_resource(year, raw_resource)) is not None
    ]

    return sorted(resources, key=lambda resource: (resource.uf, resource.turn))


def load_tse_votes(year: int, uf: str, turn: int) -> tuple[pd.DataFrame, TSEBUResource]:
    resource = _find_resource(year, uf, turn)
    zip_path = _download_resource(resource)
    data = _aggregate_bu_zip(zip_path, resource)
    return data, resource


def _fetch_package(year: int) -> dict[str, Any]:
    try:
        response = requests.get(
            CKAN_PACKAGE_URL,
            params={"id": f"resultados-{year}-boletim-de-urna"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        raise TSEClientError(f"Falha ao consultar o Portal de Dados Abertos do TSE: {error}") from error

    if not payload.get("success"):
        raise TSEClientError(f"O conjunto de boletins de urna de {year} nao foi localizado no TSE.")

    return payload["result"]


def _parse_resource(year: int, raw_resource: dict[str, Any]) -> TSEBUResource | None:
    name = str(raw_resource.get("name") or "")
    url = str(raw_resource.get("url") or "")
    file_format = str(raw_resource.get("format") or "")
    searchable = f"{name} {url}".lower()

    if "boletim" not in searchable or "bweb" not in searchable:
        return None

    file_match = re.search(r"bweb_([12])t_([a-z]{2})_", url, flags=re.IGNORECASE)
    if file_match:
        turn = int(file_match.group(1))
        uf = file_match.group(2).upper()
    else:
        name_match = re.match(r"^\s*([A-Z]{2})\s*-", name)
        if not name_match:
            return None

        uf = name_match.group(1).upper()
        if "segundo" in searchable:
            turn = 2
        elif "primeiro" in searchable:
            turn = 1
        else:
            return None

    return TSEBUResource(
        year=year,
        uf=uf,
        turn=turn,
        name=name,
        url=url,
        format=file_format,
    )


def _find_resource(year: int, uf: str, turn: int) -> TSEBUResource:
    uf = uf.upper()
    for resource in list_bu_resources(year):
        if resource.uf == uf and resource.turn == turn:
            return resource

    raise TSEClientError(f"Arquivo oficial nao encontrado para {uf}, {year}, {turn} turno.")


def _download_resource(resource: TSEBUResource) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_name = Path(urlparse(resource.url).path).name
    if not file_name:
        file_name = f"bweb_{resource.turn}t_{resource.uf}_{resource.year}.zip"

    target = DOWNLOAD_DIR / file_name
    if target.exists() and target.stat().st_size > 0:
        return target

    try:
        with requests.get(resource.url, stream=True, timeout=(15, 180)) as response:
            response.raise_for_status()
            expected_size = int(response.headers.get("Content-Length") or 0)

            with tempfile.NamedTemporaryFile(delete=False, dir=DOWNLOAD_DIR) as tmp_file:
                temp_path = Path(tmp_file.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        tmp_file.write(chunk)
    except requests.RequestException as error:
        raise TSEClientError(f"Falha ao baixar o boletim de urna do TSE: {error}") from error

    if expected_size and temp_path.stat().st_size != expected_size:
        temp_path.unlink(missing_ok=True)
        raise TSEClientError("O download do boletim de urna ficou incompleto.")

    temp_path.replace(target)
    return target


def _aggregate_bu_zip(zip_path: Path, resource: TSEBUResource) -> pd.DataFrame:
    AGGREGATED_DIR.mkdir(parents=True, exist_ok=True)
    aggregated_path = AGGREGATED_DIR / f"votos_{resource.year}_{resource.turn}t_{resource.uf}.csv"

    if aggregated_path.exists() and aggregated_path.stat().st_size > 0:
        return pd.read_csv(aggregated_path)

    with zipfile.ZipFile(zip_path) as zipped_file:
        data_file_name = _find_bu_data_file(zipped_file)
        columns = _read_bu_columns(zipped_file, data_file_name)
        column_map = _resolve_tse_columns(columns)
        usecols = list(column_map.values())

        grouped_chunks: list[pd.DataFrame] = []
        with zipped_file.open(data_file_name) as data_file:
            reader = pd.read_csv(
                data_file,
                sep=";",
                encoding="latin1",
                dtype=str,
                usecols=usecols,
                chunksize=200_000,
            )

            for chunk in reader:
                grouped = _aggregate_chunk(chunk, column_map, resource)
                if not grouped.empty:
                    grouped_chunks.append(grouped)

    if not grouped_chunks:
        raise TSEClientError("Nenhum voto nominal foi encontrado no boletim selecionado.")

    data = (
        pd.concat(grouped_chunks, ignore_index=True)
        .groupby(
            ["ano", "turno", "estado", "cidade", "cargo", "deputado", "partido"],
            as_index=False,
            dropna=False,
        )["votos"]
        .sum()
        .sort_values(["cargo", "cidade", "votos"], ascending=[True, True, False])
    )

    data.to_csv(aggregated_path, index=False, encoding="utf-8")
    return data


def _find_bu_data_file(zipped_file: zipfile.ZipFile) -> str:
    candidates = [
        name
        for name in zipped_file.namelist()
        if name.lower().endswith(".csv") and not Path(name).name.startswith("_")
    ]

    if not candidates:
        raise TSEClientError("O ZIP do TSE nao contem um arquivo CSV de boletim.")

    return candidates[0]


def _read_bu_columns(zipped_file: zipfile.ZipFile, data_file_name: str) -> list[str]:
    with zipped_file.open(data_file_name) as data_file:
        return list(
            pd.read_csv(
                data_file,
                sep=";",
                encoding="latin1",
                dtype=str,
                nrows=0,
            ).columns
        )


def _resolve_tse_columns(columns: list[str]) -> dict[str, str]:
    normalized_columns = {_normalize_column_name(column): column for column in columns}
    resolved: dict[str, str] = {}

    for canonical_name, candidates in TSE_COLUMNS.items():
        for candidate in candidates:
            normalized = _normalize_column_name(candidate)
            if normalized in normalized_columns:
                resolved[canonical_name] = normalized_columns[normalized]
                break

        if canonical_name not in resolved:
            expected = ", ".join(candidates)
            raise TSEClientError(
                f"Coluna obrigatoria ausente no arquivo do TSE: {canonical_name}. "
                f"Nomes esperados: {expected}."
            )

    return resolved


def _aggregate_chunk(
    chunk: pd.DataFrame,
    column_map: dict[str, str],
    resource: TSEBUResource,
) -> pd.DataFrame:
    chunk = chunk.rename(columns={value: key for key, value in column_map.items()})
    chunk["tipo_votavel"] = _clean_text_series(chunk["tipo_votavel"]).str.upper()
    chunk = chunk[chunk["tipo_votavel"] == "NOMINAL"].copy()

    if chunk.empty:
        return pd.DataFrame()

    chunk["ano"] = resource.year
    chunk["turno"] = resource.turn
    chunk["estado"] = resource.uf
    chunk["cidade"] = _clean_text_series(chunk["cidade"]).str.title()
    chunk["cargo"] = _clean_text_series(chunk["cargo"]).str.upper()
    chunk["deputado"] = _clean_text_series(chunk["deputado"]).str.upper()
    chunk["partido"] = _clean_text_series(chunk["partido"]).str.upper()
    chunk["votos"] = _clean_votes(chunk["votos"])

    chunk = chunk[
        (chunk["cidade"] != "")
        & (chunk["cargo"] != "")
        & (chunk["deputado"] != "")
        & (chunk["votos"] > 0)
    ]

    if chunk.empty:
        return pd.DataFrame()

    return chunk.groupby(
        ["ano", "turno", "estado", "cidade", "cargo", "deputado", "partido"],
        as_index=False,
        dropna=False,
    )["votos"].sum()


def _normalize_column_name(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _clean_text_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.replace("#NULO#", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def _clean_votes(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.replace(r"[^\d-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0).astype(int)
