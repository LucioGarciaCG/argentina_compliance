# Copyright (c) 2025, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
import traceback
from frappe.model.document import Document


class ElectronicInvoiceLog(Document):
    pass


def log_electronic_invoice_response(
    doctype=None,
    module=None,
    title=None,
    message=None,
    exception=None,
    status=None,
    source=None,
):
    try:
        frappe.get_doc(
            {
                "doctype": "Electronic Invoice Log",
                "reference_doctype": doctype,
                "reference_module": module,
                "status": status,
                "source": source,
                "title": title,
                "error": str(exception) if exception else "",
                "message": message,
            }
        ).insert(ignore_permissions=True)
    except Exception as log_error:
        frappe.log_error(f"Failed to log to Electronic Invoice Log: {str(log_error)}")
