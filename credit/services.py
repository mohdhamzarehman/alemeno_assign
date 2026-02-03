from datetime import date

from django.db.models import Q, Sum

from .models import Loan


LAKH = 100000


def round_to_lakh(value):
    return int(round(value / LAKH) * LAKH)


def calculate_emi(principal, annual_rate, tenure_months):
    if tenure_months <= 0:
        return 0.0
    monthly_rate = (annual_rate / 100.0) / 12.0
    if monthly_rate == 0:
        return principal / tenure_months
    factor = (1 + monthly_rate) ** tenure_months
    return principal * monthly_rate * factor / (factor - 1)


def get_current_loans(customer):
    today = date.today()
    return Loan.objects.filter(
        customer=customer
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))


def get_current_emi_sum(customer):
    return (
        get_current_loans(customer).aggregate(total=Sum("monthly_repayment")).get("total")
        or 0.0
    )


def get_current_debt_sum(customer):
    return (
        get_current_loans(customer).aggregate(total=Sum("loan_amount")).get("total")
        or 0.0
    )


def compute_credit_score(customer):
    loans = Loan.objects.filter(customer=customer)
    total_loans = loans.count()
    current_debt = get_current_debt_sum(customer)

    if current_debt > customer.approved_limit:
        return 0

    total_emis = loans.aggregate(total=Sum("tenure")).get("total") or 0
    paid_on_time = loans.aggregate(total=Sum("emis_paid_on_time")).get("total") or 0
    on_time_ratio = min(paid_on_time / total_emis, 1) if total_emis > 0 else 0

    loan_count_score = min(total_loans, 10) / 10 * 15

    current_year = date.today().year
    current_year_loans = loans.filter(start_date__year=current_year).count()
    current_year_score = min(current_year_loans, 5) / 5 * 15

    approved_limit = customer.approved_limit or 1
    total_volume = loans.aggregate(total=Sum("loan_amount")).get("total") or 0
    volume_score = min(total_volume / approved_limit, 1) * 20

    score = on_time_ratio * 50 + loan_count_score + current_year_score + volume_score
    return min(int(score), 100)


def minimum_rate_for_score(score):
    if score > 50:
        return 0.0
    if 30 < score <= 50:
        return 12.0
    if 10 < score <= 30:
        return 16.0
    return None


def evaluate_eligibility(customer, loan_amount, interest_rate, tenure):
    score = compute_credit_score(customer)
    min_rate = minimum_rate_for_score(score)
    corrected_rate = interest_rate

    if min_rate is None:
        return {
            "score": score,
            "approved": False,
            "corrected_rate": interest_rate,
        }

    if min_rate > 0 and interest_rate < min_rate:
        corrected_rate = min_rate

    current_emi_sum = get_current_emi_sum(customer)
    new_emi = calculate_emi(loan_amount, corrected_rate, tenure)
    emi_limit = 0.5 * customer.monthly_salary

    if current_emi_sum + new_emi > emi_limit:
        return {
            "score": score,
            "approved": False,
            "corrected_rate": corrected_rate,
        }

    if min_rate > 0 and interest_rate < min_rate:
        return {
            "score": score,
            "approved": False,
            "corrected_rate": corrected_rate,
        }

    return {
        "score": score,
        "approved": True,
        "corrected_rate": corrected_rate,
    }
