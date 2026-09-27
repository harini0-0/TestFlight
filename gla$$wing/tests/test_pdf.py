import io

from glasswing_adapters.runtime import LocalPdfParser
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf_with_sentence(sentence: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    page = writer.pages[0]
    page["/Resources"][NameObject("/Font")] = DictionaryObject(
        {
            NameObject("/F1"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({sentence}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_page_text_is_extracted():
    payload = _pdf_with_sentence("Customer discount is 6%")
    text = LocalPdfParser().extract_text(payload, "rate.pdf")
    assert text == "Customer discount is 6%"
    assert not text.startswith("%PDF")


def test_unreadable_pdf_is_not_kept_as_file_source():
    text = LocalPdfParser().extract_text(b"%PDF-1.3 this is not a readable document", "bad.pdf")
    assert text == ""


def test_page_words_stay_and_hidden_glyphs_do_not():
    payload = "Fee is 0.75% of sales.\n\ue001\ue014\ue022\nNotice is sixty (60) days.\n".encode()
    text = LocalPdfParser().extract_text(payload, "terms.txt")
    assert text == "Fee is 0.75% of sales.\nNotice is sixty (60) days."
    assert "\ue001" not in text


def test_pdf_file_syntax_is_not_treated_as_words():
    payload = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    assert LocalPdfParser().extract_text(payload, "notes.txt") == ""
