# Seed Notes

Current disposable demo seed:

Site:
- default `pwd.yml` demo site created by `create-site`

Administrator account:
- username: `Administrator`
- password: `admin`

Current authoring assumptions:
- login is embedded in every recipe
- desk, item list, customer list, new customer form, and new sales order form should be reachable after login
- the reseed path completes the first-run setup wizard automatically with:
  - organization: `NExUI Benchmark Lab`
  - abbreviation: `NBL`

Deterministic fixtures created by `./scripts/reseed_erpnext.sh`:
- customer:
  - `customer_name`: `NExUI Test Customer`
  - `customer_type`: `Company`
  - `customer_group`: `Commercial`
  - `territory`: `United States`
- item:
  - `item_code`: `NEXUI-ITEM-001`
  - `item_name`: `NExUI Test Item`
  - `item_group`: `Products`
  - `stock_uom`: `Nos`
- supplier:
  - `supplier_name`: `NExUI Test Supplier`
  - `supplier_type`: `Company`
- address:
  - `address_title`: `NExUI Test Customer Billing`
  - `address_type`: `Billing`
  - `address_line1`: `100 Benchmark Way`
  - `city`: `Bismarck`
  - `country`: `United States`
- contact:
  - `first_name`: `NExUI`
  - `last_name`: `Automation`
  - `email_id`: `customer@example.test`
  - `phone`: `7015550100`
