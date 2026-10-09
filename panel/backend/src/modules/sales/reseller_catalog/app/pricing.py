from src.modules.sales.reseller_catalog.domain.dtos import AgreementPrice


class AgreementPricing:
    @staticmethod
    def quote(price: AgreementPrice, catalog_price_rial: int) -> int:
        numerator = catalog_price_rial
        denominator = 1
        if price.mode == "fixed":
            assert price.fixed_price_rial is not None
            numerator = price.fixed_price_rial
        elif price.mode == "discount":
            assert price.discount_bps is not None
            numerator *= 10_000 - price.discount_bps
            denominator = 10_000
        divisor = denominator * price.quantum_rial
        units, remainder = divmod(numerator, divisor)
        if price.rounding == "ceil" and remainder:
            units += 1
        elif price.rounding == "nearest" and remainder * 2 >= divisor:
            units += 1
        return units * price.quantum_rial
