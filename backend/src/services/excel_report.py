"""Small OOXML writer: typed numbers and literal text, without formula execution."""
from io import BytesIO
import math
import re
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile, ZIP_DEFLATED

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def xml_bytes(content):
    return (XML_HEADER + content).encode("utf-8")
MAX_ROWS = 1_048_576


def column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell(value, reference):
    if value is None:
        return f'<c r="{reference}"/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return f'<c r="{reference}" t="n"><v>{value}</v></c>'
    text = INVALID_XML.sub("", str(value))[:32767]
    return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def workbook(sheets):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        overrides = []
        names = []
        relations = []
        for index, (name, rows) in enumerate(sheets, 1):
            path = f"xl/worksheets/sheet{index}.xml"
            with archive.open(path, "w") as stream:
                stream.write(xml_bytes(f'<worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews><sheetData>'))
                last = 0
                columns = 1
                for last, row in enumerate(rows, 1):
                    if last > MAX_ROWS:
                        raise ValueError("A consulta excede o limite de linhas do Excel. Reduza o período ou selecione um assunto.")
                    columns = max(columns, len(row))
                    cells = ''.join(cell(value, f"{column_name(col)}{last}") for col, value in enumerate(row, 1))
                    stream.write(f'<row r="{last}">{cells}</row>'.encode('utf-8'))
                stream.write(f'</sheetData><autoFilter ref="A1:{column_name(columns)}{max(1, last)}"/></worksheet>'.encode('utf-8'))
            overrides.append(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            names.append(f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>')
            relations.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
        archive.writestr('[Content_Types].xml', xml_bytes('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(overrides) + '</Types>'))
        archive.writestr('_rels/.rels', xml_bytes('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'))
        archive.writestr('xl/workbook.xml', xml_bytes(f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(names) + '</sheets></workbook>'))
        archive.writestr('xl/_rels/workbook.xml.rels', xml_bytes('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(relations) + '</Relationships>'))
    return output.getvalue()


def document_rows(query):
    yield ["ID do documento", "ID na fonte", "Número do processo", "Tribunal", "Instância", "Data de ajuizamento", "Código da classe", "Classe", "Código do órgão", "Órgão julgador", "Assuntos", "Resultado (proxy por documento)"]
    rows = query.select_related("process_dimension", "degree_dimension", "time", "process_class", "organization", "result").defer("raw_payload", "payload_hash").prefetch_related("subjects").order_by("pk")
    for row in rows.iterator(chunk_size=1000):
        yield [row.pk, row.source_id, row.number_process, row.court, row.degree, row.time.date.isoformat(), row.process_class.code, row.process_class.name, row.organization.code, row.organization.name, "; ".join(f"{s.code} - {s.name}" for s in sorted(row.subjects.all(), key=lambda s: s.code)), row.result.name]
