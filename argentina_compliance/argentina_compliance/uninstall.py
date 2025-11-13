import frappe

TEMPLATES_TO_DELETE = {
    "Sales Taxes and Charges Template": [
        "Standard Sales VAT%",
    ],
    "Purchase Taxes and Charges Template": [
        "Standard Purchase VAT%",
    ],
}


def before_uninstall():
    """Remove the tax templates created during install."""
    frappe.logger().info("🧹 Starting cleanup of tax templates before uninstall...")

    for doctype, titles in TEMPLATES_TO_DELETE.items():
        for title in titles:
            delete_templates_by_title(doctype, title)

    frappe.db.commit()
    frappe.logger().info("✅ Cleanup completed successfully.")


def delete_templates_by_title(doctype: str, title: str) -> None:
    """Delete all documents of `doctype` that match the given `title`."""
    names = frappe.get_all(doctype, filters={"title": title}, pluck="name")

    if not names:
        frappe.logger().info(f"⚠️ No {doctype} found with title '{title}'")
        return

    for name in names:
        try:
            frappe.delete_doc(
                doctype,
                name,
                ignore_permissions=True,
                ignore_missing=True,
                force=True,
            )
            frappe.logger().info(f"🗑️ Deleted {doctype}: {name}")
        except Exception as e:
            frappe.log_error(
                title=f"❌ Failed to delete {doctype}",
                message=f"Name: {name}\nError: {str(e)}\n\n{frappe.get_traceback()}",
            )
            frappe.logger().error(f"Failed to delete {doctype}: {name} ({e})")

