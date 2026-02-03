from datetime import date

import pandas as pd
from celery import shared_task
from django.conf import settings

from .models import Customer, Loan
from .services import calculate_emi, get_current_debt_sum


def _parse_date(value):
    if pd.isna(value):
        return None
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _get_value(row, *keys, default=None):
    for key in keys:
        if key in row and not pd.isna(row.get(key)):
            return row.get(key)
    return default


@shared_task
def ingest_initial_data():
    customer_file = settings.DATA_DIR / "customer_data.xlsx"
    loan_file = settings.DATA_DIR / "loan_data.xlsx"

    if customer_file.exists():
        customers_df = pd.read_excel(customer_file)
        for _, row in customers_df.iterrows():
            customer_id_value = _get_value(row, "customer_id", "customer id")
            if customer_id_value is None:
                continue
            Customer.objects.update_or_create(
                customer_id=int(customer_id_value),
                defaults={
                    "first_name": str(_get_value(row, "first_name", default="")).strip(),
                    "last_name": str(_get_value(row, "last_name", default="")).strip(),
                    "phone_number": str(_get_value(row, "phone_number", default="")).strip(),
                    "monthly_salary": int(_get_value(row, "monthly_salary", default=0)),
                    "approved_limit": int(_get_value(row, "approved_limit", default=0)),
                    "current_debt": int(_get_value(row, "current_debt", default=0)),
                },
            )

    if loan_file.exists():
        loans_df = pd.read_excel(loan_file)
        for _, row in loans_df.iterrows():
            customer_id_value = _get_value(row, "customer id", "customer_id")
            if customer_id_value is None:
                continue
            customer_id = int(customer_id_value)
            customer = Customer.objects.filter(customer_id=customer_id).first()
            if not customer:
                continue

            interest_rate = float(_get_value(row, "interest rate", "interest_rate", default=0))
            tenure = int(_get_value(row, "tenure", default=0))
            loan_amount = float(_get_value(row, "loan amount", "loan_amount", default=0))
            monthly_repayment = float(
                _get_value(row, "monthly repayment", "monthly_repayment", default=0)
            )
            if monthly_repayment == 0 and loan_amount and tenure:
                monthly_repayment = calculate_emi(loan_amount, interest_rate, tenure)

            Loan.objects.update_or_create(
                loan_id=int(_get_value(row, "loan id", "loan_id")),
                defaults={
                    "customer": customer,
                    "loan_amount": loan_amount,
                    "tenure": tenure,
                    "interest_rate": interest_rate,
                    "monthly_repayment": monthly_repayment,
                    "emis_paid_on_time": int(
                        _get_value(row, "EMIs paid on time", "emis_paid_on_time", default=0)
                    ),
                    "start_date": _parse_date(_get_value(row, "start date", "start_date")),
                    "end_date": _parse_date(_get_value(row, "end date", "end_date")),
                },
            )

    for customer in Customer.objects.all():
        customer.current_debt = int(get_current_debt_sum(customer))
        customer.save(update_fields=["current_debt"])
