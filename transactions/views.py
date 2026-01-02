from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, ListView
from django.http import HttpResponse
from datetime import datetime
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from transactions.constants import DEPOSIT, WITHDRAWAL, LOAN, LOAN_PAID
from transactions.forms import DepositForm, WithdrawForm, LoanRequestForm
from transactions.models import Transaction


import os


def send_transaction_email(user, amount, subject, template):
    """Send email safely"""
    if os.environ.get("DEBUG_EMAIL") == "1":
        print(f"[DEBUG EMAIL] {subject} to {user.email}, amount: {amount}")
        return
    if not user.email:
        print("[Email Skipped] User has no email")
        return
    try:
        message = render_to_string(template, {"user": user, "amount": amount})
        send_email = EmailMultiAlternatives(subject, "", to=[user.email])
        send_email.attach_alternative(message, "text/html")
        send_email.send()
    except Exception as e:
        print(f"[Email Error] Could not send email to {user.email}: {e}")


class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    model = Transaction
    template_name = "transactions/transaction_form.html"
    success_url = reverse_lazy("transaction_report")
    title = ""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["account"] = self.request.user.account
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        return context


class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = "Deposit"

    def get_initial(self):
        return {"transaction_type": DEPOSIT}

    def form_valid(self, form):
        amount = form.cleaned_data["amount"]
        account = self.request.user.account

        try:
            account.balance += amount
            account.save(update_fields=["balance"])

            messages.success(
                self.request,
                f"{amount:,.2f}$ was deposited successfully",
            )
            send_transaction_email(
                self.request.user,
                amount,
                "Deposit Message",
                "transactions/deposite_email.html",
            )
        except Exception as e:
            messages.error(self.request, f"Deposit failed: {e}")
            return redirect("transaction_report")

        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = "Withdraw Money"

    def get_initial(self):
        return {"transaction_type": WITHDRAWAL}

    def form_valid(self, form):
        amount = form.cleaned_data["amount"]
        account = self.request.user.account

        account.balance -= amount
        account.save(update_fields=["balance"])

        messages.success(
            self.request,
            f"{amount:,.2f}$ withdrawn successfully",
        )
        send_transaction_email(
            self.request.user,
            amount,
            "Withdrawal Message",
            "transactions/withdrawal_email.html",
        )
        return super().form_valid(form)


class LoanRequestView(TransactionCreateMixin):
    form_class = LoanRequestForm
    title = "Request For Loan"

    def get_initial(self):
        return {"transaction_type": LOAN}

    def form_valid(self, form):
        amount = form.cleaned_data["amount"]
        account = self.request.user.account

        loan_count = Transaction.objects.filter(
            account=account,
            transaction_type=LOAN,
            loan_approve=True,
        ).count()

        if loan_count >= 3:
            return HttpResponse("You have crossed the loan limit")

        messages.success(
            self.request,
            f"Loan request of {amount:,.2f}$ submitted successfully",
        )
        send_transaction_email(
            self.request.user,
            amount,
            "Loan Request Message",
            "transactions/loan_email.html",
        )
        return super().form_valid(form)


class TransactionReportView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "transactions/transaction_report.html"

    def get_queryset(self):
        queryset = Transaction.objects.filter(account=self.request.user.account)

        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")

        if start_date and end_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

            queryset = queryset.filter(timestamp__date__range=(start, end))

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["account"] = self.request.user.account
        return context


class PayLoanView(LoginRequiredMixin, View):
    def get(self, request, loan_id):
        loan = get_object_or_404(Transaction, id=loan_id)
        account = loan.account

        if loan.loan_approve:
            if account.balance >= loan.amount:
                try:
                    account.balance -= loan.amount
                    account.save(update_fields=["balance"])

                    loan.transaction_type = LOAN_PAID
                    loan.balance_after_transaction = account.balance
                    loan.save()
                except Exception as e:
                    messages.error(request, f"Loan payment failed: {e}")
            else:
                messages.error(request, "Insufficient balance")

        return redirect("loan_list")


class LoanListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "transactions/loan_request.html"
    context_object_name = "loans"

    def get_queryset(self):
        return Transaction.objects.filter(
            account=self.request.user.account,
            transaction_type=LOAN,
        )
