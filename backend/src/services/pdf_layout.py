"""Five-page research report following the supplied Sprint 2 layout, using real data."""

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

NAVY = colors.HexColor("#102c3d")
TEAL = colors.HexColor("#205669")
GOLD = colors.HexColor("#c7a218")
GREEN = colors.HexColor("#3f7756")
INK = colors.HexColor("#193348")
MUTED = colors.HexColor("#596875")
PALE = colors.HexColor("#f7f5ef")
BORDER = colors.HexColor("#d8d3c7")
W, H = A4
LEFT, WIDTH = 44, A4[0] - 88


def number(value):
    return f"{value:,}".replace(",", ".")


def percentage(value):
    return "Indisponível" if value is None else f"{value * 100:.1f}%".replace(".", ",")


class Report:
    def __init__(self, buffer, report_id):
        self.canvas = Canvas(buffer, pagesize=A4)
        self.canvas.setTitle("DatumLex | Relatório de pesquisa")
        self.canvas.setAuthor("DatumLex")
        self.report_id = report_id

    def text(self, value, y, *, x=LEFT, width=WIDTH, size=9, leading=13, bold=False, color=INK):
        style = ParagraphStyle(
            "report",
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=leading,
            textColor=color,
            splitLongWords=True,
        )
        para = Paragraph(escape(str(value)), style)
        _, height = para.wrap(width, H)
        if y - height < 51:
            raise ValueError("PDF content exceeds its page budget")
        para.drawOn(self.canvas, x, y - height)
        return y - height - 8

    def heading(self, title, y):
        self.canvas.setFillColor(NAVY)
        self.canvas.setFont("Times-Bold", 18)
        self.canvas.drawString(LEFT, y - 18, title)
        return y - 33

    def page(self, index, section, title, subtitle):
        c = self.canvas
        if index > 1:
            c.showPage()
        logo = Path(__file__).resolve().parents[2] / "static/datumlex-logo-horizontal.jpg"
        if logo.exists():
            c.drawImage(
                str(logo),
                LEFT,
                H - 70,
                width=145,
                height=42,
                preserveAspectRatio=True,
                anchor="sw",
                mask="auto",
            )
        else:
            c.setFont("Times-Bold", 22)
            c.setFillColor(NAVY)
            c.drawString(LEFT, H - 53, "DatumLex")
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(TEAL)
        c.drawRightString(W - LEFT, H - 49, "RELATÓRIO DE PESQUISA")
        c.setStrokeColor(GOLD)
        c.line(LEFT, H - 88, W - LEFT, H - 88)
        c.drawString(LEFT, H - 116, f"{index:02d} / {section.upper()}")
        c.setFillColor(NAVY)
        title_size = 26
        while c.stringWidth(title, "Times-Bold", title_size) > WIDTH and title_size > 17:
            title_size -= 1
        c.setFont("Times-Bold", title_size)
        c.drawString(LEFT, H - 153, title)
        y = self.text(subtitle, H - 168, size=10, color=MUTED)
        c.setStrokeColor(BORDER)
        c.line(LEFT, 42, W - LEFT, 42)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(LEFT, 24, f"DADOS DA CONSULTA | {self.report_id}")
        c.drawRightString(W - LEFT, 24, f"{index:02d} / 05")
        return y - 16

    def table(self, rows, y, widths=None, size=9, padding=8):
        widths = widths or [WIDTH * 0.34, WIDTH * 0.66]
        style = ParagraphStyle("cell", fontName="Helvetica", fontSize=size, leading=size + 3, textColor=INK)
        head = ParagraphStyle("head", parent=style, textColor=colors.white)
        cells = [
            [Paragraph(escape(str(value)), head if index == 0 else style) for value in row]
            for index, row in enumerate(rows)
        ]
        table = Table(cells, colWidths=widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, colors.white]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                    ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER),
                ]
            )
        )
        _, height = table.wrap(WIDTH, H)
        if y - height < 51:
            raise ValueError("PDF table exceeds its page budget")
        table.drawOn(self.canvas, LEFT, y - height)
        return y - height - 14

    def notice(self, title, text, y):
        self.canvas.setFillColor(PALE)
        self.canvas.rect(LEFT, y - 72, WIDTH, 72, fill=1, stroke=0)
        self.canvas.setFillColor(GOLD)
        self.canvas.rect(LEFT, y - 72, 3, 72, fill=1, stroke=0)
        next_y = self.text(title, y - 12, x=LEFT + 14, width=WIDTH - 28, bold=True)
        self.text(text, next_y, x=LEFT + 14, width=WIDTH - 28, size=8.5, leading=12, color=MUTED)
        return y - 90

    def source_link(self, url, y):
        bottom = self.text(f"Fonte: {url[:160]}", y, size=7.5, leading=10, color=TEAL)
        parsed = urlparse(url)
        if parsed.scheme == "https" and not parsed.username and not parsed.password:
            self.canvas.linkURL(url, (LEFT, bottom + 8, LEFT + WIDTH, y), relative=0)
        return bottom

    def cards(self, cards, y):
        gap = 16
        width = (WIDTH - gap) / 2
        for i, (value, label, note, color) in enumerate(cards):
            x = LEFT + (i % 2) * (width + gap)
            top = y - (i // 2) * 91
            self.canvas.setFillColor(PALE)
            self.canvas.rect(x, top - 78, width, 78, fill=1, stroke=0)
            self.canvas.setFillColor(color)
            self.canvas.rect(x, top - 78, 3, 78, fill=1, stroke=0)
            self.canvas.setFont("Times-Bold", 22 if len(value) < 12 else 16)
            self.canvas.drawString(x + 13, top - 28, value)
            self.text(label, top - 35, x=x + 13, width=width - 24, size=9, bold=True)
            self.text(note, top - 54, x=x + 13, width=width - 24, size=7.5, leading=10, color=MUTED)
        return y - 182


def build_report(scope, totals, provenance, series, pangea=None, cases=None, context=None):
    context = context or {}
    output = BytesIO()
    report_id = uuid4().hex[:12].upper()
    r = Report(output, report_id)
    courts = scope["court"].replace(",", " e ")
    subject = context.get("subject_name") or (
        f"Assunto TPU {scope['subject']}" if scope["subject"] else "Pesquisa jurídica integrada"
    )
    period = f"{datetime.fromisoformat(scope['start']):%d/%m/%Y} a {datetime.fromisoformat(scope['end']):%d/%m/%Y}"
    review = context.get("assessments", {})
    comparable = review.get("aligned", 0) + review.get("divergent", 0)
    adherence = review.get("aligned", 0) / comparable if comparable else None
    denominator = totals["binary_denominator"]

    y = r.page(
        1, "Visão geral", subject[:45], f"Pesquisa integrada | {courts} | Recorte aplicado na consulta"
    )
    y = r.notice(
        "Pesquisa sobre os dados carregados",
        "Valores calculados no momento da exportação. A base é parcial; documentos, processos e recursos individuais são unidades diferentes.",
        y,
    )
    y = r.heading("Filtros aplicados", y)
    y = r.table(
        [
            ["PARÂMETRO", "RECORTE DA PESQUISA"],
            ["Tribunais", courts],
            ["Assunto", subject],
            ["Período solicitado", period],
            ["Campo temporal", "Ajuizamento (DataJud); decisão nas avaliações revisadas"],
            ["Fonte jurídica", "DataJud" + (" e referências Pangea/STJ" if pangea is not None else "")],
        ],
        y,
    )
    y = r.heading("Panorama da pesquisa", y)
    r.cards(
        [
            (
                number(totals["process_records"]),
                "Documentos DataJud",
                f"{number(totals['distinct_process_numbers'])} números CNJ distintos",
                NAVY,
            ),
            (
                percentage(totals["grant_rate"]),
                "Taxa de provimento",
                f"{number(totals['granted'])} / {number(denominator)} documentos classificáveis",
                GREEN,
            ),
            (
                percentage(adherence),
                "Aderência revisada",
                f"Base: {number(comparable)} vínculos alinhados ou divergentes",
                GOLD,
            ),
            (
                "Indisponível",
                "Cobertura NLP nesta exportação",
                "Requer snapshot de evidências revisadas e liberadas",
                TEAL,
            ),
        ],
        y,
    )

    y = r.page(
        2,
        "Resultados e tendências",
        "Mérito recursal",
        f"{courts} | Mesmo período e assunto da página 1 | Indicador por documento",
    )
    y = r.heading("Distribuição dos resultados", y)
    if denominator:
        portion = totals["granted"] / denominator
        r.canvas.setFillColor(TEAL)
        r.canvas.rect(LEFT, y - 25, WIDTH, 25, fill=1, stroke=0)
        r.canvas.setFillColor(GREEN)
        r.canvas.rect(LEFT, y - 25, WIDTH * portion, 25, fill=1, stroke=0)
        y = r.text(
            f"Providos: {number(totals['granted'])} ({percentage(totals['grant_rate'])}) | Desprovidos: {number(totals['denied'])} ({percentage(totals['denial_rate'])})",
            y - 38,
            bold=True,
        )
    else:
        y = r.notice(
            "Indisponível (sem base binária)",
            "Nenhum resultado binário identificado neste recorte. Ausência de base não é taxa de 0%.",
            y,
        )
    y = r.heading("Taxa de provimento ao longo do tempo", y - 12)
    annual = context.get("annual")
    if annual is None:
        volume = defaultdict(int)
        for item in series:
            volume[item["time__year"]] += item["count"]
        annual = [
            {"time__year": year, "documents": value, "granted": None, "denied": None}
            for year, value in sorted(volume.items())
        ]
    chart_top = y - 10
    chart_height = 115
    chart_left = LEFT + 30
    chart_width = WIDTH - 40
    c = r.canvas
    for tick in (0, 25, 50, 75, 100):
        pos = chart_top - chart_height + chart_height * tick / 100
        c.setStrokeColor(BORDER)
        c.line(chart_left, pos, chart_left + chart_width, pos)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawRightString(chart_left - 6, pos - 2, f"{tick}%")
    previous = None
    for index, item in enumerate(annual):
        x = chart_left + chart_width * index / max(1, len(annual) - 1)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawCentredString(x, chart_top - chart_height - 15, str(item["time__year"]))
        total = (item["granted"] or 0) + (item["denied"] or 0)
        if not total:
            previous = None
            continue
        rate = item["granted"] / total
        point = (x, chart_top - chart_height + chart_height * rate)
        c.setStrokeColor(TEAL)
        c.setLineWidth(2)
        if previous:
            c.line(*previous, *point)
        c.setFillColor(TEAL)
        c.circle(*point, 2.5, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(point[0], point[1] + 9, percentage(rate))
        previous = point
    y = chart_top - chart_height - 35
    y = r.table(
        [["ANO", "DOCUMENTOS", "PROVIDOS", "DESPROVIDOS"]]
        + [
            [
                item["time__year"],
                number(item["documents"]),
                number(item["granted"]) if item["granted"] is not None else "Não disponível",
                number(item["denied"]) if item["denied"] is not None else "Não disponível",
            ]
            for item in annual
        ],
        y,
        [WIDTH * 0.16, WIDTH * 0.28, WIDTH * 0.28, WIDTH * 0.28],
        size=8,
        padding=4,
    )
    if not annual:
        y = r.text("Sem registros no recorte.", y)
    r.text(
        "Anos sem denominador não recebem taxa nem ligação no gráfico. O volume inclui todos os graus; as taxas usam apenas os resultados binários elegíveis. O último ano pode ser parcial conforme o filtro.",
        y,
        size=8,
        leading=11,
        color=MUTED,
    )

    y = r.page(
        3,
        "Precedentes e teses",
        "Relação com o STJ",
        "Avaliações humanas validadas e referências de consulta, em populações separadas",
    )
    y = r.heading("Comparação dos vínculos revisados", y)
    if comparable or sum(review.values()):
        y = r.table(
            [["CLASSIFICAÇÃO", "VÍNCULOS"]]
            + [
                [label, number(review.get(key, 0))]
                for key, label in [
                    ("aligned", "Aderência identificada"),
                    ("divergent", "Possível divergência"),
                    ("distinguished", "Distinção registrada"),
                    ("uncertain", "Inconclusivo"),
                ]
            ],
            y,
        )
        y = r.text(
            f"Taxa de aderência: {percentage(adherence)}. Base: {comparable} vínculos alinhados ou divergentes; demais categorias ficam fora da taxa. Período por data de decisão revisada, não ajuizamento.",
            y,
            size=8,
            leading=11,
        )
    else:
        y = r.notice(
            "Comparação jurídica indisponível",
            "Não há avaliações validadas elegíveis. Citações do Pangea não são convertidas automaticamente em aderência ou divergência.",
            y,
        )
    y = r.heading("Teses e precedentes para consulta", y)
    if pangea and pangea["items"]:
        y = r.text(
            f"Amostra de até três das {number(pangea['sample_count'])} referências no inventário complementar. Não é ranking NLP de relevância ou frequência. Itens sem data ou assunto classificados não têm correspondência confirmada ao recorte.",
            y,
            size=8,
            leading=11,
        )
        for item in pangea["items"][:3]:
            y = r.text(item["title"][:100], y, bold=True)
            y = r.text(
                item["thesis"][:330] + (" [Trecho; consulte a fonte.]" if len(item["thesis"]) > 330 else ""),
                y,
                size=8.5,
                leading=12,
            )
            y = r.text(
                f"Revisão: {'aprovada' if item['approved'] else 'pendente de aprovação jurídica'}. Publicação: {item['published_at'] or 'não informada - período não confirmado'}.",
                y,
                size=8,
                leading=11,
                color=MUTED,
            )
            y = r.source_link(item["source_url"], y)
    else:
        y = r.text(
            "Nenhuma referência Pangea nesta exportação. Inclua STJ para consultar o inventário disponível.",
            y,
        )
    r.text(
        "Frequência de teses NLP: indisponível neste resumo sem snapshot de evidências revisadas e liberadas. Nenhuma série demonstrativa foi usada.",
        y - 5,
        size=8,
        leading=11,
        color=MUTED,
    )

    y = r.page(
        4,
        "Rastreabilidade",
        "Evidências da pesquisa",
        "Metadados para localizar os autos e conferir a origem das informações",
    )
    y = r.heading("Registros processuais para conferência", y)
    y = r.text(
        "Até dois documentos da consulta, priorizando resultados identificados e depois ajuizamento mais recente. Não representam uma seleção de precedentes mais relevantes.",
        y,
        size=8,
        leading=11,
    )
    labels = {"granted": "Provido", "denied": "Desprovido", "partial": "Parcial"}
    for item in (cases or [])[:2]:
        y = r.text(f"{item['court']} | Processo {item['process_dimension__number_process']}", y, bold=True)
        y = r.table(
            [
                ["CAMPO", "INFORMAÇÃO DISPONÍVEL"],
                ["Classe / órgão", f"{item['process_class__name']} / {item['organization__name']}"],
                [
                    "Data / resultado",
                    f"Ajuizamento: {item['time__date']}. Resultado: {labels.get(item['result__name'], 'não conclusivo')}",
                ],
                [
                    "Trecho e revisão",
                    "Inteiro teor e avaliação jurídica não estão incluídos neste metadado DataJud.",
                ],
            ],
            y,
            size=8,
        )
    if not cases:
        y = r.text("Sem registros processuais para conferência no recorte.", y)
    y = r.text("Fonte dos metadados: https://api-publica.datajud.cnj.jus.br/", y, size=8, color=TEAL)
    y = r.heading("Doutrina relacionada | BDJur", y)
    r.text(
        "Não integrada a este resumo. Nenhum material doutrinário foi incluído nos indicadores. O relatório de evidências NLP permanece disponível separadamente quando houver snapshot revisado e liberado.",
        y,
        size=8,
        leading=11,
    )

    y = r.page(
        5,
        "Fontes, cobertura e limitações",
        "Como ler este relatório",
        "Metadados da consulta e critérios para interpretar os resultados exportados",
    )
    y = r.table(
        [
            ["FONTE / CAMADA", "COBERTURA NESTA EXPORTAÇÃO"],
            [
                "DataJud / CNJ",
                f"{number(totals['process_records'])} documentos e {number(totals['distinct_process_numbers'])} números CNJ distintos no recorte.",
            ],
            [
                "Pangea / STJ",
                f"{number(pangea['inventory_count'])} referências no inventário complementar; {number(pangea['undated_count'])} sem publicação informada."
                if pangea
                else "Não incluído nesta seleção.",
            ],
            [
                "Textos e NLP",
                "Sem cobertura quantificada neste resumo. Metadados não equivalem a decisões com inteiro teor processado.",
            ],
            ["BDJur", "Doutrina não incluída nos indicadores desta exportação."],
        ],
        y,
        size=8.5,
    )
    y = r.heading("Critérios e limitações", y)
    y = r.text(
        "Unidade de contagem. Os valores DataJud contam documentos da fonte, não recursos individuais. Um número CNJ pode aparecer em mais de uma instância. A base carregada é parcial.",
        y,
    )
    y = r.text(
        "Resultado e instância. Taxa = providos / (providos + desprovidos). A regra usa o último movimento TPU mapeado e datado em G2/TR no TJDFT e SUP no STJ; empate usa o maior ID local. Ausência de denominador é indisponibilidade, não 0%.",
        y,
    )
    excluded = {
        "partial": "Parcial",
        "not_admitted": "Não admitido",
        "partial_knowledge": "Conhecido em parte",
        "ambiguous": "Ambíguo",
        "unknown": "Sem resultado",
        "outside_appellate_degree": "Fora do grau recursal",
    }
    y = r.text(
        "Fora das taxas: "
        + "; ".join(f"{excluded.get(key, key)}: {number(value)}" for key, value in totals["excluded"].items())
        + ".",
        y,
        size=8.5,
        leading=12,
    )
    y = r.text(
        "Cobertura e NLP. Citação ou similaridade não comprovam aderência jurídica. Teses Pangea não são automaticamente evidências NLP revisadas. Atualização da fonte não substitui data de publicação ou julgamento; assunto não classificado não comprova correspondência temática.",
        y,
    )
    y = r.heading("Identificação da exportação", y)
    now = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S - Brasília")
    y = r.text(f"Pesquisa: {report_id} | Emissão: {now} | Layout: sprint2-real-v1", y, size=8.5)
    y = r.text(
        f"Última coleta DataJud no recorte: {provenance['last_record_refresh'] or 'não disponível'}. Regra: {totals['rule_version']}.",
        y,
        size=8.5,
    )
    r.text(
        "Os dados foram consultados na exportação. O identificador rastreia este arquivo; não é um snapshot persistido das evidências NLP. Os filtros não garantem cobertura integral das fontes.",
        y,
        size=8.5,
        color=MUTED,
    )
    r.canvas.save()
    return output.getvalue()
