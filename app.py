import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_cors import CORS
from functools import wraps
from werkzeug.utils import secure_filename
import uuid
from flask_socketio import SocketIO, emit, join_room
from datetime import timezone
# Import pustaka json
import json
from sqlalchemy import func

# Muat variabel lingkungan dari .env
load_dotenv()

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)

class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(255))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

class TransactionProduct(db.Model):
    __tablename__ = 'transaction_product'
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), primary_key=True)
    quantity = db.Column(db.Integer, nullable=False)
    product = db.relationship("Product")

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(100), nullable=False)
    payment_method = db.Column(db.String(100))
    items_json = db.Column(db.String(1000), nullable=False)
    items = db.relationship("TransactionProduct", cascade="all, delete-orphan")

class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(255), nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    products = db.relationship('Product', backref='category', lazy=True)

# Buat database jika belum ada
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return "Welcome to Kasim Backend API!"

# --- Income Endpoints ---
@app.route('/income/today', methods=['GET'])
def get_today_income():
    today_str = datetime.now().strftime('%Y-%m-%d')
    total_today = db.session.query(func.sum(Transaction.total)).filter(Transaction.date.like(f"{today_str}%")).scalar()
    return jsonify({"total": total_today or 0})

@app.route('/income/monthly', methods=['GET'])
def get_monthly_income():
    month_str = datetime.now().strftime('%Y-%m')
    total_monthly = db.session.query(func.sum(Transaction.total)).filter(Transaction.date.like(f"{month_str}%")).scalar()
    return jsonify({"total": total_monthly or 0})

# --- Product Endpoints ---
@app.route('/products/bestselling', methods=['GET'])
def get_bestselling_products():
    bestselling_products = db.session.query(
        Product,
        func.sum(TransactionProduct.quantity).label('total_quantity')
    ).join(TransactionProduct, Product.id == TransactionProduct.product_id) \
    .group_by(Product.id) \
    .order_by(func.sum(TransactionProduct.quantity).desc()) \
    .limit(5) \
    .all()

    products_list = []
    for product, total_quantity in bestselling_products:
        products_list.append({
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "image": product.image,
            "category_id": product.category_id,
            "total_quantity": total_quantity
        })

    return jsonify(products_list)

@app.route('/products', methods=['GET'])
def get_products():
    category_id = request.args.get('category_id')
    if category_id:
        products = Product.query.filter_by(category_id=category_id).all()
    else:
        products = Product.query.all()
    return jsonify([{"id": p.id, "name": p.name, "price": p.price, "image": p.image, "category_id": p.category_id} for p in products])

@app.route('/products', methods=['POST'])
def add_product():
    data = request.json
    new_product = Product(name=data['name'], price=data['price'], image=data.get('image'), category_id=data.get('category_id'))
    db.session.add(new_product)
    db.session.commit()
    return jsonify({"message": "Product added successfully", "id": new_product.id}), 201

@app.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.json
    product.name = data.get('name', product.name)
    product.price = data.get('price', product.price)
    product.image = data.get('image', product.image)
    product.category_id = data.get('category_id', product.category_id)
    db.session.commit()
    return jsonify({"message": "Product updated successfully"})

@app.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    return jsonify({"message": "Product deleted successfully"})

# --- Image Upload Endpoint ---
@app.route('/products/<int:product_id>/image', methods=['POST'])
def upload_product_image(product_id):
    product = Product.query.get_or_404(product_id)
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file:
        filename = secure_filename(file.filename)
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
        os.makedirs(upload_path, exist_ok=True)
        file.save(os.path.join(upload_path, filename))
        product.image = f'uploads/images/{filename}'
        db.session.commit()
        return jsonify({'message': 'Image uploaded successfully', 'image_path': product.image})

# --- Static File Serving ---
@app.route('/uploads/images/<filename>')
def serve_image(filename):
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'images'), filename)

# --- Category Endpoints ---
@app.route('/categories', methods=['GET'])
def get_categories():
    categories = Category.query.all()
    return jsonify([{"id": c.id, "name": c.name} for c in categories])

