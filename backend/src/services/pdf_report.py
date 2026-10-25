"""Compact PDF summary of one authorized analytical selection."""

from collections import defaultdict
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def build_report(scope, totals, provenance, series, pangea=None, cases=None):
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Note", fontSize=9, leading=13, textColor=colors.HexColor("#405263")))
    story = []

    def paragraph(text, style="BodyText"):
        return Paragraph(escape(str(text)), styles[style])

    def table(rows, widths):
        result = Table([[paragraph(cell) for cell in row] for row in rows], colWidths=widths, repeatRows=1)
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d7dfe3")),
                ]
            )
        )
        return result

    def count(value):
        return f"{value:,}".replace(",", ".")

    def rate(value):
        return "Indisponível (sem base binária)" if value is None else f"{value * 100:.2f}%".replace(".", ",")

    generated = timezone.now().strftime("%d/%m/%Y %H:%M UTC")
    story += [
        paragraph("DatumLex | Relatório de pesquisa jurídica", "Title"),
        paragraph(f"Emitido em {generated}", "Note"),
        Spacer(1, 12),
    ]
    story += [
        paragraph("1. Síntese da pesquisa", "Heading2"),
        paragraph(
            f"Foram encontrados {count(totals['process_records'])} documentos processuais no recorte, "
            f"correspondentes a {count(totals['distinct_process_numbers'])} números CNJ distintos. "
            f"Em {count(totals['binary_denominator'])} documentos foi identificado um resultado binário: "
            f"{count(totals['granted'])} providos e {count(totals['denied'])} desprovidos. "
            "Esses números descrevem somente a base carregada. Não medem probabilidade de êxito e "
            "não substituem a leitura do inteiro teor."
        ),
        Spacer(1, 10),
    ]
    story += [
        paragraph("Recorte aplicado", "Heading2"),
        paragraph(
            f"Tribunais: {scope['court']}. Período: {scope['start']} a {scope['end']}. "
            f"Assunto TPU: {scope['subject'] or 'todos os assuntos carregados'}. "
            "Campo temporal: data de ajuizamento, não data de julgamento."
        ),
        Spacer(1, 12),
    ]
    story.append(
        table(
            [
                ["Indicador", "Valor"],
                ["Documentos consultados", count(totals["process_records"])],
                ["Base usada nas duas taxas (providos + desprovidos)", count(totals["binary_denominator"])],
                ["Taxa de provimento por documento", rate(totals["grant_rate"])],
                ["Taxa de desprovimento por documento", rate(totals["denial_rate"])],
            ],
            [320, 180],
        )
    )
    labels = {
        "partial": "Parcial",
        "not_admitted": "Não admitido",
        "partial_knowledge": "Conhecido em parte",
        "ambiguous": "Ambíguo",
        "unknown": "Sem resultado identificado",
        "outside_appellate_degree": "Fora do grau recursal",
    }
    annual = defaultdict(int)
    for row in series:
        annual[row["time__year"]] += row["count"]
    story += [
        paragraph("Como usar este relatório", "Heading2"),
        paragraph(
            "Use as teses e seus processos citados como ponto de partida para localizar precedentes. "
            "Confira o inteiro teor, a situação atual do precedente e a pertinência aos fatos do caso. "
            "Uma citação do Pangea não demonstra, por si só, que o TJDFT adotou ou afastou aquela tese. "
            "As fontes ainda não revisadas são identificadas expressamente."
        ),
    ]
    story += [
        paragraph("Fonte, atualização e limites", "Heading2"),
        paragraph(
            "Fonte: DataJud / CNJ - https://api-publica.datajud.cnj.jus.br/. "
            f"Última coleta no recorte: {provenance['last_record_refresh'] or 'indisponível'}. "
            f"Regra de classificação: {totals['rule_version']}.",
            "Note",
        ),
        paragraph(
            "Cobertura parcial dos registros carregados; não é um censo dos tribunais. "
            "Cada fato representa um documento da fonte. Um número CNJ pode aparecer em mais de uma instância. "
            "As taxas usam o último movimento TPU mapeado e datado no grau recursal, com desempate técnico por ID; "
            "não representam recursos individuais nem previsão de êxito. Zero registros não comprova ausência de processos. "
            "Pangea, textos de decisões e teses não são somados a estes indicadores DataJud. "
            "O relatório consulta o banco no momento da exportação e pode refletir novas coletas.",
            "Note",
        ),
    ]

    if pangea is not None:
        story += [
            PageBreak(),
            paragraph("2. Teses e precedentes para consulta | Pangea - STJ", "Heading2"),
            paragraph(
                "Inventário complementar, separado das taxas DataJud. Referências pendentes não constituem "
                "aprovação jurídica nem prova de aderência a um processo. A data de atualização da fonte "
                "não é data de julgamento ou publicação.",
                "Note",
            ),
            paragraph(
                f"Amostra: {len(pangea['items'])} de {pangea['sample_count']} referências com publicação no período "
                "ou sem data de publicação; aprovadas primeiro, depois atualização da fonte e identificador. "
                "Itens sem data ou assunto classificados são complementos sem correspondência confirmada ao recorte.",
                "Note",
            ),
            paragraph(
                f"{count(pangea['dated_count'])} referências têm publicação confirmada no período; "
                f"{count(pangea['undated_count'])} não informam publicação e "
                f"{count(pangea['unmapped_subject_count'])} não têm assunto TPU classificado.",
                "Note",
            ),
        ]
        if not pangea["items"]:
            story.append(paragraph("Nenhuma referência Pangea disponível neste recorte."))
        for item in pangea["items"]:
            story.append(
                KeepTogether(
                    [
                        paragraph(item["title"], "Heading3"),
                        paragraph(
                            f"Revisão: {'aprovada' if item['approved'] else 'pendente de aprovação jurídica'}. "
                            f"Publicação: {item['published_at'] or 'não informada - período não confirmado'}. "
                            f"Atualização da fonte: {item['source_updated_at'] or 'não informada'}. "
                            f"Assunto TPU: {item['subject_code'] or 'não classificado'}. "
                            f"Identificador: {item['identifier']}.",
                            "Note",
                        ),
                        paragraph(
                            item["thesis"][:1800]
                            + (
                                " [Trecho limitado a 1.800 caracteres; consulte o enunciado completo na fonte.]"
                                if len(item["thesis"]) > 1800
                                else ""
                            )
                        ),
                        paragraph(
                            "Processos citados pela fonte: "
                            + (
                                "; ".join(
                                    str(decision.get("identifier", ""))
                                    for decision in item.get("related_decisions", [])[:3]
                                )
                                or "não informados"
                            )
                            + ". A citação não confirma vínculo com um processo local.",
                            "Note",
                        ),
                        paragraph(f"Fonte: {item['source_url']}", "Note"),
                    ]
                )
            )

    if cases is not None:
        story += [
            PageBreak(),
            paragraph("Registros processuais para conferência", "Heading2"),
            paragraph(
                "Até cinco documentos do recorte, priorizando resultados identificados e depois o ajuizamento mais recente. "
                "São metadados para localizar os autos; não representam uma seleção de precedentes mais relevantes.",
                "Note",
            ),
        ]
        if not cases:
            story.append(paragraph("Sem registros processuais no período selecionado."))
        results = {"granted": "Provido", "denied": "Desprovido", "partial": "Parcial"}
        for item in cases:
            story.append(
                KeepTogether(
                    [
                        paragraph(
                            f"{item['court']} | Processo {item['process_dimension__number_process']}",
                            "Heading3",
                        ),
                        paragraph(
                            f"Classe: {item['process_class__name']}. Órgão: {item['organization__name']}. "
                            f"Ajuizamento: {item['time__date']}. Resultado identificado: "
                            f"{results.get(item['result__name'], 'sem resultado recursal conclusivo')}."
                        ),
                    ]
                )
            )
    story += [
        paragraph("Notas de leitura e cobertura", "Heading2"),
        paragraph(
            "Excluídos das taxas: "
            + "; ".join(
                f"{labels.get(key, key)}: {count(value)}" for key, value in totals["excluded"].items()
            )
            + ".",
            "Note",
        ),
        paragraph(
            "Volume por ano de ajuizamento: "
            + (
                "; ".join(f"{year}: {count(value)}" for year, value in sorted(annual.items()))
                or "Sem registros"
            )
            + ".",
            "Note",
        ),
    ]

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(47, 25, "DatumLex | Dados públicos - acesso conforme permissões do usuário")
        canvas.drawRightString(A4[0] - 47, 25, f"Página {document.page}")

    SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=47,
        leftMargin=47,
        topMargin=38,
        bottomMargin=44,
        title="DatumLex - Relatório de pesquisa jurídica",
        author="DatumLex",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
