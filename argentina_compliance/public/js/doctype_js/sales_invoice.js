frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        if (!frm.is_new() && !frm.doc.docstatus) {  // Added check for docstatus
            const buttonLabel = frm.doc.is_return ? __('Generate Credit Note') : __('Generate E-Invoice');
            
            frm.add_custom_button(__(buttonLabel), function() {
                // Determine which method to call based on is_return
                const method = frm.doc.is_return 
                    ? 'argentina_compliance.argentina_compliance.doc_events.sales_invoice.cancel_invoice'
                    : 'argentina_compliance.argentina_compliance.doc_events.sales_invoice.generate_invoice';

                frappe.call({
                    method: method,
                    args: {
                        salesInvoice: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: frm.doc.is_return ? __('Generating Credit Note...') : __('Generating E-Invoice...'),
                    callback: function(r) {
                        if (r.message) {
                            // Show success message
                            if (r.message.success) {
                                const msg = frm.doc.is_return
                                    ? __(`Credit Note generated successfully with CAE: ${r.message.cae}`)
                                    : __(`Invoice generated successfully with CAE: ${r.message.cae}`);
                                frappe.msgprint({
                                    message: msg,
                                    indicator: 'green',
                                    title: frm.doc.is_return ? __('Credit Note Generated') : __('E-Invoice Generated')
                                });
                            } else {
                                frappe.msgprint(r.message);
                            }
                            // Refresh the form to show updated values
                            frm.refresh();
                        }
                    },
                    error: function(r) {
                        // Show error message
                        frappe.msgprint({
                            message: __('Error occurred while processing. Please check the error log for details.'),
                            indicator: 'red',
                            title: frm.doc.is_return ? __('Credit Note Generation Failed') : __('E-Invoice Generation Failed')
                        });
                    }
                });
            });
        }
    }
});