from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StaffCustomerAccessActor:
    staff_id: int


@dataclass(frozen=True, slots=True)
class ResellerCustomerAccessActor:
    reseller_id: int
    account_id: int


CustomerAccessActor = StaffCustomerAccessActor | ResellerCustomerAccessActor
