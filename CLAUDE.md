# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FinInsight is a Flask-based personal financial tracking application with AI-powered insights. It uses SQLite for data storage, Flask-Login for authentication, and LangChain with Groq API for generating financial insights.

## Development Commands

### Running the Application
```bash
python app.py
```
The app runs in debug mode by default on http://localhost:5000

### Database Management
The database is automatically created on first run. To reset the database, delete `instance/expense_tracker.db` and restart the app.

## Architecture

### Single-File Application Structure
The entire application is contained in `app.py` (~950 lines). All routes, models, and business logic are in this single file.

### Database Models (SQLAlchemy)
- **User**: Authentication and user profile (id, username, email, password, name, date_registered)
- **Account**: Financial accounts belonging to users (id, name, balance, user_id)
- **Category**: Income/expense categories (id, name, type, user_id)
- **Transaction**: Income and expense records (id, type, amount, description, date, user_id, account_id, category_id)

Relationships:
- One user has many accounts, categories, and transactions
- Each transaction belongs to one account and one category
- Cascading deletes are NOT configured - manual cleanup is required

### Key Routes and Functionality

**Authentication Routes:**
- `/register` - User registration with password hashing (pbkdf2:sha256)
- `/login` - Login with Flask-Login session management
- `/logout` - Session termination

**Core CRUD Routes:**
- `/dashboard` - Main view with account balances, recent transactions, and expense charts
- `/transactions` - List all transactions with add/edit capabilities
- `/add_transaction` - Transaction creation with account balance updates
- `/accounts` - Account management (add/update/delete with validation)
- `/categories` - Category management (expense/income types)

**Reporting and Insights:**
- `/report` - Financial reports with monthly summaries and AI-generated insights
- Uses `get_financial_insights()` function that analyzes last 3 months of data
- LLM integration via LangChain + Groq API (llama3-70b-8192 model)

**Data Management:**
- `/export_data` - Exports user data as zip file with CSV files (accounts, categories, transactions, profile)
- `/delete_user_account` - Complete account deletion with password verification

### AI Integration Details

The `get_financial_insights(user_id)` function:
1. Queries last 3 months of transactions
2. Aggregates expenses by category
3. Calculates net savings/loss and total balance
4. Sends financial summary to Groq LLM via LangChain
5. Returns formatted insights with recommendations

Requires `GROQ_API_KEY` in `.env` file.

### Important Validation Rules

**Account Balance Validation:**
- Expenses cannot exceed account balance (checked in `add_transaction`)
- Account updates allow direct balance modification

**Delete Restrictions:**
- Accounts with transactions cannot be deleted
- Categories with transactions cannot be deleted

**User Registration:**
- Creates default expense categories: Food, Transport, Housing, Utilities, Entertainment, Shopping, Healthcare, Education, Other
- Creates default income categories: Salary, Gift, Investment, Freelance, Other
- Creates default "Cash" account with 0 balance

### Transaction Flow
When adding a transaction:
1. Validate account and category ownership
2. Check sufficient balance for expenses
3. Create transaction record
4. Update account balance (+income or -expense)
5. Commit both changes in single transaction

### Templates
All HTML templates are in `/templates` directory using Jinja2:
- `layout.html` - Base template with Bootstrap 5
- Dashboard uses Chart.js for visualizations (pie charts for expenses and account balances)
- Custom Jinja filter `nl2br` converts newlines to HTML breaks

## Configuration

**Required Environment Variables (.env):**
- `GROQ_API_KEY` - Required for AI insights feature

**Flask Configuration (app.py:24-26):**
- `SECRET_KEY` - Currently hardcoded as 'your_secret_key_here' (should be changed in production)
- `SQLALCHEMY_DATABASE_URI` - SQLite database at `instance/expense_tracker.db`
- `SQLALCHEMY_TRACK_MODIFICATIONS` - Disabled

## Known Patterns

**Password Hashing:**
Uses `werkzeug.security.generate_password_hash` with method='pbkdf2:sha256'

**Date Handling:**
- Database stores dates as `Date` type (not DateTime for transactions)
- Date inputs use format '%Y-%m-%d'
- UTC timestamps for user registration

**Flash Message Categories:**
- 'success' - Green success messages
- 'danger' - Red error messages
- 'info' - Blue informational messages

## Security Considerations

- SECRET_KEY is hardcoded and should be moved to environment variables
- No CSRF protection implemented (Flask-WTF not used)
- SQL injection protected by SQLAlchemy ORM
- Password hashing uses secure pbkdf2:sha256 method
- User ownership validation on all CRUD operations
- Session-based authentication via Flask-Login
