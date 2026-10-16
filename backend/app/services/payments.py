"""Одобрение заявок: зачисление, кэшбэк, реферальные, уведомления."""
from app.core.notifications import notify_admin
from app.services import ledger

CASHBACK_MIN_MINOR = 100000      # от 1000 ₽
CASHBACK_PERCENT = 3             # +3% бонусом
REFERRAL_REWARD_MINOR = 5000     # 50 ₽ за приведённого друга


def approve_payreq(db, pr, actor_email: str = "system") -> None:
    wallet = ledger.get_wallet(db, pr.user_id)
    ledger.credit(db, wallet, pr.amount_minor, reason=f"payment_{pr.method}",
                  entity_type="payment_request", entity_id=pr.id,
                  idempotency_key=f"payreq:{pr.id}")
    pr.status = "approved"
    if pr.amount_minor >= CASHBACK_MIN_MINOR:
        bonus = int(pr.amount_minor * CASHBACK_PERCENT / 100)
        ledger.credit(db, wallet, bonus, reason="topup_cashback",
                      entity_type="payment_request", entity_id=pr.id,
                      idempotency_key=f"cashback:{pr.id}")
    from app.models import User
    user = db.get(User, pr.user_id)
    if user is not None and user.referred_by:
        rw = ledger.get_wallet(db, user.referred_by)
        ledger.credit(db, rw, REFERRAL_REWARD_MINOR, reason="referral_reward",
                      entity_type="user", entity_id=user.id,
                      idempotency_key=f"referral:{user.id}")
    notify_admin(db, f"✅ Заявка #{pr.id}: {(pr.amount_minor/100):.0f} ₽ зачислено ({pr.method}, одобрил: {actor_email})")
