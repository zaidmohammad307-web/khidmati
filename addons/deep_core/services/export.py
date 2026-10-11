import base64
import io

import xlsxwriter


def export_xlsx(records, filename, headers, rows):
    """Formula-safe XLSX export through an access-controlled native attachment."""
    records.check_access("read")
    output = io.BytesIO()
    book = xlsxwriter.Workbook(
        output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}
    )
    sheet = book.add_worksheet("Report")
    style = book.add_format({"bold": True, "bg_color": "#DCEBE5"})
    sheet.write_row(0, 0, headers, style)
    for index, row in enumerate(rows, 1):
        sheet.write_row(index, 0, row)
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, len(rows), len(headers) - 1)
    sheet.set_column(0, len(headers) - 1, 23)
    book.close()
    attachment = records.env["ir.attachment"].create(
        {
            "name": filename,
            "type": "binary",
            "datas": base64.b64encode(output.getvalue()),
            "res_model": records._name,
            "res_id": records[:1].id or 0,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    )
    return {
        "type": "ir.actions.act_url",
        "url": f"/web/content/{attachment.id}?download=true",
        "target": "self",
    }
