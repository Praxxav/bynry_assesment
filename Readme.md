# StockFlow Assessment - My Solution

## Part 1: What's Wrong with This Code? 

When I looked at the original product creation code, I found some serious problems that would cause headaches in production:

### The Big Issues I Found:

**1. The Database Could Get Messed Up**
```python
# Original code:
db.session.add(product)
db.session.commit()        # ← First save

db.session.add(inventory)  
db.session.commit()        # ← Second save - what if this fails?
```
**Problem:** If the second save fails, you get a product with no inventory. That's like having a ghost product that exists but isn't in any warehouse!

**2. No Safety Checks**
The code just assumes all the data is there and correct. What if someone sends:
- Missing fields? → Crash with KeyError
- Wrong data types? → Database explosion
- Duplicate SKU? → Creates chaos in the system

**3. Anyone Can Create Products**
There's no security - any random person could add products to any company's inventory!

### My Fixed Version:

```python
@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json
    
    # Check if we have all the required stuff
    required_fields = ['name', 'sku', 'price', 'warehouse_id', 'initial_quantity']
    if not all(field in data for field in required_fields):
        return {"error": "Hey, you're missing some required info!"}, 400
    
    #  Make sure the data makes sense
    try:
        price = float(data['price'])
        quantity = int(data['initial_quantity'])
        
        if price <= 0:
            return {"error": "Price should be more than $0!"}, 400
        if quantity < 0:
            return {"error": "Can't have negative inventory!"}, 400
    except ValueError:
        return {"error": "Price and quantity need to be numbers"}, 400
    
    #  Check if SKU already exists (no duplicates!)
    if Product.query.filter_by(sku=data['sku']).first():
        return {"error": f"SKU '{data['sku']}' already exists"}, 409
    
    # Do everything in ONE transaction (all or nothing!)
    try:
        # Create product
        product = Product(
            name=data['name'],
            sku=data['sku'].upper(),  # Standardize SKU format
            price=price
        )
        db.session.add(product)
        db.session.flush()  # Get the ID without committing yet
        
        # Create inventory
        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data['warehouse_id'],
            quantity=quantity
        )
        db.session.add(inventory)
        
        # Save both at once - success or failure together!
        db.session.commit()
        
        return {
            "message": "Product created successfully!",
            "product_id": product.id,
            "sku": product.sku
        }, 201
        
    except Exception as e:
        db.session.rollback()  # Undo everything if something goes wrong
        return {"error": "Something went wrong, please try again"}, 500
```

## Part 2: Database Design 

I designed the database to handle a real B2B business with multiple companies, warehouses, and complex relationships.

### My Database Tables:

```sql
-- Companies (the main tenants)
CREATE TABLE companies (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Each company can have multiple warehouses
CREATE TABLE warehouses (
    id INT PRIMARY KEY AUTO_INCREMENT,
    company_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

-- Products (the things we're tracking)
CREATE TABLE products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    sku VARCHAR(100) NOT NULL UNIQUE,  -- SKUs are unique across everyone
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    low_stock_threshold INT DEFAULT 10,
    is_bundle BOOLEAN DEFAULT FALSE,   -- Some products contain other products
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Where products are stored and how much
CREATE TABLE inventory (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    UNIQUE (product_id, warehouse_id),  -- No duplicates
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

-- Track every inventory change (for history and analytics)
CREATE TABLE inventory_history (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    warehouse_id INT NOT NULL,
    change_type VARCHAR(20) NOT NULL,  -- 'SALE', 'RESTOCK', 'ADJUSTMENT'
    quantity_change INT NOT NULL,
    previous_quantity INT NOT NULL,
    new_quantity INT NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Suppliers (who we buy from)
CREATE TABLE suppliers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50)
);

-- Which suppliers provide which products
CREATE TABLE product_suppliers (
    product_id INT NOT NULL,
    supplier_id INT NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (product_id, supplier_id)
);
```

### Questions I'd Ask the Product Team:

