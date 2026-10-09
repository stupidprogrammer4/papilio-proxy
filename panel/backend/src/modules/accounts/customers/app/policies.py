from src.modules.accounts.customers.domain.models import CustomerModel


class CustomerAccessPolicy:
    @staticmethod
    def services_available(customer: CustomerModel) -> bool:
        return customer.services_enabled and not customer.service_hold_pending

    @staticmethod
    def renewals_available(customer: CustomerModel) -> bool:
        return (
            CustomerAccessPolicy.services_available(customer)
            and customer.renewals_enabled
        )
