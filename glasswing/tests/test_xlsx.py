import io

from glasswing_adapters.runtime import LocalPdfParser, looks_like_document
from openpyxl import Workbook


def test_xlsx_sheet_is_extracted_as_text():
    book = Workbook()
    sheet = book.active
    sheet.title = "Discounts"
    sheet.append(["Publisher", "Discount"])
    sheet.append(["Adobe CLP", 0.06])
    sheet.append([None, None])
    buffer = io.BytesIO()
    book.save(buffer)
    payload = buffer.getvalue()

    assert looks_like_document(payload, "Adobe-Price-List.xlsx")
    text = LocalPdfParser().extract_text(payload, "Adobe-Price-List.xlsx")
    assert "Sheet: Discounts" in text
    assert "Publisher\tDiscount" in text
    assert "Adobe CLP\t0.06" in text
    assert text.count("\n\n") == 0 or "None" not in text
