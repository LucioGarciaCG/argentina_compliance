# Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
import traceback
from frappe.model.document import Document


class AFIPSetting(Document):
	pass


def log_electronic_invoice_error(doctype=None, module=None, title=None, message=None, exception=None, status=None):
    try:
        frappe.get_doc({
            "doctype": "Electronic Invoice Log",
            "reference_doctype": doctype,
            "reference_module": module,
            "status": status,
            "title": title,
            "error": str(exception) if exception else "",
            "path": traceback.format_exc() if exception else "",
            "message": message
        }).insert(ignore_permissions=True)
    except Exception as log_error:
        frappe.log_error(f"Failed to log to Electronic Invoice Log: {str(log_error)}")
