# WeDrink SaaS Architecture & Core Logic

This document explains the core technical decisions, multi-tenant architecture, and complex calculations powering the WeDrink SaaS platform.

## 1. Multi-Tenant Architecture (Micro SaaS)

The platform is designed to serve multiple franchise locations (companies) from a single database and bot instance.

### Company Structure
- **Company 1 (Platform Core)**: This is the master company. The Superadmins belong here. 
  - All "Base Products" are managed here.
  - When a new franchisee (company) is created, the system automatically runs `duplicate_company_products` to copy all active products from Company 1 to the new company. This ensures instant onboarding.
- **Child Companies**: Franchisee locations. They have their own isolated `stock`, `supplies`, `orders`, `staff`, and copy of `products`.

### Global Products & Menu Freeze
- Products marked with `is_global = TRUE` are locked to the Platform Core.
- Franchisee admins cannot rename, delete, or change the unit/packaging metrics of global products. They can only toggle visibility (`is_active`).
- Superadmins can use `/api/superadmin/products` to globally inject a new product into all existing companies seamlessly.

### Subscriptions & Access Control
- Each company has a `subscription_end_date` and a `status` (`trial`, `active`, `expired`).
- `scheduler.py` runs a daily cron job (`check_expired_subscriptions`) at 00:05 to downgrade expired companies.
- An interceptor in `webapp/server.py` (`check_subscription` middleware) blocks access to the dashboard for expired companies, redirecting them to a Kaspi payment instruction page (`/expired`).
- The Telegram bot handles subscription renewals via the Kaspi Concierge flow, forwarding requests to the Superadmin chat for approval.

### Notifications
- Reminders and orders are purely DM-based (no longer reliant on a global `.env` group chat).
- Notifications are routed precisely using `get_admins_for_company` and `get_staff_for_company`, ensuring franchisees only see alerts for their own store.

## 2. Inventory & Consumption Calculations

The accuracy of the "Smart Order" system relies on precise mathematical formulas handling edge cases, missing data, and bulk packaging.

### Physical Stock vs. Packaging
- Products are received in bulk (e.g., Boxes), but inventory is tracked in base units (Packages/Pieces).
- Formula for receiving supplies: `Added Quantity = boxes * units_per_box`.
- Weight and Cost are similarly scaled to accurately reflect Supplier Debts and inventory valuation.

### Complex Daily Consumption (`calculate_consumption`)
To suggest accurate 7/10/14 day orders, the system must calculate the true daily burn rate of a product. A simple `(Start - End) / Days` fails when ingredients go out of stock for days at a time.

**The Filter Logic:**
The calculation iterates through chronological historical stock records, forming "gaps" (periods between two inventory checks).
1. `consumed_qty = Initial Qty + Deliveries (supplies) - Final Qty`
2. **Zero-Stock Anomaly Filter**: If a product's quantity was `0` at the start of a gap AND `0` at the end of a gap, it means the product was physically unavailable. These days are **stripped** from the `actual_days` denominator. This prevents out-of-stock periods from artificially deflating the average consumption rate.
3. **Negative Anomaly Filter**: If `consumed_qty < 0` (e.g., staff forgot to log a supply or typo'd a massive inventory recount), the gap is flagged as an anomaly. The days and the bogus quantity are skipped entirely, protecting the integrity of the math.

### Order Generation (`calculate_order_for_company`)
The Smart Order calculation uses a tiered look-back window (defaulting to max 90 days, but prioritizing recent dense periods).
- It applies a `safety_factor = 1.2` (20% buffer) to the calculated daily average.
- It calculates `days_remaining` using explicit physical stock.
- It calculates `total_days_remaining` including products still "in transit" (pending orders/supplies).
- The Dashboard UI triggers warnings based strictly on `total_days_remaining` dipping below thresholds.

## 3. History & State Mutations
- **Historical Editing**: Superadmins can edit historical stock entries via the History page. This performs a targeted `UPDATE/INSERT` (Upsert) on `stock` rows mapped strictly to a specific past `date`, gracefully adjusting past inventory without triggering overlapping duplication.
- **Debt Handling**: Unreceived items in a supply order can be flagged as "Supplier Debt". If delivered later, resolving the debt increments the stock and updates supply metrics accurately factoring in `units_per_box`.