@app.route('/categories', methods=['POST'])
def add_category():
    data = request.json
    new_category = Category(name=data['name'])
    db.session.add(new_category)
    db.session.commit()
    return jsonify({"message": "Category added successfully", "id": new_category.id}), 201

@app.route('/categories/<int:category_id>', methods=['PUT'])
def update_category(category_id):
    category = Category.query.get_or_404(category_id)
    data = request.json
    category.name = data.get('name', category.name)
    db.session.commit()
    return jsonify({"message": "Category updated successfully"})

@app.route('/categories/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    return jsonify({"message": "Category deleted successfully"})

# --- Transaction Endpoints ---
@app.route('/transactions', methods=['GET'])
def get_transactions():
    date_str = request.args.get('date')
    query = Transaction.query
    if date_str:
        query = query.filter(Transaction.date.like(f"{date_str}%"))
    # Eagerly load the 'items' and 'product' relationships
    transactions = query.options(db.joinedload(Transaction.items).joinedload(TransactionProduct.product)).order_by(Transaction.date.desc()).all()
    transactions_list = []
    for t in transactions:
        items = []
        for item in t.items:
            # Ensure product exists before accessing its attributes
            if item.product:
                items.append({
                    "product_id": item.product.id,
                    "name": item.product.name,
                    "price": item.product.price,
                    "quantity": item.quantity,
                    "image": item.product.image
                })
            else:
                # Handle case where product might be missing (e.g., deleted)
                items.append({
                    "product_id": None, # Or a placeholder ID
                    "name": "Product Not Found",
                    "price": 0.0,
                    "quantity": item.quantity,
                    "image": None # Or a placeholder image
                })
        transactions_list.append({
            "id": t.id,
            "total": t.total,
            "date": t.date,
            "payment_method": t.payment_method,
            "items": items
        })
    return jsonify(transactions_list)

@app.route('/transactions', methods=['POST'])
def add_transaction():
    data = request.json
    new_transaction = Transaction(
        total=data['total'],
        date=data['date'],
        payment_method=data.get('payment_method'),
        items_json=json.dumps(data['items'])
    )
    for item_data in data['items']:
        product = Product.query.get(item_data['product_id'])
        if product:
            tp = TransactionProduct(
                quantity=item_data['qty']
            )
            tp.product = product
            new_transaction.items.append(tp)
    db.session.add(new_transaction)
    db.session.commit()
    return jsonify({"message": "Transaction added successfully", "id": new_transaction.id}), 201

@app.route('/transactions/<int:transaction_id>', methods=['PUT'])
def update_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    data = request.json

    # Update basic transaction details
    transaction.total = data.get('total', transaction.total)
    transaction.payment_method = data.get('payment_method', transaction.payment_method)

    # Handle items update: This is more complex.
    # A common strategy is to delete all existing items and re-add them.
    # This requires 'cascade="all, delete-orphan"' on the items relationship, which we already added.
    for item_to_delete in list(transaction.items):
        db.session.delete(item_to_delete)
    db.session.flush() # Ensure deletions are processed before adding new ones

    if 'items' in data and isinstance(data['items'], list):
        for item_data in data['items']:
            product = Product.query.get(item_data['product_id'])
            if product:
                tp = TransactionProduct(
                    quantity=item_data['qty']
                )
                tp.product = product
                transaction.items.append(tp)
            else:
                # Handle case where product_id is invalid
                return jsonify({"message": f"Product with ID {item_data['product_id']} not found"}), 400

    db.session.commit()
    return jsonify({"message": "Transaction updated successfully"}), 200

@app.route('/transactions/<int:transaction_id>', methods=['DELETE'])
def delete_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    db.session.delete(transaction)
    db.session.commit()
    return jsonify({"message": "Transaction deleted successfully"})

# --- Banner Endpoints ---
@app.route('/banners', methods=['GET'])
def get_banners():
    banners = Banner.query.all()
    return jsonify([{"id": b.id, "image_url": b.image_url} for b in banners])

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
