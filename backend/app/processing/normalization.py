"""Versioned, locale-independent CSV value normalization."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

POLICY_VERSION = "normalize-v1"
DATE_FORMATS = {"%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"}
# Supported ISO 4217 alphabetic codes for normalize-v1. Adding codes changes the policy.
SUPPORTED_CURRENCIES = frozenset(
    """AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD
    BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR
    FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD
    JOD JPY KES KGS KHR KMF KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT
    MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG
    QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS
    TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER
    ZAR ZMW""".split()
)


class NormalizationIssue(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize(
    field: str, original: str, *, date_format: str | None, period_start: date, period_end: date
) -> date | str | int | Decimal:
    value = original.strip()
    if not value:
        raise NormalizationIssue(
            "blank_campaign_name" if field == "campaign_name" else "missing_value"
        )
    if field == "campaign_name":
        return value
    if field == "date":
        if date_format is not None and date_format not in DATE_FORMATS:
            raise NormalizationIssue("invalid_date")
        if date_format is None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise NormalizationIssue(
                "ambiguous_date"
                if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value)
                else "invalid_date"
            )
        try:
            parsed = datetime.strptime(value, date_format or "%Y-%m-%d").date()
        except ValueError as exc:
            raise NormalizationIssue("invalid_date") from exc
        if not period_start <= parsed <= period_end:
            raise NormalizationIssue("out_of_period")
        return parsed
    if field == "currency":
        code = value.upper()
        if code not in SUPPORTED_CURRENCIES:
            raise NormalizationIssue("unsupported_currency")
        return code
    if field in {"impressions", "clicks", "leads"}:
        if value.startswith("-") and re.fullmatch(r"-\d+", value):
            raise NormalizationIssue("negative_measure")
        if not re.fullmatch(r"\d+", value):
            raise NormalizationIssue("invalid_count")
        return int(value)
    if field == "spend":
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            raise NormalizationIssue("invalid_spend")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise NormalizationIssue("invalid_spend") from exc
        if not number.is_finite():
            raise NormalizationIssue("invalid_spend")
        if number < 0:
            raise NormalizationIssue("negative_measure")
        return number
    raise ValueError("unknown canonical field")
