import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qs, urlparse

WEBHOOK_SECRET = "whsec_test"


def movie_payload(
    name="Heat",
    year=1995,
    price="9.99",
    imdb=8.3,
    votes=700,
    genres=("Drama", "Crime"),
    stars=("Al Pacino",),
    directors=("Michael Mann",),
    description="A crime story.",
):
    return {
        "name": name,
        "year": year,
        "time": 120,
        "imdb": imdb,
        "votes": votes,
        "description": description,
        "price": price,
        "certification": "R",
        "genres": list(genres),
        "stars": list(stars),
        "directors": list(directors),
    }


def mail_params(mail: dict) -> dict:
    link = re.search(r"http\S+", mail["body"]).group(0)
    return parse_qs(urlparse(link).query)


def signed_webhook(event: dict, secret: str = WEBHOOK_SECRET, age_seconds: int = 0) -> dict:
    payload = json.dumps(event).encode()
    timestamp = int(time.time()) - age_seconds
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return {
        "content": payload,
        "headers": {"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"},
    }


def paid_event(order_id: int, amount_cents: int, payment_intent: str = "pi_test_1") -> dict:
    return {
        "id": "evt_test",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{payment_intent}",
                "payment_intent": payment_intent,
                "payment_status": "paid",
                "amount_total": amount_cents,
                "metadata": {"order_id": str(order_id)},
            }
        },
    }
