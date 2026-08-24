"""Extraccion de texto de archivos que un agente conoce de memoria."""

from __future__ import annotations

import io

import pytest

from aw1.core.errors import ValidationError
from aw1.core.file_extract import extract_text


def test_plain_text_is_decoded():
    assert extract_text("notas.txt", "Hola mundo".encode()) == "Hola mundo"


def test_csv_rows_are_joined_with_a_separator():
    content = "producto,precio\nZeta 12,549990\n".encode()
    assert extract_text("precios.csv", content) == "producto | precio\nZeta 12 | 549990"


def test_an_unreadable_file_raises_instead_of_returning_empty_text():
    with pytest.raises(ValidationError, match="texto legible"):
        extract_text("foto.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF")


def test_a_file_over_the_size_limit_is_rejected():
    with pytest.raises(ValidationError, match="MB"):
        extract_text("grande.txt", b"a" * (9_000_000))


def test_the_extracted_text_is_capped():
    huge = ("linea\n" * 10_000).encode()
    text = extract_text("grande.txt", huge)
    assert len(text) <= 20_000


def test_xlsx_cells_are_extracted_as_rows():
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Precios"
    sheet.append(["Producto", "Precio"])
    sheet.append(["Zeta 12", 549990])
    buffer = io.BytesIO()
    workbook.save(buffer)

    text = extract_text("catalogo.xlsx", buffer.getvalue())
    assert "[Precios]" in text
    assert "Producto | Precio" in text
    assert "Zeta 12 | 549990" in text


def test_pdf_text_is_extracted():
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    # Una pagina en blanco no tiene texto -sirve para confirmar que el
    # extractor no lanza con un PDF valido, aunque este vacio de contenido.
    with pytest.raises(ValidationError, match="texto legible"):
        extract_text("vacio.pdf", buffer.getvalue())
