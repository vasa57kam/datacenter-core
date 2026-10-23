"""Человеко-читаемые названия операций и способов (без служебных кодов в UI)."""
REASON_RU = {
    "topup_cashback": "Бонус за пополнение",
    "referral_reward": "Награда за друга",
    "promo_code": "Промокод",
    "gift_certificate": "Подарочный сертификат",
    "coupon": "Купон",
    "vpn_usage_second": "Использование канала, посекундно",
    "vpn_usage_minute": "Использование канала, поминутно",
    "vpn_traffic_gb": "Использованный трафик",
    "payment_cash": "Пополнение наличными",
    "payment_transfer": "Пополнение переводом",
    "payment_other": "Пополнение баланса",
    "service_activation_month": "Активация месячного тарифа",
    "service_activation_one_time": "Разовая оплата услуги",
    "adjustment": "Корректировка баланса",
    "dividend_accrual": "Начисление дивидендов",
    "dividend_payout": "Выплата дивидендов по реквизитам",
    "refund": "Возврат средств",
}
METHOD_RU = {"cash": "наличные", "transfer": "перевод на карту", "other": "другое"}
PAYREQ_RU = {"pending": "на проверке", "approved": "зачислено", "rejected": "отклонено"}

def ru_reason(r: str) -> str:
    if r in REASON_RU:
        return REASON_RU[r]
    if r.startswith("vpn_usage_"):
        return "Использование услуги"
    if r.startswith("payment_"):
        return "Пополнение баланса"
    if r.startswith("service_activation_"):
        return "Активация тарифа"
    return r.replace("_", " ").capitalize()

def ru_method(m: str) -> str:
    return METHOD_RU.get(m, m)

def ru_payreq(s: str) -> str:
    return PAYREQ_RU.get(s, s)


CODE_RU = {
    "cash": "наличные", "transfer": "перевод на карту", "other": "другое",
    "approved": "зачислено", "pending": "на проверке", "rejected": "отклонено",
    "debit": "списание", "credit": "зачисление",
    "active": "активна", "suspended": "приостановлена", "provisioning": "выдаётся",
    "terminated": "завершена", "closed": "закрыта",
}

def finalize_human(v):
    """Jinja finalize: служебные коды в выводе -> русский текст."""
    if isinstance(v, str):
        if v in CODE_RU:
            return CODE_RU[v]
        if v in REASON_RU:
            return REASON_RU[v]
    return v
