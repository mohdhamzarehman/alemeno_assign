from datetime import date

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Customer, Loan
from .services import (
    calculate_emi,
    evaluate_eligibility,
    get_current_debt_sum,
    round_to_lakh,
)


def _require_fields(data, fields):
    missing = [field for field in fields if field not in data]
    if missing:
        return False, Response(
            {"error": f"Missing fields: {', '.join(missing)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return True, None


def _parse_int(value, field):
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, Response(
            {"error": f"Invalid value for {field}."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _parse_float(value, field):
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, Response(
            {"error": f"Invalid value for {field}."},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def register_customer(request):
    ok, response = _require_fields(
        request.data, ["first_name", "last_name", "age", "monthly_income", "phone_number"]
    )
    if not ok:
        return response

    monthly_income, error = _parse_int(request.data["monthly_income"], "monthly_income")
    if error:
        return error
    age, error = _parse_int(request.data["age"], "age")
    if error:
        return error
    approved_limit = round_to_lakh(36 * monthly_income)

    customer = Customer.objects.create(
        first_name=request.data["first_name"],
        last_name=request.data["last_name"],
        age=age,
        monthly_salary=monthly_income,
        approved_limit=approved_limit,
        phone_number=str(request.data["phone_number"]),
        current_debt=0,
    )

    return Response(
        {
            "customer_id": customer.customer_id,
            "name": f"{customer.first_name} {customer.last_name}",
            "age": customer.age,
            "monthly_income": customer.monthly_salary,
            "approved_limit": customer.approved_limit,
            "phone_number": customer.phone_number,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def check_eligibility(request):
    ok, response = _require_fields(
        request.data, ["customer_id", "loan_amount", "interest_rate", "tenure"]
    )
    if not ok:
        return response

    customer = get_object_or_404(Customer, customer_id=request.data["customer_id"])
    loan_amount, error = _parse_float(request.data["loan_amount"], "loan_amount")
    if error:
        return error
    interest_rate, error = _parse_float(request.data["interest_rate"], "interest_rate")
    if error:
        return error
    tenure, error = _parse_int(request.data["tenure"], "tenure")
    if error:
        return error

    evaluation = evaluate_eligibility(customer, loan_amount, interest_rate, tenure)
    corrected_rate = evaluation["corrected_rate"]
    monthly_installment = calculate_emi(loan_amount, corrected_rate, tenure)

    return Response(
        {
            "customer_id": customer.customer_id,
            "approval": evaluation["approved"],
            "interest_rate": interest_rate,
            "corrected_interest_rate": corrected_rate,
            "tenure": tenure,
            "monthly_installment": round(monthly_installment, 2),
        }
    )


@api_view(["POST"])
def create_loan(request):
    ok, response = _require_fields(
        request.data, ["customer_id", "loan_amount", "interest_rate", "tenure"]
    )
    if not ok:
        return response

    customer = get_object_or_404(Customer, customer_id=request.data["customer_id"])
    loan_amount, error = _parse_float(request.data["loan_amount"], "loan_amount")
    if error:
        return error
    interest_rate, error = _parse_float(request.data["interest_rate"], "interest_rate")
    if error:
        return error
    tenure, error = _parse_int(request.data["tenure"], "tenure")
    if error:
        return error

    evaluation = evaluate_eligibility(customer, loan_amount, interest_rate, tenure)
    corrected_rate = evaluation["corrected_rate"]
    monthly_installment = calculate_emi(loan_amount, corrected_rate, tenure)

    if not evaluation["approved"]:
        return Response(
            {
                "loan_id": None,
                "customer_id": customer.customer_id,
                "loan_approved": False,
                "message": "Loan not approved based on credit policy.",
                "monthly_installment": round(monthly_installment, 2),
            },
            status=status.HTTP_200_OK,
        )

    start_date = date.today()
    end_date = start_date + relativedelta(months=tenure)
    loan = Loan.objects.create(
        customer=customer,
        loan_amount=loan_amount,
        tenure=tenure,
        interest_rate=corrected_rate,
        monthly_repayment=monthly_installment,
        emis_paid_on_time=0,
        start_date=start_date,
        end_date=end_date,
    )

    customer.current_debt = int(get_current_debt_sum(customer))
    customer.save(update_fields=["current_debt"])

    return Response(
        {
            "loan_id": loan.loan_id,
            "customer_id": customer.customer_id,
            "loan_approved": True,
            "message": "Loan approved.",
            "monthly_installment": round(monthly_installment, 2),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def view_loan(request, loan_id):
    loan = get_object_or_404(Loan, loan_id=loan_id)
    customer = loan.customer

    return Response(
        {
            "loan_id": loan.loan_id,
            "customer": {
                "id": customer.customer_id,
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "phone_number": customer.phone_number,
                "age": customer.age,
            },
            "loan_amount": loan.loan_amount,
            "interest_rate": loan.interest_rate,
            "monthly_installment": round(loan.monthly_repayment, 2),
            "tenure": loan.tenure,
        }
    )


@api_view(["GET"])
def view_loans_by_customer(request, customer_id):
    customer = get_object_or_404(Customer, customer_id=customer_id)
    loans = Loan.objects.filter(customer=customer).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=date.today())
    )

    response = []
    for loan in loans:
        repayments_left = max(loan.tenure - loan.emis_paid_on_time, 0)
        response.append(
            {
                "loan_id": loan.loan_id,
                "loan_amount": loan.loan_amount,
                "interest_rate": loan.interest_rate,
                "monthly_installment": round(loan.monthly_repayment, 2),
                "repayments_left": repayments_left,
            }
        )

    return Response(response)
