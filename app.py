from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import json
from sqlalchemy import func
import csv
import io
from flask import send_file
import json
from datetime import datetime


from langchain_groq import ChatGroq
from langchain.prompts import ChatPromptTemplate
from dotenv import load_dotenv
import os
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///expense_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Custom Jinja filters
@app.template_filter('nl2br')
def nl2br(value):
    """Convert newlines to HTML line breaks."""
    if value:
        value = value.replace('\n', '<br>')
    return value

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Define database models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    date_registered = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    accounts = db.relationship('Account', backref='owner', lazy=True)
    categories = db.relationship('Category', backref='owner', lazy=True)
    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationship with transactions
    transactions = db.relationship('Transaction', backref='account', lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'income' or 'expense'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationship with transactions
    transactions = db.relationship('Transaction', backref='category', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # 'income' or 'expense'
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.Date, default=datetime.utcnow)
    
    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Load environment variables
load_dotenv()

def get_financial_insights(user_id):
    """Generate financial insights using LLM."""
    # Get transaction data for the last 3 months
    three_months_ago = datetime.now() - timedelta(days=90)
    
    # Get expense data
    expenses = db.session.query(
        Transaction.date, 
        Category.name.label('category'),
        Transaction.amount,
        Transaction.description
    ).join(Category, Transaction.category_id == Category.id) \
    .filter(Transaction.user_id == user_id) \
    .filter(Transaction.type == 'expense') \
    .filter(Transaction.date >= three_months_ago) \
    .order_by(Transaction.date.desc()) \
    .all()
    
    # Get income data
    incomes = db.session.query(
        Transaction.date, 
        Category.name.label('category'),
        Transaction.amount,
        Transaction.description
    ).join(Category, Transaction.category_id == Category.id) \
    .filter(Transaction.user_id == user_id) \
    .filter(Transaction.type == 'income') \
    .filter(Transaction.date >= three_months_ago) \
    .order_by(Transaction.date.desc()) \
    .all()
    
    # Get account balances
    accounts = db.session.query(
        Account.name,
        Account.balance
    ).filter(Account.user_id == user_id).all()
    
    # Convert to dataframes for easier analysis
    expenses_df = pd.DataFrame(expenses, columns=['date', 'category', 'amount', 'description'])
    incomes_df = pd.DataFrame(incomes, columns=['date', 'category', 'amount', 'description'])
    accounts_df = pd.DataFrame(accounts, columns=['name', 'balance'])
    
    # Get summary statistics
    total_expenses = expenses_df['amount'].sum() if not expenses_df.empty else 0
    total_income = incomes_df['amount'].sum() if not incomes_df.empty else 0
    total_balance = accounts_df['balance'].sum() if not accounts_df.empty else 0
    
    # Group expenses by category
    expense_by_category = {}
    if not expenses_df.empty:
        expense_by_category = expenses_df.groupby('category')['amount'].sum().to_dict()
    
    # Prepare the context for the LLM
    financial_context = f"""
    Financial Summary:
    - Total Expenses (Last 3 Months): ${total_expenses:.2f}
    - Total Income (Last 3 Months): ${total_income:.2f}
    - Net Savings/Loss: ${(total_income - total_expenses):.2f}
    - Current Total Balance: ${total_balance:.2f}
    
    Expense Breakdown by Category:
    {', '.join([f"{category}: ${amount:.2f}" for category, amount in expense_by_category.items()])}
    
    Top Expense Categories:
    {', '.join([f"{category}: ${amount:.2f}" for category, amount in sorted(expense_by_category.items(), key=lambda x: x[1], reverse=True)[:3]]) if expense_by_category else "No expense data available"}
    """
    
    try:
        # Initialize the Groq LLM
        llm = ChatGroq(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            model_name="llama3-70b-8192"  # You can change this to a different model
        )
        
        # Create a prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a personal financial advisor. Analyze the user's financial data and provide 
            helpful insights and actionable recommendations to improve their financial health. 
            Focus on spending patterns, saving opportunities, and budget optimization.
            Format your response in a clear, concise manner with section headings and bullet points. 
            Include 3-5 specific recommendations based on the data provided."""),
            ("user", "{financial_data}")
        ])
        
        # Generate insights
        chain = prompt | llm
        response = chain.invoke({"financial_data": financial_context})
        
        # Extract the content from the response
        insights = response.content
        
        return insights
    
    except Exception as e:
        # Return a fallback message if there's an error
        return f"Unable to generate financial insights at this time. Error: {str(e)}"


# Create default categories for a new user
def create_default_categories(user_id):
    default_expense_categories = ['Food', 'Transport', 'Housing', 'Utilities', 'Entertainment', 'Shopping', 'Healthcare', 'Education', 'Other']
    default_income_categories = ['Salary', 'Gift', 'Investment', 'Freelance', 'Other']
    
    for category_name in default_expense_categories:
        category = Category(name=category_name, type='expense', user_id=user_id)
        db.session.add(category)
    
    for category_name in default_income_categories:
        category = Category(name=category_name, type='income', user_id=user_id)
        db.session.add(category)
    
    db.session.commit()

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# @app.route('/register', methods=['GET', 'POST'])
# def register():
#     if request.method == 'POST':
#         username = request.form.get('username')
#         name = request.form.get('name')
#         email = request.form.get('email')
#         password = request.form.get('password')
#         confirm_password = request.form.get('confirm_password')
        
#         # Validation
#         if User.query.filter_by(username=username).first():
#             flash('Username already exists', 'danger')
#             return redirect(url_for('register'))
            
#         if User.query.filter_by(email=email).first():
#             flash('Email already registered', 'danger')
#             return redirect(url_for('register'))
            
#         if password != confirm_password:
#             flash('Passwords do not match', 'danger')
#             return redirect(url_for('register'))
        
#         # Create new user
#         hashed_password = generate_password_hash(password, method='sha256')
#         new_user = User(username=username, name=name, email=email, password=hashed_password)
#         db.session.add(new_user)
#         db.session.commit()
        
#         # Create default categories for new user
#         create_default_categories(new_user.id)
        
#         # Create a default cash account
#         cash_account = Account(name='Cash', balance=0.0, user_id=new_user.id)
#         db.session.add(cash_account)
#         db.session.commit()
        
#         flash('Registration successful! You can now login.', 'success')
#         return redirect(url_for('login'))
        
#     return render_template('register.html')

# @app.route('/register', methods=['GET', 'POST'])
# def register():
#     if request.method == 'POST':
#         username = request.form.get('username')
#         name = request.form.get('name')
#         email = request.form.get('email')
#         password = request.form.get('password')
#         confirm_password = request.form.get('confirm_password')
        
#         # Validation
#         if User.query.filter_by(username=username).first():
#             flash('Username already exists', 'danger')
#             return redirect(url_for('register'))
            
#         if User.query.filter_by(email=email).first():
#             flash('Email already registered', 'danger')
#             return redirect(url_for('register'))
            
#         if password != confirm_password:
#             flash('Passwords do not match', 'danger')
#             return redirect(url_for('register'))
        
#         # Create new user with the updated method parameter
#         # Use 'pbkdf2:sha256' instead of 'sha256'
#         hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
#         new_user = User(username=username, name=name, email=email, password=hashed_password)
#         db.session.add(new_user)
#         db.session.commit()
        
#         # Create default categories for new user
#         create_default_categories(new_user.id)
        
#         # Create a default cash account
#         cash_account = Account(name='Cash', balance=0.0, user_id=new_user.id)
#         db.session.add(cash_account)
#         db.session.commit()
        
#         flash('Registration successful! You can now login.', 'success')
#         return redirect(url_for('login'))
        
#     return render_template('register.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    # If user is already logged in, redirect to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
            
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
        
        # Create new user with the updated method parameter
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, name=name, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        # Create default categories for new user
        create_default_categories(new_user.id)
        
        # Create a default cash account
        cash_account = Account(name='Cash', balance=0.0, user_id=new_user.id)
        db.session.add(cash_account)
        db.session.commit()
        
        flash('Registration successful! You can now login.', 'success')
        # Redirect to login page instead of letting it proceed to the next page
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not check_password_hash(user.password, password):
            flash('Please check your login details and try again.', 'danger')
            return redirect(url_for('login'))
            
        login_user(user, remember=remember)
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('dashboard'))
        
    return render_template('login.html')

# @app.route('/login', methods=['GET', 'POST'])
# def login():
#     if request.method == 'POST':
#         username = request.form.get('username')
#         password = request.form.get('password')
#         remember = True if request.form.get('remember') else False
        
#         user = User.query.filter_by(username=username).first()
        
#         if not user or not check_password_hash(user.password, password):
#             flash('Please check your login details and try again.', 'danger')
#             return redirect(url_for('login'))
            
#         login_user(user, remember=remember)
#         return redirect(url_for('dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's accounts
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    total_balance = sum(account.balance for account in accounts)
    
    # Get recent transactions (last 5)
    recent_transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).limit(5).all()
    
    # Get expense summary by category
    expense_summary = db.session.query(Category.name, func.sum(Transaction.amount)) \
        .join(Transaction, Category.id == Transaction.category_id) \
        .filter(Transaction.user_id == current_user.id) \
        .filter(Transaction.type == 'expense') \
        .group_by(Category.name) \
        .all()
    
    # Prepare data for charts
    expense_labels = [item[0] for item in expense_summary]
    expense_values = [float(item[1]) for item in expense_summary]
    
    # Account balance for pie chart
    account_labels = [account.name for account in accounts]
    account_values = [account.balance for account in accounts]
    
    return render_template('dashboard.html', 
                          accounts=accounts,
                          total_balance=total_balance,
                          recent_transactions=recent_transactions,
                          expense_labels=json.dumps(expense_labels),
                          expense_values=json.dumps(expense_values),
                          account_labels=json.dumps(account_labels),
                          account_values=json.dumps(account_values))

@app.route('/transactions')
@login_required
def transactions():
    # Get all user transactions
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).all()
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    categories = Category.query.filter_by(user_id=current_user.id).all()
    
    return render_template('transactions.html', 
                          transactions=transactions, 
                          accounts=accounts, 
                          categories=categories)

@app.route('/add_transaction', methods=['GET', 'POST'])
@login_required
def add_transaction():
    if request.method == 'POST':
        transaction_type = request.form.get('type')
        amount = float(request.form.get('amount'))
        account_id = int(request.form.get('account_id'))
        category_id = int(request.form.get('category_id'))
        description = request.form.get('description')
        date_str = request.form.get('date')
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Validate transaction
        account = Account.query.get(account_id)
        if not account or account.user_id != current_user.id:
            flash('Invalid account', 'danger')
            return redirect(url_for('add_transaction'))
            
        category = Category.query.get(category_id)
        if not category or category.user_id != current_user.id:
            flash('Invalid category', 'danger')
            return redirect(url_for('add_transaction'))
            
        if transaction_type == 'expense' and amount > account.balance:
            flash('Insufficient funds in this account', 'danger')
            return redirect(url_for('add_transaction'))
        
        # Create new transaction
        new_transaction = Transaction(
            type=transaction_type,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            description=description,
            date=date,
            user_id=current_user.id
        )
        db.session.add(new_transaction)
        
        # Update account balance
        if transaction_type == 'expense':
            account.balance -= amount
        else:  # income
            account.balance += amount
            
        db.session.commit()
        flash('Transaction added successfully', 'success')
        return redirect(url_for('transactions'))
    
    # GET request - show form
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    expense_categories = Category.query.filter_by(user_id=current_user.id, type='expense').all()
    income_categories = Category.query.filter_by(user_id=current_user.id, type='income').all()
    
    return render_template('add_transaction.html', 
                          accounts=accounts, 
                          expense_categories=expense_categories,
                          income_categories=income_categories,
                          today=datetime.now().strftime('%Y-%m-%d'))

# Add this function to your app.py file or replace the existing accounts route

@app.route('/accounts')
@login_required
def accounts():
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    
    # Calculate total balance
    total_balance = sum(account.balance for account in accounts)
    
    return render_template('accounts.html', 
                          accounts=accounts,
                          total_balance=total_balance)

@app.route('/add_account', methods=['GET', 'POST'])
@login_required
def add_account():
    if request.method == 'POST':
        account_name = request.form.get('name')
        initial_balance = float(request.form.get('balance') or 0)
        
        # Check if account name already exists for this user
        existing_account = Account.query.filter_by(user_id=current_user.id, name=account_name).first()
        if existing_account:
            flash('An account with this name already exists', 'danger')
            return redirect(url_for('add_account'))
        
        # Create new account
        new_account = Account(name=account_name, balance=initial_balance, user_id=current_user.id)
        db.session.add(new_account)
        db.session.commit()
        
        flash('Account added successfully', 'success')
        return redirect(url_for('accounts'))
        
    return render_template('add_account.html')

@app.route('/update_account/<int:account_id>', methods=['GET', 'POST'])
@login_required
def update_account(account_id):
    account = Account.query.get_or_404(account_id)
    
    # Check if account belongs to current user
    if account.user_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('accounts'))
    
    if request.method == 'POST':
        account.name = request.form.get('name')
        account.balance = float(request.form.get('balance'))
        
        db.session.commit()
        flash('Account updated successfully', 'success')
        return redirect(url_for('accounts'))
        
    return render_template('update_account.html', account=account)

@app.route('/delete_account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    account = Account.query.get_or_404(account_id)
    
    # Check if account belongs to current user
    if account.user_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('accounts'))
    
    # Check if account has transactions
    if Transaction.query.filter_by(account_id=account_id).first():
        flash('Cannot delete account with transactions', 'danger')
        return redirect(url_for('accounts'))
    
    db.session.delete(account)
    db.session.commit()
    flash('Account deleted successfully', 'success')
    return redirect(url_for('accounts'))

@app.route('/categories')
@login_required
def categories():
    expense_categories = Category.query.filter_by(user_id=current_user.id, type='expense').all()
    income_categories = Category.query.filter_by(user_id=current_user.id, type='income').all()
    return render_template('categories.html', 
                          expense_categories=expense_categories,
                          income_categories=income_categories)

@app.route('/add_category', methods=['GET', 'POST'])
@login_required
def add_category():
    if request.method == 'POST':
        category_name = request.form.get('name')
        category_type = request.form.get('type')
        
        # Check if category name already exists for this user and type
        existing_category = Category.query.filter_by(
            user_id=current_user.id, 
            name=category_name,
            type=category_type
        ).first()
        
        if existing_category:
            flash(f'A {category_type} category with this name already exists', 'danger')
            return redirect(url_for('add_category'))
        
        # Create new category
        new_category = Category(name=category_name, type=category_type, user_id=current_user.id)
        db.session.add(new_category)
        db.session.commit()
        
        flash('Category added successfully', 'success')
        return redirect(url_for('categories'))
        
    return render_template('add_category.html')

@app.route('/update_category/<int:category_id>', methods=['GET', 'POST'])
@login_required
def update_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Check if category belongs to current user
    if category.user_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('categories'))
    
    if request.method == 'POST':
        category.name = request.form.get('name')
        
        db.session.commit()
        flash('Category updated successfully', 'success')
        return redirect(url_for('categories'))
        
    return render_template('update_category.html', category=category)

@app.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Check if category belongs to current user
    if category.user_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('categories'))
    
    # Check if category has transactions
    if Transaction.query.filter_by(category_id=category_id).first():
        flash('Cannot delete category with transactions', 'danger')
        return redirect(url_for('categories'))
    
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted successfully', 'success')
    return redirect(url_for('categories'))

# @app.route('/report')
# @login_required
# def report():
#     # Get summary data for reports
#     # Monthly expenses by category
#     monthly_expenses = db.session.query(
#         func.strftime('%Y-%m', Transaction.date).label('month'),
#         Category.name,
#         func.sum(Transaction.amount)
#     ).join(Category, Transaction.category_id == Category.id) \
#     .filter(Transaction.user_id == current_user.id) \
#     .filter(Transaction.type == 'expense') \
#     .group_by('month', Category.name) \
#     .order_by('month') \
#     .all()
    
#     # Process data for charts
#     report_data = {}
#     for month, category, amount in monthly_expenses:
#         if month not in report_data:
#             report_data[month] = {}
#         report_data[month][category] = float(amount)
    
#     # Get income vs expenses by month
#     monthly_summary = db.session.query(
#         func.strftime('%Y-%m', Transaction.date).label('month'),
#         Transaction.type,
#         func.sum(Transaction.amount)
#     ).filter(Transaction.user_id == current_user.id) \
#     .group_by('month', Transaction.type) \
#     .order_by('month') \
#     .all()
    
#     # Process income vs expense data
#     income_vs_expense = {}
#     for month, type_, amount in monthly_summary:
#         if month not in income_vs_expense:
#             income_vs_expense[month] = {'income': 0, 'expense': 0}
#         income_vs_expense[month][type_] = float(amount)
    
#     return render_template('report.html', 
#                           report_data=json.dumps(report_data),
#                           income_vs_expense=json.dumps(income_vs_expense))

@app.route('/report')
@login_required
def report():
    # Get summary data for reports
    # Monthly expenses by category
    monthly_expenses = db.session.query(
        func.strftime('%Y-%m', Transaction.date).label('month'),
        Category.name,
        func.sum(Transaction.amount)
    ).join(Category, Transaction.category_id == Category.id) \
    .filter(Transaction.user_id == current_user.id) \
    .filter(Transaction.type == 'expense') \
    .group_by('month', Category.name) \
    .order_by('month') \
    .all()
    
    # Process data for charts
    report_data = {}
    for month, category, amount in monthly_expenses:
        if month not in report_data:
            report_data[month] = {}
        report_data[month][category] = float(amount)
    
    # Get income vs expenses by month
    monthly_summary = db.session.query(
        func.strftime('%Y-%m', Transaction.date).label('month'),
        Transaction.type,
        func.sum(Transaction.amount)
    ).filter(Transaction.user_id == current_user.id) \
    .group_by('month', Transaction.type) \
    .order_by('month') \
    .all()
    
    # Process income vs expense data
    income_vs_expense = {}
    for month, type_, amount in monthly_summary:
        if month not in income_vs_expense:
            income_vs_expense[month] = {'income': 0, 'expense': 0}
        income_vs_expense[month][type_] = float(amount)
    
    # Generate LLM insights if the user has transaction data
    financial_insights = None
    if monthly_expenses or monthly_summary:
        financial_insights = get_financial_insights(current_user.id)
    
    return render_template('report.html', 
                          report_data=json.dumps(report_data),
                          income_vs_expense=json.dumps(income_vs_expense),
                          financial_insights=financial_insights)

# @app.route('/profile', methods=['GET', 'POST'])
# @login_required
# def profile():
#     if request.method == 'POST':
#         # Update user profile
#         current_user.name = request.form.get('name')
#         current_user.email = request.form.get('email')
        
#         # Check if password change was requested
#         current_password = request.form.get('current_password')
#         new_password = request.form.get('new_password')
#         confirm_password = request.form.get('confirm_password')
        
#         if current_password and new_password:
#             # Verify current password
#             if not check_password_hash(current_user.password, current_password):
#                 flash('Current password is incorrect', 'danger')
#                 return redirect(url_for('profile'))
                
#             if new_password != confirm_password:
#                 flash('New passwords do not match', 'danger')
#                 return redirect(url_for('profile'))
                
#             # Update password
#             current_user.password = generate_password_hash(new_password, method='sha256')
            
#         db.session.commit()
#         flash('Profile updated successfully', 'success')
#         return redirect(url_for('profile'))
        
#     return render_template('profile.html', user=current_user)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'profile':
            # Update user profile info
            current_user.name = request.form.get('name')
            current_user.email = request.form.get('email')
            flash('Profile updated successfully', 'success')
            
        elif form_type == 'password':
            # Handle password change
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            # Verify current password
            if not check_password_hash(current_user.password, current_password):
                flash('Current password is incorrect', 'danger')
                return redirect(url_for('profile'))
                
            if new_password != confirm_password:
                flash('New passwords do not match', 'danger')
                return redirect(url_for('profile'))
                
            # Update password using the correct method
            current_user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
            flash('Password updated successfully', 'success')
        
        # Save changes to database
        db.session.commit()
        return redirect(url_for('profile'))
        
    return render_template('profile.html', user=current_user)
# API routes for AJAX
@app.route('/api/categories/<transaction_type>')
@login_required
def get_categories_by_type(transaction_type):
    categories = Category.query.filter_by(user_id=current_user.id, type=transaction_type).all()
    return jsonify([{'id': category.id, 'name': category.name} for category in categories])

# Create all tables
with app.app_context():
    db.create_all()


# Add these routes to your app.py file



# Update the export_data route to support both GET and POST

@app.route('/report', methods=['GET', 'POST'])
@login_required
def export_data():
    """Export all user data as a zip file containing CSV files."""
    from io import StringIO
    import csv
    from zipfile import ZipFile
    from io import BytesIO
    
    memory_file = BytesIO()
    
    with ZipFile(memory_file, 'w') as zf:
        # Export accounts
        accounts_file = StringIO()
        accounts_writer = csv.writer(accounts_file)
        accounts_writer.writerow(['ID', 'Name', 'Balance'])
        
        for account in current_user.accounts:
            accounts_writer.writerow([account.id, account.name, account.balance])
        
        zf.writestr('accounts.csv', accounts_file.getvalue())
        
        # Export categories
        categories_file = StringIO()
        categories_writer = csv.writer(categories_file)
        categories_writer.writerow(['ID', 'Name', 'Type'])
        
        for category in current_user.categories:
            categories_writer.writerow([category.id, category.name, category.type])
        
        zf.writestr('categories.csv', categories_file.getvalue())
        
        # Export transactions
        transactions_file = StringIO()
        transactions_writer = csv.writer(transactions_file)
        transactions_writer.writerow(['ID', 'Date', 'Type', 'Amount', 'Description', 'Account', 'Category'])
        
        for transaction in current_user.transactions:
            transactions_writer.writerow([
                transaction.id,
                transaction.date.strftime('%Y-%m-%d'),
                transaction.type,
                transaction.amount,
                transaction.description or '',
                transaction.account.name,
                transaction.category.name
            ])
        
        zf.writestr('transactions.csv', transactions_file.getvalue())
        
        # Export user profile (without sensitive info)
        profile_file = StringIO()
        profile_writer = csv.writer(profile_file)
        profile_writer.writerow(['Username', 'Email', 'Name', 'Date Registered'])
        profile_writer.writerow([
            current_user.username,
            current_user.email,
            current_user.name,
            current_user.date_registered.strftime('%Y-%m-%d')
        ])
        
        zf.writestr('profile.csv', profile_file.getvalue())
    
    # Reset file pointer
    memory_file.seek(0)
    
    # Create a download name with the current date
    download_name = f"financial_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    
    return send_file(
        memory_file,
        download_name=download_name,
        as_attachment=True,
        mimetype='application/zip'
    )


@app.route('/delete_user_account', methods=['POST'])
@login_required
def delete_user_account():
    """Delete the user account and all associated data."""
    password = request.form.get('delete_password')
    
    # Verify password
    if not check_password_hash(current_user.password, password):
        flash('Incorrect password. Account deletion cancelled.', 'danger')
        return redirect(url_for('profile'))
    
    # Store user ID before logout
    user_id = current_user.id
    
    # Log out the user first
    logout_user()
    
    # Get the user object
    user = User.query.get(user_id)
    
    # Delete all user's transactions
    Transaction.query.filter_by(user_id=user_id).delete()
    
    # Delete all user's accounts
    Account.query.filter_by(user_id=user_id).delete()
    
    # Delete all user's categories
    Category.query.filter_by(user_id=user_id).delete()
    
    # Delete the user
    db.session.delete(user)
    db.session.commit()
    
    flash('Your account and all associated data have been permanently deleted.', 'info')
    return redirect(url_for('index'))


# Run the app
if __name__ == '__main__':
    app.run(debug=True)