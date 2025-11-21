"""
MTN Mobile Money PDF Statement Import Module
============================================
This module handles parsing and importing MoMo PDF statements into FinInsight.
"""

import os
import re
from datetime import datetime
from werkzeug.utils import secure_filename
import pdfplumber

# =============================================================================
# CONFIGURATION
# =============================================================================

UPLOAD_FOLDER = 'uploads/statements'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def allowed_file(filename):
    """Check if file has allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_momo_date(date_str):
    """
    Parse MoMo date format to Python datetime.
    Format: "20 Nov 2025 18:18"
    """
    try:
        # Clean the date string
        date_str = date_str.strip()
        return datetime.strptime(date_str, "%d %b %Y %H:%M")
    except ValueError:
        # Try alternative formats
        formats = [
            "%d %B %Y %H:%M",      # Full month name
            "%d/%m/%Y %H:%M",      # Numeric format
            "%Y-%m-%d %H:%M:%S",   # ISO format
            "%d %b %Y",            # Without time
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

def parse_amount(amount_str):
    """
    Parse amount string to float.
    Handles formats like "-25.00", "+50.00", "GHS 32.46"
    Returns (amount, is_expense)
    """
    if not amount_str:
        return 0.0, False

    # Remove currency symbols and whitespace
    cleaned = re.sub(r'[GHS\s,]', '', str(amount_str))

    # Check if expense (negative)
    is_expense = cleaned.startswith('-')

    # Remove sign and convert to float
    cleaned = cleaned.lstrip('+-')

    try:
        amount = float(cleaned)
        return amount, is_expense
    except ValueError:
        return 0.0, False

def parse_fee_or_tax(value_str):
    """Parse fee/tax string like 'GHS 0.50' to float."""
    if not value_str:
        return 0.0

    cleaned = re.sub(r'[GHS\s,]', '', str(value_str))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def extract_counterparty(to_from_str):
    """
    Extract phone number and name from To/From field.
    Format: "+233 54 86 74 41 0, JAMES F. TORI VENTURES"
    Returns (phone, name)
    """
    if not to_from_str:
        return None, None

    parts = str(to_from_str).split(',', 1)

    phone = parts[0].strip() if parts else None
    name = parts[1].strip() if len(parts) > 1 else None

    # If first part doesn't look like a phone, it might be the name
    if phone and not re.search(r'[\d+]', phone):
        name = phone
        phone = None

    return phone, name

def determine_transaction_type(payment_type, amount_is_expense):
    """
    Determine transaction type based on payment type and amount sign.
    Returns 'income', 'expense', or 'transfer'
    """
    payment_type_upper = str(payment_type).upper() if payment_type else ''

    # Transfer indicators
    transfer_keywords = ['TRANSFER', 'BANKPUSH', 'BANK PUSH']
    if any(kw in payment_type_upper for kw in transfer_keywords):
        return 'transfer'

    # Use amount sign as primary indicator
    return 'expense' if amount_is_expense else 'income'

# =============================================================================
# PDF PARSING
# =============================================================================

def parse_momo_pdf(file_path):
    """
    Parse MTN MoMo PDF statement and extract transactions.

    Args:
        file_path: Path to the PDF file

    Returns:
        dict with 'transactions' list and 'errors' list
    """
    transactions = []
    errors = []

    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Extract tables from page
                tables = page.extract_tables()

                for table in tables:
                    if not table:
                        continue

                    # Find header row to determine column positions
                    header_row = None
                    data_start = 0

                    for i, row in enumerate(table):
                        if row and any('Date' in str(cell) for cell in row if cell):
                            header_row = row
                            data_start = i + 1
                            break

                    # If no header found, try to parse as data rows
                    if not header_row:
                        data_start = 0

                    # Process data rows
                    for row_num, row in enumerate(table[data_start:], data_start + 1):
                        try:
                            transaction = parse_table_row(row, page_num, row_num)
                            if transaction:
                                transactions.append(transaction)
                        except Exception as e:
                            errors.append({
                                'page': page_num,
                                'row': row_num,
                                'error': str(e),
                                'data': row
                            })

    except Exception as e:
        errors.append({
            'page': 0,
            'row': 0,
            'error': f"Failed to open PDF: {str(e)}",
            'data': None
        })

    return {
        'transactions': transactions,
        'errors': errors,
        'total_parsed': len(transactions),
        'total_errors': len(errors)
    }

def parse_table_row(row, page_num, row_num):
    """
    Parse a single table row into a transaction dict.

    Expected columns (may vary):
    0: Date & Time
    1: Payment Type
    2: To/From Account Name
    3: Amount
    4: Transaction ID
    5: Fees
    6: Tax
    7: Balance
    8: Reference
    """
    if not row or len(row) < 4:
        return None

    # Skip empty rows or header rows
    if all(not cell for cell in row):
        return None

    # Check if this looks like a data row (has a date)
    first_cell = str(row[0]) if row[0] else ''
    if not re.search(r'\d{1,2}\s+\w+\s+\d{4}', first_cell):
        return None

    # Extract fields with safe indexing
    def get_cell(index):
        return row[index] if index < len(row) and row[index] else ''

    date_str = get_cell(0)
    payment_type = get_cell(1)
    to_from = get_cell(2)
    amount_str = get_cell(3)
    transaction_id = get_cell(4)
    fees_str = get_cell(5)
    tax_str = get_cell(6)
    balance_str = get_cell(7)
    reference = get_cell(8) if len(row) > 8 else ''

    # Parse date
    parsed_date = parse_momo_date(date_str)
    if not parsed_date:
        return None

    # Parse amount
    amount, is_expense = parse_amount(amount_str)
    if amount == 0:
        return None

    # Parse fees and tax
    fees = parse_fee_or_tax(fees_str)
    tax = parse_fee_or_tax(tax_str)
    balance_after = parse_fee_or_tax(balance_str)

    # Extract counterparty info
    phone, name = extract_counterparty(to_from)
    counterparty = name if name else phone

    # Determine transaction type
    trans_type = determine_transaction_type(payment_type, is_expense)

    return {
        'date': parsed_date,
        'payment_type': payment_type,
        'counterparty': counterparty,
        'counterparty_phone': phone,
        'amount': amount,
        'transaction_id': str(transaction_id).strip() if transaction_id else None,
        'fees': fees,
        'tax': tax,
        'balance_after': balance_after,
        'reference': reference,
        'type': trans_type,
        'page': page_num,
        'row': row_num
    }

# =============================================================================
# AUTO-CATEGORIZATION
# =============================================================================

# Default categorization rules
DEFAULT_CATEGORY_RULES = {
    'Transport': ['uber', 'bolt', 'taxi', 'bus', 'fuel', 'petrol', 'transport'],
    'Food': ['food', 'restaurant', 'pizza', 'jumia food', 'kfc', 'chicken', 'meal'],
    'Shopping': ['jumia', 'tonaton', 'shop', 'store', 'market', 'mall'],
    'Utilities': ['airtime', 'data', 'ecg', 'electricity', 'water', 'internet', 'mtn'],
    'Bank Transfer': ['bank', 'bankpush', 'bank push', 'transfer'],
    'Healthcare': ['hospital', 'pharmacy', 'clinic', 'doctor', 'medical'],
    'Entertainment': ['movie', 'cinema', 'netflix', 'spotify', 'game'],
}

def auto_categorize(transaction, user_categories=None):
    """
    Auto-categorize a transaction based on keywords.

    Args:
        transaction: Transaction dict with payment_type, reference, counterparty
        user_categories: List of user's Category objects with keywords

    Returns:
        Category name or 'Other'
    """
    # Build search text from transaction fields
    search_text = ' '.join([
        str(transaction.get('payment_type', '')),
        str(transaction.get('reference', '')),
        str(transaction.get('counterparty', '')),
    ]).lower()

    # Check user's custom categories first
    if user_categories:
        for category in user_categories:
            if hasattr(category, 'keywords') and category.keywords:
                keywords = category.keywords if isinstance(category.keywords, list) else []
                for keyword in keywords:
                    if keyword.lower() in search_text:
                        return category.name

    # Fall back to default rules
    for category_name, keywords in DEFAULT_CATEGORY_RULES.items():
        for keyword in keywords:
            if keyword in search_text:
                return category_name

    # Default category based on transaction type
    if transaction.get('type') == 'income':
        return 'Other'  # Income Other
    return 'Other'  # Expense Other

def categorize_transactions(transactions, user_categories=None):
    """
    Add category suggestions to all transactions.

    Args:
        transactions: List of transaction dicts
        user_categories: User's Category objects

    Returns:
        List of transactions with 'suggested_category' field added
    """
    for trans in transactions:
        trans['suggested_category'] = auto_categorize(trans, user_categories)
    return transactions

# =============================================================================
# DUPLICATE DETECTION
# =============================================================================

def find_duplicates(transactions, existing_transaction_ids):
    """
    Mark transactions that already exist in database.

    Args:
        transactions: List of parsed transactions
        existing_transaction_ids: Set of existing transaction IDs

    Returns:
        transactions with 'is_duplicate' field added
    """
    for trans in transactions:
        trans_id = trans.get('transaction_id')
        trans['is_duplicate'] = trans_id in existing_transaction_ids if trans_id else False
    return transactions

# =============================================================================
# IMPORT SUMMARY
# =============================================================================

def generate_import_summary(transactions):
    """
    Generate summary statistics for parsed transactions.

    Args:
        transactions: List of parsed transactions

    Returns:
        dict with summary statistics
    """
    total = len(transactions)
    duplicates = sum(1 for t in transactions if t.get('is_duplicate', False))
    new_transactions = total - duplicates

    total_income = sum(t['amount'] for t in transactions if t.get('type') == 'income')
    total_expense = sum(t['amount'] for t in transactions if t.get('type') == 'expense')
    total_fees = sum(t.get('fees', 0) for t in transactions)
    total_tax = sum(t.get('tax', 0) for t in transactions)

    # Get final balance (from last transaction)
    final_balance = transactions[-1].get('balance_after', 0) if transactions else 0

    # Category breakdown
    categories = {}
    for trans in transactions:
        cat = trans.get('suggested_category', 'Other')
        if cat not in categories:
            categories[cat] = {'count': 0, 'amount': 0}
        categories[cat]['count'] += 1
        categories[cat]['amount'] += trans['amount']

    return {
        'total': total,
        'new_transactions': new_transactions,
        'duplicates': duplicates,
        'total_income': total_income,
        'total_expense': total_expense,
        'total_fees': total_fees,
        'total_tax': total_tax,
        'final_balance': final_balance,
        'categories': categories
    }
