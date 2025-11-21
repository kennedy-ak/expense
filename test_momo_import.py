"""
Test suite for MoMo PDF import functionality
Run with: python -m pytest test_momo_import.py -v
"""

import pytest
from datetime import datetime
from momo_import import (
    parse_momo_date,
    parse_amount,
    parse_fee_or_tax,
    extract_counterparty,
    determine_transaction_type,
    auto_categorize,
    categorize_transactions,
    find_duplicates,
    generate_import_summary,
    parse_table_row
)

# =============================================================================
# DATE PARSING TESTS
# =============================================================================

def test_parse_momo_date_standard():
    """Test standard MoMo date format"""
    result = parse_momo_date("20 Nov 2025 18:18")
    assert result is not None
    assert result.day == 20
    assert result.month == 11
    assert result.year == 2025
    assert result.hour == 18
    assert result.minute == 18

def test_parse_momo_date_full_month():
    """Test full month name format"""
    result = parse_momo_date("15 December 2025 09:30")
    assert result is not None
    assert result.month == 12

def test_parse_momo_date_invalid():
    """Test invalid date returns None"""
    result = parse_momo_date("invalid date")
    assert result is None

# =============================================================================
# AMOUNT PARSING TESTS
# =============================================================================

def test_parse_amount_negative():
    """Test parsing negative amount (expense)"""
    amount, is_expense = parse_amount("-25.00")
    assert amount == 25.00
    assert is_expense is True

def test_parse_amount_positive():
    """Test parsing positive amount (income)"""
    amount, is_expense = parse_amount("+50.00")
    assert amount == 50.00
    assert is_expense is False

def test_parse_amount_with_currency():
    """Test parsing amount with GHS prefix"""
    amount, is_expense = parse_amount("GHS 32.46")
    assert amount == 32.46
    assert is_expense is False

def test_parse_amount_empty():
    """Test parsing empty amount"""
    amount, is_expense = parse_amount("")
    assert amount == 0.0
    assert is_expense is False

# =============================================================================
# FEE/TAX PARSING TESTS
# =============================================================================

def test_parse_fee_standard():
    """Test parsing standard fee format"""
    result = parse_fee_or_tax("GHS 0.50")
    assert result == 0.50

def test_parse_fee_zero():
    """Test parsing zero fee"""
    result = parse_fee_or_tax("GHS 0.00")
    assert result == 0.0

def test_parse_fee_empty():
    """Test parsing empty fee"""
    result = parse_fee_or_tax("")
    assert result == 0.0

# =============================================================================
# COUNTERPARTY EXTRACTION TESTS
# =============================================================================

def test_extract_counterparty_full():
    """Test extracting phone and name"""
    phone, name = extract_counterparty("+233 54 86 74 41 0, JAMES F. TORI VENTURES")
    assert phone == "+233 54 86 74 41 0"
    assert name == "JAMES F. TORI VENTURES"

def test_extract_counterparty_phone_only():
    """Test extracting phone only"""
    phone, name = extract_counterparty("+233 55 123 4567")
    assert phone == "+233 55 123 4567"
    assert name is None

def test_extract_counterparty_name_only():
    """Test extracting name only"""
    phone, name = extract_counterparty("MARIAM EFFE")
    assert name == "MARIAM EFFE"

# =============================================================================
# TRANSACTION TYPE TESTS
# =============================================================================

def test_determine_type_expense():
    """Test determining expense type"""
    result = determine_transaction_type("CASH OUT", True)
    assert result == "expense"

def test_determine_type_income():
    """Test determining income type"""
    result = determine_transaction_type("MOMO USER", False)
    assert result == "income"

def test_determine_type_transfer():
    """Test determining transfer type"""
    result = determine_transaction_type("BANKPUSH", True)
    assert result == "transfer"

# =============================================================================
# AUTO-CATEGORIZATION TESTS
# =============================================================================

def test_auto_categorize_transport():
    """Test categorizing transport transactions"""
    trans = {
        'payment_type': 'MOMO USER',
        'reference': 'Uber ride',
        'counterparty': 'UBER GH'
    }
    result = auto_categorize(trans)
    assert result == 'Transport'

def test_auto_categorize_airtime():
    """Test categorizing airtime transactions"""
    trans = {
        'payment_type': 'AIRTIME',
        'reference': '',
        'counterparty': 'MTN'
    }
    result = auto_categorize(trans)
    assert result == 'Utilities'

