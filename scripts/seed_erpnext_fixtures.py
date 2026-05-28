from __future__ import annotations

import frappe


SITE = "frontend"
SITES_PATH = "/home/frappe/frappe-bench/sites"
COMPANY = "NExUI Benchmark Lab"

CUSTOMER_NAME = "NExUI Test Customer"
ITEM_CODE = "NEXUI-ITEM-001"
SUPPLIER_NAME = "NExUI Test Supplier"
ADDRESS_TITLE = "NExUI Test Customer Billing"
CONTACT_EMAIL = "customer@example.test"


def save_doc(doc: frappe.model.document.Document) -> None:
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)


def ensure_customer() -> None:
    existing = frappe.db.exists("Customer", CUSTOMER_NAME)
    doc = frappe.get_doc("Customer", existing) if existing else frappe.new_doc("Customer")
    doc.customer_name = CUSTOMER_NAME
    doc.customer_type = "Company"
    doc.customer_group = "Commercial"
    doc.territory = "United States"
    save_doc(doc)


def ensure_item() -> None:
    existing = frappe.db.exists("Item", ITEM_CODE)
    doc = frappe.get_doc("Item", existing) if existing else frappe.new_doc("Item")
    doc.item_code = ITEM_CODE
    doc.item_name = "NExUI Test Item"
    doc.item_group = "Products"
    doc.stock_uom = "Nos"
    save_doc(doc)


def ensure_supplier() -> None:
    existing = frappe.db.exists("Supplier", SUPPLIER_NAME)
    doc = frappe.get_doc("Supplier", existing) if existing else frappe.new_doc("Supplier")
    doc.supplier_name = SUPPLIER_NAME
    doc.supplier_type = "Company"
    save_doc(doc)


def reset_links(doc: frappe.model.document.Document) -> None:
    doc.set(
        "links",
        [
            {
                "link_doctype": "Customer",
                "link_name": CUSTOMER_NAME,
                "link_title": CUSTOMER_NAME,
            }
        ],
    )


def ensure_address() -> None:
    existing = frappe.db.get_value(
        "Address",
        {"address_title": ADDRESS_TITLE, "address_type": "Billing"},
        "name",
    )
    doc = frappe.get_doc("Address", existing) if existing else frappe.new_doc("Address")
    doc.address_title = ADDRESS_TITLE
    doc.address_type = "Billing"
    doc.address_line1 = "100 Benchmark Way"
    doc.city = "Bismarck"
    doc.country = "United States"
    doc.email_id = CONTACT_EMAIL
    doc.phone = "7015550100"
    reset_links(doc)
    save_doc(doc)


def ensure_contact() -> None:
    existing = frappe.db.get_value("Contact", {"email_id": CONTACT_EMAIL}, "name")
    if not existing:
        existing = frappe.db.get_value(
            "Contact",
            {"first_name": "NExUI", "last_name": "Automation"},
            "name",
        )
    doc = frappe.get_doc("Contact", existing) if existing else frappe.new_doc("Contact")
    doc.first_name = "NExUI"
    doc.last_name = "Automation"
    doc.email_id = CONTACT_EMAIL
    doc.phone = "7015550100"
    doc.mobile_no = "7015550100"
    doc.company_name = COMPANY
    doc.is_primary_contact = 1
    doc.is_billing_contact = 1
    reset_links(doc)
    doc.set(
        "email_ids",
        [
            {
                "email_id": CONTACT_EMAIL,
                "is_primary": 1,
            }
        ],
    )
    doc.set(
        "phone_nos",
        [
            {
                "phone": "7015550100",
                "is_primary_phone": 1,
                "is_primary_mobile_no": 1,
            }
        ],
    )
    save_doc(doc)


def main() -> None:
    frappe.init(site=SITE, sites_path=SITES_PATH)
    frappe.connect()
    try:
        ensure_customer()
        ensure_item()
        ensure_supplier()
        ensure_address()
        ensure_contact()
        frappe.db.commit()
        print(
            "Seeded ERPNext fixtures:",
            {
                "customer": CUSTOMER_NAME,
                "item": ITEM_CODE,
                "supplier": SUPPLIER_NAME,
                "address": ADDRESS_TITLE,
                "contact": CONTACT_EMAIL,
            },
        )
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()