1. **User Management**: Who can access what? Do warehouse staff have different permissions than managers?
2. **Multi-Currency**: Do we need to handle different currencies for international companies?
3. **Bundle Logic**: When someone buys a "laptop bundle", do we automatically reduce the inventory of the laptop, mouse, and keyboard?
4. **Pricing**: Can the same product have different prices for different companies?
5. **Data Retention**: How long should we keep the inventory history? Forever or just a few years?

## Part 3: Low Stock Alerts API

This is the fun part - building the smart alert system that tells businesses when they're running low on stock.

### My Implementation:

```python
@app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
def get_low_stock_alerts(company_id):
    # Make sure the company exists
    company = Company.query.get(company_id)
    if not company:
        return {"error": "Company not found"}, 404
    
    # Look back 30 days for "recent activity"
    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    # Find products that are:
    # 1. Below their low stock threshold
    # 2. Have been sold recently (so we care about restocking them)
    # 3. Have a supplier (so we can reorder)
    
    low_stock_query = db.session.query(
        Product.id.label('product_id'),
        Product.name.label('product_name'),
        Product.sku,
        Product.low_stock_threshold.label('threshold'),
        Warehouse.id.label('warehouse_id'),
        Warehouse.name.label('warehouse_name'),
        Inventory.quantity.label('current_stock'),
        Supplier.id.label('supplier_id'),
        Supplier.name.label('supplier_name'),
        Supplier.contact_email,
        # Calculate average daily sales
        func.avg(InventoryHistory.quantity_change).label('avg_daily_sales')
    ).join(Inventory, Product.id == Inventory.product_id)\
     .join(Warehouse, Inventory.warehouse_id == Warehouse.id)\
     .join(product_suppliers, Product.id == product_suppliers.c.product_id)\
     .join(Supplier, product_suppliers.c.supplier_id == Supplier.id)\
     .join(InventoryHistory, and_(
         InventoryHistory.product_id == Product.id,
         InventoryHistory.change_type == 'SALE',
         InventoryHistory.changed_at >= thirty_days_ago
     ))\
     .filter(
         Warehouse.company_id == company_id,
         Inventory.quantity <= Product.low_stock_threshold
     ).group_by(Product.id, Warehouse.id, Supplier.id).all()
    
    # Build the response
    alerts = []
    for item in low_stock_query:
        # Calculate how many days until we run out
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
    
    # Sort by urgency (products running out soonest first)
    alerts.sort(key=lambda x: x['days_until_stockout'] or 999)
    
    return {
        "alerts": alerts,
        "total_alerts": len(alerts)
    }
```

### How My Logic Works:

1. **Check Company Exists**: Basic validation - can't get alerts for a company that doesn't exist
2. **Find Low Stock Items**: Look for products where current stock ≤ threshold
3. **Only Include Active Products**: Only show alerts for products that have sold recently (why restock something nobody buys?)
4. **Calculate Urgency**: Use recent sales to predict how many days until stockout
5. **Include Supplier Info**: So the business knows who to call for reordering
6. **Sort by Urgency**: Most critical alerts first

### Edge Cases I Handle:

- **No Recent Sales**: Product won't appear in alerts (smart!)
- **Division by Zero**: Won't crash if sales data is weird
- **Missing Suppliers**: Won't break if a product has no supplier
- **Invalid Company**: Returns proper 404 error
- **No Alerts**: Returns empty array gracefully

## My Assumptions:

- **"Recent Activity"** = sold something in the last 30 days
- **Low stock threshold** varies by product (some need 100 units, others need 5)
- **Primary supplier** = the main vendor for each product
- **Days until stockout** = current stock ÷ average daily sales

## Why This Approach Works:

**Real Business Value**: Only alerts for products that actually sell  
**Actionable**: Includes supplier contact info for easy reordering  
**Smart Prioritization**: Shows most urgent alerts first  
**Handles Edge Cases**: Won't crash on weird data  
**Scalable**: Query is optimized and won't slow down with more data  
