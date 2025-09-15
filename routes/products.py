from flask import Blueprint, request
from database import db
from models import Product, Inventory, Warehouse

products_bp = Blueprint("products", __name__)

@products_bp.route("", methods=["POST"])
def create_product():
    data = request.json
    required_fields = ["name", "sku", "price", "warehouse_id", "initial_quantity"]
    if not all(field in data for field in required_fields):
        return {"error": "Missing required info"}, 400

    try:
        price = float(data["price"])
        quantity = int(data["initial_quantity"])
        if price <= 0:
            return {"error": "Price must be > 0"}, 400
        if quantity < 0:
            return {"error": "Quantity cannot be negative"}, 400
    except ValueError:
        return {"error": "Price and quantity must be numbers"}, 400

    # Check if warehouse exists
    if not Warehouse.query.get(data["warehouse_id"]):
        return {"error": f"Warehouse with id {data['warehouse_id']} not found"}, 404

    if Product.query.filter_by(sku=data["sku"]).first():
        return {"error": f"SKU '{data['sku']}' already exists"}, 409

    try:
        product = Product(name=data["name"], sku=data["sku"].upper(), price=price)
        db.session.add(product)
        db.session.flush()

        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data["warehouse_id"],
            quantity=quantity,
        )
        db.session.add(inventory)
        db.session.commit()

        return {"message": "Product created", "product_id": product.id}, 201
    except Exception:
        db.session.rollback()
        return {"error": "Something went wrong"}, 500