def test_auto_categorize_food():
    """Test categorizing food transactions"""
    trans = {
        'payment_type': 'MOMO USER',
        'reference': 'Pizza order',
        'counterparty': 'PIZZA INN'
    }
    result = auto_categorize(trans)
    assert result == 'Food'

def test_auto_categorize_default():
    """Test default category for unknown transactions"""
    trans = {
        'payment_type': 'MOMO USER',
        'reference': '',
        'counterparty': 'RANDOM PERSON',
        'type': 'expense'
    }
    result = auto_categorize(trans)
    assert result == 'Other'

# =============================================================================
# DUPLICATE DETECTION TESTS
# =============================================================================

def test_find_duplicates():
    """Test duplicate detection"""
    transactions = [
        {'transaction_id': '123', 'amount': 10},
        {'transaction_id': '456', 'amount': 20},
        {'transaction_id': '789', 'amount': 30}
    ]
    existing_ids = {'123', '789'}

    result = find_duplicates(transactions, existing_ids)

    assert result[0]['is_duplicate'] is True
    assert result[1]['is_duplicate'] is False
    assert result[2]['is_duplicate'] is True

# =============================================================================
# SUMMARY GENERATION TESTS
# =============================================================================

def test_generate_import_summary():
    """Test generating import summary"""
    transactions = [
        {
            'amount': 100,
            'type': 'income',
            'fees': 0,
            'tax': 0,
            'balance_after': 200,
            'is_duplicate': False,
            'suggested_category': 'Salary'
        },
        {
            'amount': 50,
            'type': 'expense',
            'fees': 0.5,
            'tax': 0,
            'balance_after': 150,
            'is_duplicate': False,
            'suggested_category': 'Food'
        },
        {
            'amount': 25,
            'type': 'expense',
            'fees': 0.25,
            'tax': 0,
            'balance_after': 125,
            'is_duplicate': True,
            'suggested_category': 'Transport'
        }
    ]

    summary = generate_import_summary(transactions)

    assert summary['total'] == 3
    assert summary['new_transactions'] == 2
    assert summary['duplicates'] == 1
    assert summary['total_income'] == 100
    assert summary['total_expense'] == 75
    assert summary['total_fees'] == 0.75
    assert summary['final_balance'] == 125

# =============================================================================
# TABLE ROW PARSING TESTS
# =============================================================================

def test_parse_table_row_valid():
    """Test parsing valid table row"""
    row = [
        "20 Nov 2025 18:18",
        "CASH OUT",
        "+233 54 86 74 41 0, JAMES F. TORI VENTURES",
        "-25.00",
        "69366086327",
        "GHS 0.50",
        "GHS 0.00",
        "GHS 32.46",
        "NationalId--"
    ]

    result = parse_table_row(row, 1, 1)

    assert result is not None
    assert result['amount'] == 25.0
    assert result['type'] == 'expense'
    assert result['transaction_id'] == "69366086327"
    assert result['fees'] == 0.50
    assert result['balance_after'] == 32.46

def test_parse_table_row_empty():
    """Test parsing empty row returns None"""
    row = [None, None, None, None]
    result = parse_table_row(row, 1, 1)
    assert result is None

def test_parse_table_row_short():
    """Test parsing row with too few columns"""
    row = ["20 Nov 2025", "CASH OUT"]
    result = parse_table_row(row, 1, 1)
    assert result is None

# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    # Run basic tests without pytest
    print("Running MoMo Import Tests...\n")

    tests = [
        ("Date parsing (standard)", test_parse_momo_date_standard),
        ("Date parsing (invalid)", test_parse_momo_date_invalid),
        ("Amount parsing (negative)", test_parse_amount_negative),
        ("Amount parsing (positive)", test_parse_amount_positive),
        ("Fee parsing", test_parse_fee_standard),
        ("Counterparty extraction", test_extract_counterparty_full),
        ("Transaction type (expense)", test_determine_type_expense),
        ("Auto-categorize (transport)", test_auto_categorize_transport),
        ("Duplicate detection", test_find_duplicates),
        ("Summary generation", test_generate_import_summary),
        ("Table row parsing", test_parse_table_row_valid),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            print(f"  PASS: {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*50}")
