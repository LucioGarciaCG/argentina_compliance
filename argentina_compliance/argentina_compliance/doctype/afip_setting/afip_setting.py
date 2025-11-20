# Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import json
import frappe
import traceback
from frappe.model.document import Document
from argentina_compliance.argentina_compliance.doc_events.afip_token import (
    get_afip_token,
    check_token_validity
)


class AFIPSetting(Document):
    def validate(self):
        # validate company not set duplicate
        seen = {}
        for row in self.credentials:
            if row.company in seen:
                frappe.throw(
                    f"Duplicate company '{row.company}' found in Row {row.idx} "
                    f"(already used in Row {seen[row.company]})"
                )
            seen[row.company] = row.idx
    
    

@frappe.whitelist()
def create_new_token(row):
    row = json.loads(row) 
    return get_afip_token(row)