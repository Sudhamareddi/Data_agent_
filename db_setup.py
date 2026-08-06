"""
Creates a sample 11-table e-commerce SQLite database so the agent has a
realistic, multi-hop relational schema to explore -- mirroring the scale
of the original project (11-table schema, joins across up to 5 tables).

Run once: python db_setup.py
Swap this out for a real Postgres/MySQL connection string in agent_graph.py
when you point this at an actual dataset.
"""
import sqlite3
import os
from sqlalchemy import create_engine

DB_PATH = os.path.join(os.path.dirname(__file__), "sample.db")


def get_example_engine():
    """Engine for the bundled example database (builds it if missing)."""
    if not os.path.exists(DB_PATH):
        build()
    return create_engine(f"sqlite:///{DB_PATH}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    signup_date TEXT,
    region TEXT
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id INTEGER PRIMARY KEY,
    supplier_name TEXT NOT NULL,
    country TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category_name TEXT,
    supplier_id INTEGER,
    unit_price REAL,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
);

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id INTEGER PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    city TEXT
);

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id INTEGER PRIMARY KEY,
    product_id INTEGER,
    warehouse_id INTEGER,
    quantity INTEGER,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    employee_id INTEGER,
    order_date TEXT,
    status TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    product_id INTEGER,
    quantity INTEGER,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    amount REAL,
    payment_method TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    warehouse_id INTEGER,
    ship_date TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY,
    product_id INTEGER,
    customer_id INTEGER,
    rating INTEGER,
    comment TEXT,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
"""

SEED = """
INSERT INTO customers VALUES
 (1,'Asha Rao','asha@example.com','2024-01-10','South'),
 (2,'Vikram Shah','vikram@example.com','2024-02-15','West'),
 (3,'Priya Nair','priya@example.com','2024-03-20','South');

INSERT INTO suppliers VALUES (1,'TechSource','India'),(2,'HomeGoods Ltd','India');

INSERT INTO products VALUES
 (1,'Wireless Mouse','Electronics',1,699.0),
 (2,'Blender','Home & Kitchen',2,1899.0),
 (3,'Novel: The Sea','Books',2,399.0);

INSERT INTO warehouses VALUES (1,'Bengaluru WH','Bengaluru'),(2,'Hyderabad WH','Hyderabad');

INSERT INTO inventory VALUES (1,1,1,120),(2,2,2,45),(3,3,1,300);

INSERT INTO employees VALUES (1,'Ramesh Iyer','Sales Rep'),(2,'Divya Menon','Sales Rep');

INSERT INTO orders VALUES
 (1,1,1,'2024-04-01','Delivered'),
 (2,2,2,'2024-04-03','Shipped'),
 (3,3,1,'2024-04-05','Delivered');

INSERT INTO order_items VALUES
 (1,1,1,2),(2,1,3,1),(3,2,2,1),(4,3,1,1);

INSERT INTO payments VALUES
 (1,1,1797.0,'UPI'),(2,2,1899.0,'Card'),(3,3,699.0,'UPI');

INSERT INTO shipments VALUES
 (1,1,1,'2024-04-02'),(2,2,2,'2024-04-04'),(3,3,1,'2024-04-06');

INSERT INTO reviews VALUES
 (1,1,1,5,'Great mouse'),(2,3,3,4,'Good read'),(3,2,2,3,'Works fine');
"""

def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.executescript(SEED)
    conn.commit()
    conn.close()
    print(f"Sample DB built at {DB_PATH}")

if __name__ == "__main__":
    build()
