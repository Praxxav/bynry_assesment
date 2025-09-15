from flask import Flask
from config import Config
from database import db
from sqlalchemy import event


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    # Enforce foreign key constraints for SQLite
    if "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]:
        def _fk_pragma_on_connect(dbapi_con, con_record):
            dbapi_con.execute("PRAGMA foreign_keys=ON")

        with app.app_context():
            event.listen(db.engine, "connect", _fk_pragma_on_connect)

    # Register blueprints
    from routes.products import products_bp
    from routes.alerts import alerts_bp
    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(alerts_bp, url_prefix="/api/companies")

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()

        # Seed initial data if the database is empty
        from models import Company, Warehouse
        if not Company.query.first():
            print("Database is empty. Seeding initial data...")
            company = Company(id=1, name="Default Company")
            warehouse = Warehouse(id=1, name="Main Warehouse", company_id=1)
            db.session.add(company)
            db.session.add(warehouse)
            db.session.commit()
    app.run(debug=True)
