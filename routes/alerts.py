from flask import Blueprint
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from database import db
from models import Company, Product, Warehouse, Inventory, InventoryHistory, Supplier, ProductSupplier

alerts_bp = Blueprint("alerts", __name__)

@alerts_bp.route("/<int:company_id>/alerts/low-stock", methods=["GET"])
def get_low_stock_alerts(company_id):
    company = Company.query.get(company_id)
    if not company:
        return {"error": "Company not found"}, 404

    thirty_days_ago = datetime.now() - timedelta(days=30)

    low_stock_query = db.session.query(
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.sku,
        Product.low_stock_threshold.label("threshold"),
        Warehouse.id.label("warehouse_id"),
        Warehouse.name.label("warehouse_name"),
        Inventory.quantity.label("current_stock"),
        Supplier.id.label("supplier_id"),
        Supplier.name.label("supplier_name"),
        Supplier.contact_email,
        func.avg(InventoryHistory.quantity_change).label("avg_daily_sales")
    ).join(Inventory, Product.id == Inventory.product_id)\
     .join(Warehouse, Inventory.warehouse_id == Warehouse.id)\
     .join(ProductSupplier, Product.id == ProductSupplier.product_id)\
     .join(Supplier, ProductSupplier.supplier_id == Supplier.id)\
     .join(InventoryHistory, and_(
         InventoryHistory.product_id == Product.id,
         InventoryHistory.change_type == "SALE",
         InventoryHistory.changed_at >= thirty_days_ago
     ))\
     .filter(
         Warehouse.company_id == company_id,
         Inventory.quantity <= Product.low_stock_threshold
     ).group_by(Product.id, Warehouse.id, Supplier.id).all()

    alerts = []
    for item in low_stock_query:
        days_until_stockout = None
        if item.avg_daily_sales and item.avg_daily_sales > 0:
            days_until_stockout = int(item.current_stock / abs(item.avg_daily_sales))

        alerts.append({
            "product_id": item.product_id,
            "product_name": item.product_name,
            "sku": item.sku,
            "warehouse_id": item.warehouse_id,
            "warehouse_name": item.warehouse_name,
            "current_stock": item.current_stock,
            "threshold": item.threshold,
            "days_until_stockout": days_until_stockout,
            "supplier": {
                "id": item.supplier_id,
                "name": item.supplier_name,
                "contact_email": item.contact_email
            }
        })

    alerts.sort(key=lambda x: x["days_until_stockout"] or 999)
    return {"alerts": alerts, "total_alerts": len(alerts)}
