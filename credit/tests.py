from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status

from .models import Customer, Loan
from .services import (
    calculate_emi,
    round_to_lakh,
    compute_credit_score,
    minimum_rate_for_score,
    evaluate_eligibility,
    get_current_debt_sum,
)


class ServiceTests(TestCase):
    """Tests for credit service functions."""

    def test_round_to_lakh(self):
        self.assertEqual(round_to_lakh(150000), 200000)
        self.assertEqual(round_to_lakh(149999), 100000)
        self.assertEqual(round_to_lakh(100000), 100000)
        self.assertEqual(round_to_lakh(3600000), 3600000)

    def test_calculate_emi_basic(self):
        # 100000 at 12% for 12 months
        emi = calculate_emi(100000, 12, 12)
        self.assertAlmostEqual(emi, 8884.88, places=2)

    def test_calculate_emi_zero_rate(self):
        emi = calculate_emi(12000, 0, 12)
        self.assertEqual(emi, 1000.0)

    def test_calculate_emi_zero_tenure(self):
        emi = calculate_emi(100000, 12, 0)
        self.assertEqual(emi, 0.0)

    def test_minimum_rate_for_score(self):
        self.assertEqual(minimum_rate_for_score(60), 0.0)
        self.assertEqual(minimum_rate_for_score(50), 12.0)
        self.assertEqual(minimum_rate_for_score(30), 16.0)
        self.assertIsNone(minimum_rate_for_score(10))

    def test_compute_credit_score_no_loans(self):
        customer = Customer.objects.create(
            first_name="Test",
            last_name="User",
            phone_number="1234567890",
            monthly_salary=50000,
            approved_limit=1800000,
        )
        score = compute_credit_score(customer)
        self.assertEqual(score, 0)

    def test_compute_credit_score_with_loans(self):
        customer = Customer.objects.create(
            first_name="Test",
            last_name="User",
            phone_number="1234567890",
            monthly_salary=50000,
            approved_limit=1800000,
        )
        Loan.objects.create(
            customer=customer,
            loan_amount=100000,
            tenure=12,
            interest_rate=12,
            monthly_repayment=8885,
            emis_paid_on_time=12,
            start_date=date.today() - timedelta(days=365),
            end_date=date.today() - timedelta(days=1),
        )
        score = compute_credit_score(customer)
        self.assertGreater(score, 0)

    def test_evaluate_eligibility_approved(self):
        customer = Customer.objects.create(
            first_name="Test",
            last_name="User",
            phone_number="1234567890",
            monthly_salary=100000,
            approved_limit=3600000,
        )
        # Add a past loan with good history
        Loan.objects.create(
            customer=customer,
            loan_amount=100000,
            tenure=12,
            interest_rate=12,
            monthly_repayment=8885,
            emis_paid_on_time=12,
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() - timedelta(days=30),
        )
        result = evaluate_eligibility(customer, 200000, 12, 24)
        self.assertIn("approved", result)
        self.assertIn("score", result)


class CustomerAPITests(APITestCase):
    """Tests for customer registration API."""

    def test_register_customer_success(self):
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "age": 30,
            "monthly_income": 50000,
            "phone_number": "9876543210",
        }
        response = self.client.post("/register", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("customer_id", response.data)
        self.assertEqual(response.data["approved_limit"], 1800000)

    def test_register_customer_missing_fields(self):
        data = {"first_name": "John"}
        response = self.client.post("/register", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)


class LoanAPITests(APITestCase):
    """Tests for loan-related APIs."""

    def setUp(self):
        self.customer = Customer.objects.create(
            first_name="Jane",
            last_name="Doe",
            phone_number="1111111111",
            age=28,
            monthly_salary=100000,
            approved_limit=3600000,
        )
        # Add loan history for credit score
        Loan.objects.create(
            customer=self.customer,
            loan_amount=100000,
            tenure=12,
            interest_rate=12,
            monthly_repayment=8885,
            emis_paid_on_time=12,
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() - timedelta(days=30),
        )

    def test_check_eligibility(self):
        data = {
            "customer_id": self.customer.customer_id,
            "loan_amount": 200000,
            "interest_rate": 15,
            "tenure": 24,
        }
        response = self.client.post("/check-eligibility", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("approval", response.data)
        self.assertIn("monthly_installment", response.data)

    def test_check_eligibility_invalid_customer(self):
        data = {
            "customer_id": 99999,
            "loan_amount": 200000,
            "interest_rate": 15,
            "tenure": 24,
        }
        response = self.client.post("/check-eligibility", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_loan_success(self):
        data = {
            "customer_id": self.customer.customer_id,
            "loan_amount": 200000,
            "interest_rate": 15,
            "tenure": 24,
        }
        response = self.client.post("/create-loan", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["loan_approved"])
        self.assertIsNotNone(response.data["loan_id"])

    def test_view_loan(self):
        loan = Loan.objects.create(
            customer=self.customer,
            loan_amount=300000,
            tenure=36,
            interest_rate=14,
            monthly_repayment=10250,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1080),
        )
        response = self.client.get(f"/view-loan/{loan.loan_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["loan_id"], loan.loan_id)
        self.assertEqual(response.data["loan_amount"], 300000)

    def test_view_loans_by_customer(self):
        Loan.objects.create(
            customer=self.customer,
            loan_amount=150000,
            tenure=18,
            interest_rate=13,
            monthly_repayment=9500,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=540),
        )
        response = self.client.get(f"/view-loans/{self.customer.customer_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 1)

    def test_view_loan_not_found(self):
        response = self.client.get("/view-loan/99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
