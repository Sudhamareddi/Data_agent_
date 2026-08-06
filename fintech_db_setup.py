"""
A payments/fintech-flavored 11-table schema, deliberately shaped like
the kind of messy, real-world question a payments support or ops team
actually asks: "why did this transaction fail," "which merchant has
unsettled refunds," "which customers have open disputes."

Same agent, same tools, same safeguards as the e-commerce example --
only the domain changes, which is the point: the agent doesn't know
this schema in advance either.

Run once: python fintech_db_setup.py
"""
import sqlite3
import os
from sqlalchemy import create_engine

DB_PATH = os.path.join(os.path.dirname(__file__), "fintech.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id INTEGER PRIMARY KEY,
    business_name TEXT NOT NULL,
    business_type TEXT,
    onboarded_date TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    signup_date TEXT
);

CREATE TABLE IF NOT EXISTS payment_methods (
    method_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    method_type TEXT,
    last4 TEXT,
    provider TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id INTEGER PRIMARY KEY,
    merchant_id INTEGER,
    customer_id INTEGER,
    method_id INTEGER,
    amount REAL,
    currency TEXT,
    status TEXT,
    created_at TEXT,
    FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (method_id) REFERENCES payment_methods(method_id)
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id INTEGER PRIMARY KEY,
    transaction_id INTEGER,
    amount REAL,
    reason TEXT,
    status TEXT,
    created_at TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id INTEGER PRIMARY KEY,
    transaction_id INTEGER,
    reason TEXT,
    status TEXT,
    opened_at TEXT,
    resolved_at TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id INTEGER PRIMARY KEY,
    merchant_id INTEGER,
    amount REAL,
    settlement_date TEXT,
    status TEXT,
    FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    merchant_id INTEGER,
    plan_name TEXT,
    status TEXT,
    start_date TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id)
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id INTEGER PRIMARY KEY,
    subscription_id INTEGER,
    amount REAL,
    due_date TEXT,
    paid_date TEXT,
    status TEXT,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(subscription_id)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    webhook_id INTEGER PRIMARY KEY,
    transaction_id INTEGER,
    event_type TEXT,
    sent_at TEXT,
    delivery_status TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    transaction_id INTEGER,
    issue_type TEXT,
    status TEXT,
    created_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);
"""

SEED = """
INSERT INTO merchants VALUES
 (1,'Bloom Retail','E-commerce','2024-01-05'),
 (2,'Nimbus SaaS','Software/Subscription','2024-02-10');

INSERT INTO customers VALUES
 (1,'Asha Rao','asha@example.com','2024-01-10'),
 (2,'Vikram Shah','vikram@example.com','2024-02-15'),
 (3,'Priya Nair','priya@example.com','2024-03-01');

INSERT INTO payment_methods VALUES
 (1,1,'card','4242','Visa'),
 (2,2,'upi','','GPay'),
 (3,3,'card','1881','Mastercard');

INSERT INTO transactions VALUES
 (1,1,1,1,1499.0,'INR','success','2024-04-01 10:15:00'),
 (2,1,2,2,899.0,'INR','failed','2024-04-02 11:00:00'),
 (3,2,3,3,2999.0,'INR','success','2024-04-03 09:30:00'),
 (4,2,1,1,2999.0,'INR','success','2024-05-03 09:30:00'),
 (5,1,3,3,499.0,'INR','failed','2024-04-05 14:00:00');

INSERT INTO refunds VALUES
 (1,1,1499.0,'customer requested','processed','2024-04-04 12:00:00');

INSERT INTO disputes VALUES
 (1,3,'unrecognized charge','open','2024-04-10 08:00:00',NULL);

INSERT INTO settlements VALUES
 (1,1,3000.0,'2024-04-06','settled'),
 (2,2,5998.0,'2024-04-09','pending');

INSERT INTO subscriptions VALUES
 (1,1,2,'Pro Monthly','active','2024-04-03'),
 (2,3,2,'Starter Monthly','cancelled','2024-03-01');

INSERT INTO invoices VALUES
 (1,1,2999.0,'2024-05-03','2024-05-03','paid'),
 (2,2,999.0,'2024-04-01',NULL,'overdue');

INSERT INTO webhook_events VALUES
 (1,2,'payment.failed','2024-04-02 11:00:05','delivered'),
 (2,1,'payment.captured','2024-04-01 10:15:05','delivered'),
 (3,5,'payment.failed','2024-04-05 14:00:05','failed_delivery');

INSERT INTO support_tickets VALUES
 (1,2,2,'failed_payment','open','2024-04-02 11:30:00'),
 (2,3,3,'unrecognized_charge','open','2024-04-10 08:15:00');
"""


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.executescript(SEED)
    conn.commit()
    conn.close()
    print(f"Fintech DB built at {DB_PATH}")


def get_fintech_engine():
    if not os.path.exists(DB_PATH):
        build()
    return create_engine(f"sqlite:///{DB_PATH}")


if __name__ == "__main__":
    build()
