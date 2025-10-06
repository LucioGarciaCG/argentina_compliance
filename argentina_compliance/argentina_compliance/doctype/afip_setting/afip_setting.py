# Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
import traceback
from frappe.model.document import Document
from argentina_compliance.argentina_compliance.doc_events.afip_token import (
    get_afip_token,
)


class AFIPSetting(Document):
    def before_save(self):
        try:
            get_afip_token()
        except Exception as e:
            frappe.log_error(
                message=f"Error in updating E-invoice certificate or key : {str(e)}",
                title="AFIP Setting Update Fail",
            )
