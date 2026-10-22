"""Одобрение заявок: зачисление, кэшбэк, реферальные, уведомления."""
from app.core.notifications import notify_admin
from app.services import ledger

CASHBACK_MIN_MINOR = 100000      # дефолт, если настройка не задана
CASHBACK_PERCENT = 3
REFERRAL_REWARD_MINOR = 5000

from app.core.settings_svc import get_setting as _gs_promo

def _cb_percent(db) -> int:
    try: return max(0, min(100, int(_gs_promo(db, "cashback_percent", str(CASHBACK_PERCENT)))))
    except ValueError: return CASHBACK_PERCENT

def _cb_min_minor(db) -> int:
    try: return max(0, int(_gs_promo(db, "cashback_min_minor", str(CASHBACK_MIN_MINOR))))
    except ValueError: return CASHBACK_MIN_MINOR

def _ref_reward(db) -> int:
    try: return max(0, int(_gs_promo(db, "referral_reward_minor", str(REFERRAL_REWARD_MINOR))))
    except ValueError: return REFERRAL_REWARD_MINOR


def approve_payreq(db, pr, actor_email: str = "system") -> None:
    wallet = ledger.get_wallet(db, pr.user_id)
    ledger.credit(db, wallet, pr.amount_minor, reason=f"payment_{pr.method}",
                  entity_type="payment_request", entity_id=pr.id,
                  idempotency_key=f"payreq:{pr.id}")
    pr.status = "approved"
    _cbp = _cb_percent(db)
    if _cbp > 0 and pr.amount_minor >= _cb_min_minor(db):
        bonus = int(pr.amount_minor * _cbp / 100)
        ledger.credit(db, wallet, bonus, reason="topup_cashback",
                      entity_type="payment_request", entity_id=pr.id,
                      idempotency_key=f"cashback:{pr.id}")
    from app.models import User
    user = db.get(User, pr.user_id)
    _rr = _ref_reward(db)
    if _rr > 0 and user is not None and user.referred_by:
        rw = ledger.get_wallet(db, user.referred_by)
        ledger.credit(db, rw, _rr, reason="referral_reward",
                      entity_type="user", entity_id=user.id,
                      idempotency_key=f"referral:{user.id}")
    notify_admin(db, f"✅ Заявка #{pr.id}: {(pr.amount_minor/100):.0f} ₽ зачислено ({pr.method}, одобрил: {actor_email})")
