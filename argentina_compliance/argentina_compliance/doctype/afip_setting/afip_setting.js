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
       frm.doc.credentials.forEach(row => {

    // 1) Current bench time in UTC
            let now_utc = new Date(frappe.datetime.now_datetime(true) + "Z");
            console.log("NOW UTC:", now_utc.toISOString());

            // If no expiry time
            if (!row.expiration_time) {
                row.status = "";
                return;
            }

            // 2) Clean the AFIP timestamp
            let exp_str = row.expiration_time
                .replace(" UTC", "")
                .replace(/\.\d+$/, "");

            // 3) Parse expiration time as **Argentina Time (UTC-3)**
            // Force offset: -03:00
            let exp_art = new Date(exp_str.replace(" ", "T") + "-03:00");

            if (isNaN(exp_art.getTime())) {
                console.warn("Invalid expiration_time:", row.expiration_time);
                row.status = "Invalid Format";
                return;
            }

            // Convert ART → UTC automatically through JS
            let exp_utc = new Date(exp_art.toISOString());

            console.log("EXP ART:", exp_art.toString());
            console.log("EXP UTC:", exp_utc.toISOString());

            // 4) Compare in UTC
            row.status = now_utc > exp_utc ? "Invalid" : "Valid";

});

frm.refresh_field("credentials");

    }
});


// ffrappe.ui.form.on("AFIP Setting", {
//     refresh: function(frm) {
        
//     }
// });


