from __future__ import annotations

from app.database.models import AuthUser


def normalize_email(email: str) -> str:
    email = email.lower().strip()
    local, _, domain = email.partition("@")
    if not domain:
        return email
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+")[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def _email_local_part(email: str) -> str:
    return email.lower().split("@")[0]


def _simple_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0

    a_bigrams = [a[index : index + 2] for index in range(len(a) - 1)]
    b_bigrams = [b[index : index + 2] for index in range(len(b) - 1)]
    if not a_bigrams or not b_bigrams:
        return 0.0

    available = list(b_bigrams)
    overlap = 0
    for bigram in a_bigrams:
        if bigram in available:
            overlap += 1
            available.remove(bigram)
    return (2.0 * overlap) / (len(a_bigrams) + len(b_bigrams))


def check_referral_fraud(
    referrer: AuthUser, referee: AuthUser
) -> tuple[bool, str | None]:
    if referrer.id == referee.id:
        return False, "self_referral"

    referrer_email = str(referrer.email).lower()
    referee_email = str(referee.email).lower()
    if normalize_email(referrer_email) == normalize_email(referee_email):
        return False, "normalized_email_match"

    referrer_local = _email_local_part(referrer_email)
    referee_local = _email_local_part(referee_email)
    similarity = _simple_similarity(referrer_local, referee_local)
    if similarity >= 0.85 and referrer_local != referee_local:
        return False, f"similar_email_local_part:{similarity:.2f}"
    return True, None
