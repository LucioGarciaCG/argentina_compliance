frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        if (!frm.is_new() && !frm.doc.docstatus) {  // Added check for docstatus
            frm.add_custom_button(__('Generate E-Invoice'), function() {
                // Action for the button
                frappe.call({
                    method: 'argentina_compliance.argentina_compliance.doc_events.sales_invoice.generate_invoice',
                    args: {
                        salesInvoice: frm.doc.name
                    },
                    callback: function(r) {
                        if(r.message) {
                            frappe.msgprint(r.message);
                        }
                    }
                });
            });
        }
    }
});