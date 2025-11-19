# Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
import traceback
from frappe.model.document import Document
from argentina_compliance.argentina_compliance.doc_events.afip_token import (
    get_afip_token,
    check_token_validity
)


class AFIPSetting(Document):
    pass
    
    # def before_save(self):
    #     """Generate token only for rows that changed or have expired token"""
    #     old_doc = self.get_doc_before_save()
        
    #     for new_row in self.credentials:
    #         regenerate = False

    #         if not old_doc:
    #             # New document: generate for all rows
    #             regenerate = True
    #         else:
    #             old_row = next((r for r in old_doc.credentials if r.name == new_row.name), None)
    #             if not old_row:
    #                 # New row added
    #                 regenerate = True
    #             else:
    #                 # Compare all fields except system fields
    #                 for field in new_row.meta.fields:
    #                     fieldname = field.fieldname
    #                     if hasattr(new_row, fieldname) and hasattr(old_row, fieldname):
    #                         if getattr(new_row, fieldname) != getattr(old_row, fieldname):
    #                             regenerate = True
    #                             break
    #                 # Also check if token expired
    #                 if not check_token_validity(new_row):
    #                     regenerate = True

    #         if regenerate:
    #             get_afip_token(new_row)

    
    
# class AFIPSetting(Document):

#     def before_save(self):
#         old_doc = self.get_doc_before_save()
#         if not old_doc:
#             return

#         for new_row in self.credentials:
#             old_row = next((r for r in old_doc.credentials if r.name == new_row.name), None)
            
#             if old_row:
#                 # Only check if the CUIT changed
#                 if new_row.cuit != old_row.cuit:
#                     if not check_token_validity(new_row):
#                         get_afip_token(new_row)
#             else:
#                 # For new row, generate token
#                 if not check_token_validity(new_row):
#                     get_afip_token(new_row)


                    
    # def before_save(self):
    #     old_doc = self.get_doc_before_save()
    #     if not old_doc:
    #         # New document - check all rows
    #         for row in self.credentials:
    #             if not check_token_validity(row):
    #                 get_afip_token(row)
    #         return
        
    #     # Check only changed/new rows
    #     for row in self.credentials:
    #         old_row = next((r for r in old_doc.credentials if r.name == row.name), None)
            
    #         # New row or row changed
    #         if not old_row or self._row_changed(old_row, row):
    #             if not check_token_validity(row):
    #                 get_afip_token(row)
    
    # def _row_changed(self, old_row, new_row):
    #     """Check if important fields changed"""
    #     fields_to_check = ["certificate", "private_key", "company", "cuit", "use_sandbox_environment"]
    #     return any(getattr(old_row, f, None) != getattr(new_row, f, None) for f in fields_to_check)



    # class AFIPSetting(Document):

    #     def validate(self):
    #         old_doc = self.get_doc_before_save()

    #         if not old_doc:
    #             return

    #         for new_row in self.credentials:

    #             # Find matching old row
    #             old_row = next((r for r in old_doc.credentials if r.name == new_row.name), None)

    #             # New row added
    #             if not old_row:
    #                 if not check_token_validity(new_row):
    #                     frappe.msgprint(f"Generating token for new row {new_row.idx}")
    #                     get_afip_token(new_row)
    #                 continue

    #             # Fields that matter
    #             fields_to_check = ["certificate", "private_key", "company", "cuit","use_sandbox_environment","check_afip_invoice_number_consistency"]

    #             # Check only these fields
    #             row_changed = any(
    #                 getattr(old_row, f) != getattr(new_row, f)
    #                 for f in fields_to_check
    #             )

    #             if row_changed:
    #                 if not check_token_validity(new_row):
    #                     frappe.msgprint(f"Row changed — generating token for row {new_row.idx}")
    #                     get_afip_token(new_row)
