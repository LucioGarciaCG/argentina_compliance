// Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
// For license information, please see license.txt

// frappe.ui.form.on("AFIP Setting", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("AFIP Setting", {
    refresh(frm) {
        frappe.model.with_doctype("Sales Invoice", function() {
            const si_meta = frappe.get_meta("Sales Invoice");
            const si_series_field = si_meta.fields.find(f => f.fieldname === "naming_series");

            if (si_series_field && si_series_field.options) {
                const series_list = si_series_field.options.split("\n");

                // Set options in child table field 'naming_series'
                frm.fields_dict.sales_invoice_naming_series.grid.update_docfield_property(
                    "naming_series",
                    "options",
                    series_list
                );
            }
        });
    }
});

