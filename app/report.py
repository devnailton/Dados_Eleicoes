from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


REPORT_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#f97316"]


class HorizontalBarChart(Flowable):
    def __init__(self, data: pd.DataFrame, width: float = 24 * cm, height: float = 5 * cm):
        super().__init__()
        self.data = data
        self.width = width
        self.height = height

    def draw(self) -> None:
        if self.data.empty:
            return

        left_label_width = 7 * cm
        right_label_width = 3 * cm
        bar_width = self.width - left_label_width - right_label_width
        row_height = min(0.85 * cm, self.height / max(len(self.data), 1))
        max_votes = max(int(self.data["votos"].max()), 1)

        for index, row in self.data.reset_index(drop=True).iterrows():
            y = self.height - ((index + 1) * row_height)
            color = colors.HexColor(REPORT_COLORS[index % len(REPORT_COLORS)])
            votes = int(row["votos"])
            width = (votes / max_votes) * bar_width
            candidate = _short_text(str(row["deputado"]), 34)

            self.canv.setFillColor(colors.black)
            self.canv.setFont("Helvetica", 8)
            self.canv.drawString(0, y + 0.18 * cm, candidate)

            self.canv.setFillColor(color)
            self.canv.rect(left_label_width, y + 0.12 * cm, width, 0.34 * cm, fill=True, stroke=False)

            self.canv.setFillColor(colors.black)
            self.canv.drawString(
                left_label_width + bar_width + 0.3 * cm,
                y + 0.18 * cm,
                _format_votes(votes),
            )


def build_pdf_report(
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
) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.0 * cm,
    )
    styles = getSampleStyleSheet()
    story: list[object] = []

    story.append(Paragraph("Relatorio de votos por candidato", styles["Title"]))
    story.append(Spacer(1, 0.3 * cm))

    cities_text = ", ".join(selected_cities) if selected_cities else "Todas as cidades"
    candidates_text = ", ".join(selected_candidates)
    source_name = source.get("name", "Portal de Dados Abertos do TSE")

    filter_rows = [
        ["Ano", str(year), "Estado", state, "Turno", f"{turn}"],
        ["Cargo", position, "Cidades", cities_text, "Fonte", source_name],
        ["Candidatos", candidates_text, "", "", "", ""],
    ]
    story.append(_styled_table(filter_rows, header=False, col_widths=[2.2 * cm, 5 * cm, 2.2 * cm, 8 * cm, 2.2 * cm, 8 * cm]))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Total por candidato", styles["Heading2"]))
    story.append(HorizontalBarChart(total_by_candidate))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_totals_table(total_by_candidate))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Votos por cidade", styles["Heading2"]))
    story.append(_city_table(city_candidate_totals))

    document.build(story)
    return buffer.getvalue()


def _totals_table(total_by_candidate: pd.DataFrame) -> Table:
    rows = [["Candidato", "Partido", "Total de votos"]]
    for _, row in total_by_candidate.iterrows():
        rows.append(
            [
                str(row["deputado"]),
                str(row.get("partido", "")),
                _format_votes(int(row["votos"])),
            ]
        )

    return _styled_table(rows, header=True, col_widths=[12 * cm, 4 * cm, 4 * cm])


def _city_table(city_candidate_totals: pd.DataFrame) -> Table:
    rows = [["Cidade", "Candidato", "Total de votos"]]
    for _, row in city_candidate_totals.iterrows():
        rows.append(
            [
                str(row["cidade"]),
                str(row["deputado"]),
                _format_votes(int(row["votos"])),
            ]
        )

    return _styled_table(rows, header=True, col_widths=[7 * cm, 12 * cm, 4 * cm])


def _styled_table(rows: list[list[str]], header: bool, col_widths: Iterable[float]) -> Table:
    table = Table(rows, colWidths=list(col_widths), repeatRows=1 if header else 0)
    style_commands = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    if header:
        style_commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )

    table.setStyle(TableStyle(style_commands))
    return table


def _format_votes(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _short_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."
