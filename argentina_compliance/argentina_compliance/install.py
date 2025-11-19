import frappe
from erpnext.setup.setup_wizard.operations.taxes_setup import make_taxes_and_charges_template


def after_install():
    """Run automatically when the app is installed."""
    companies = frappe.get_all("Company", pluck="name")

    for company in companies:
        print(f"\n Creating tax templates for company: {company}")
        result = create_tax_templates(company)
        print(f" Completed for {company}: {result}\n")
        frappe.db.commit()  # Commit after each company


def create_tax_templates(company):
    """Create Sales and Purchase Taxes and Charges Templates for the company."""
    
    created_templates = []

    # Skip if already exists
    if frappe.db.exists("Sales Taxes and Charges Template", {"company": company, "title": "Standard Sales VAT%"}):
        print(f" Sales VAT Template already exists for {company}")
    else:
        sales_template = {
            "title": "Standard Sales VAT%",
            "is_default": 1,
            "taxes": [
                {
                    "account_head": {
                        "account_name": "004.110 - VAT - CDTAP",
                        "tax_rate": 21,
                        "account_type": "Tax",
                        "company": company,
                        "parent_account": "Duties and Taxes",
                        "root_type": "Liability",
                        "report_type": "Balance Sheet",
                    },
                    "description": "VAT",
                    "rate": 21,
                    "charge_type": "On Net Total",
                    "category": "Total",
                }
            ],
        }

        make_taxes_and_charges_template(
            company,
            "Sales Taxes and Charges Template",
            sales_template,
        )
        created_templates.append("Sales VAT Template")

    # Purchase VAT 21%
    if frappe.db.exists("Purchase Taxes and Charges Template", {"company": company, "title": "Standard Purchase VAT%"}):
        print(f"Purchase VAT Template already exists for {company}")
    else:
        purchase_template = {
            "title": "Standard Purchase VAT%",
            "is_default": 1,
            "taxes": [
                {
                    "account_head": {
                        "account_name": "004.120 - Input VAT - CDTAP",
                        "tax_rate": 21,
                        "account_type": "Tax",
                    },
                    "description": "Input VAT",
                    "rate": 21,
                    "charge_type": "On Net Total",
                    "category": "Total",
                }
            ],
        }

        make_taxes_and_charges_template(
            company,
            "Purchase Taxes and Charges Template",
            purchase_template,
        )
        created_templates.append("Purchase VAT Template")

    return created_templates or "No new templates created"
