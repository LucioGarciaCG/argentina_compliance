// // For child table: Credentials
// frappe.ui.form.on('Credentials', {
//     company: function( cdt, cdn) {
//         console.log("hello")
//         let row = locals[cdt][cdn];
//         if (row.company) {
//             frappe.db.get_value('Company', row.company, 'custom_cuit')
//                 .then(r => {
//                     if (r.message && r.message.custom_cuit) {
//                         frappe.model.set_value(cdt, cdn, 'cuit', r.message.custom_cuit);
//                     }
//                 });
//         } else {
//             frappe.model.set_value(cdt, cdn, 'cuit', '');
//         }
//     },

//     // Also trigger when the row loads (e.g., company auto-set)
//     company_name: function(frm, cdt, cdn) {
//         frappe.ui.form.trigger('Credentials', 'company', frm, cdt, cdn);
//     },

//     // Or you can also handle on form refresh (auto-fill CUIT for all rows)
//     refresh: function(frm) {
//         (frm.doc.credentials || []).forEach(row => {
//             if (row.company && !row.cuit) {
//                 frappe.db.get_value('Company', row.company, 'custom_cuit')
//                     .then(r => {
//                         if (r.message && r.message.custom_cuit) {
//                             frappe.model.set_value(row.doctype, row.name, 'cuit', r.message.custom_cuit);
//                         }
//                     });
//             }
//         });
//     }
// });


// This script would be attached to the 'Sales Invoice' DocType
frappe.ui.form.on("Credentials", {
    company: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        comsole.log("hello")
        if (row.company) {
            frappe.db.get_value("Company", {"name": row.company}, "custom_cuit")
                .then(r => {
                    if (r.message && r.message.custom_cuit) {
                        frappe.model.set_value(cdt, cdn, "cuit", r.message.custom_cuit);
                    } else {
                        frappe.model.set_value(cdt, cdn, "cuit", "");
                    }
                });
        } else {
            frappe.model.set_value(cdt, cdn, "cuit", "");
        }
    }
});

