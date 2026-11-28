from tests.helpers import paid_event, signed_webhook


async def test_checkout_returns_the_payment_page_only_for_a_pending_order_of_the_owner(
    client, pending_order, user, other_user, stripe_mock
):
    url = f"/payments/orders/{pending_order['id']}/checkout/"

    ok = await client.post(url, headers=user.headers)
    assert ok.status_code == 200
    assert ok.json()["checkout_url"].startswith("https://checkout.stripe.test/")
    assert stripe_mock["checkout"] == [pending_order["id"]]

    assert (await client.post(url, headers=other_user.headers)).status_code == 404  # not their order
    await client.post(f"/orders/{pending_order['id']}/cancel/", headers=user.headers)
    assert (await client.post(url, headers=user.headers)).status_code == 400  # no longer pending


async def test_the_webhook_rejects_a_wrong_signature(client, pending_order):
    event = paid_event(pending_order["id"], 1499)

    forged = await client.post("/payments/webhook/", **signed_webhook(event, secret="whsec_not_ours"))
    unsigned = await client.post("/payments/webhook/", content=b"{}")

    assert forged.status_code == 400
    assert unsigned.status_code == 400


async def test_the_webhook_rejects_an_old_signed_request(client, pending_order, user):
    event = paid_event(pending_order["id"], 1499)

    r = await client.post("/payments/webhook/", **signed_webhook(event, age_seconds=3600))

    assert r.status_code == 400
    assert (await client.get("/orders/", headers=user.headers)).json()[0]["status"] == "pending"


async def test_a_confirmed_payment_pays_the_order_and_is_recorded(client, pending_order, user, outbox, catalog):
    outbox.clear()
    await client.post(f"/cart/movies/{catalog['Casino']}/", headers=user.headers)  # an extra movie, not in the order

    r = await client.post("/payments/webhook/", **signed_webhook(paid_event(pending_order["id"], 1499)))
    assert r.status_code == 200

    orders = (await client.get("/orders/", headers=user.headers)).json()
    assert orders[0]["status"] == "paid"

    payments = (await client.get("/payments/", headers=user.headers)).json()
    assert len(payments) == 1
    assert (payments[0]["status"], payments[0]["amount"]) == ("successful", "14.99")

    cart = (await client.get("/cart/", headers=user.headers)).json()["items"]
    assert [i["name"] for i in cart] == ["Casino"]  # the paid movies left the cart, the other stayed

    assert [m["subject"] for m in outbox] == ["Payment confirmation"]
    assert f"Order #{pending_order['id']}" in outbox[0]["body"]


async def test_a_replayed_webhook_changes_nothing(client, pending_order, user, outbox):
    event = paid_event(pending_order["id"], 1499)
    await client.post("/payments/webhook/", **signed_webhook(event))
    outbox.clear()

    await client.post("/payments/webhook/", **signed_webhook(event))

    assert len((await client.get("/payments/", headers=user.headers)).json()) == 1
    assert outbox == []


async def test_a_payment_of_the_wrong_amount_is_ignored(client, pending_order, user):
    await client.post("/payments/webhook/", **signed_webhook(paid_event(pending_order["id"], 1)))

    assert (await client.get("/orders/", headers=user.headers)).json()[0]["status"] == "pending"
    assert (await client.get("/payments/", headers=user.headers)).json() == []


async def test_a_moderator_can_refund_a_payment(client, pending_order, user, moderator, stripe_mock):
    await client.post("/payments/webhook/", **signed_webhook(paid_event(pending_order["id"], 1499, "pi_to_refund")))
    payment_id = (await client.get("/payments/", headers=user.headers)).json()[0]["id"]

    assert (await client.post(f"/payments/{payment_id}/refund/", headers=user.headers)).status_code == 403
    r = await client.post(f"/payments/{payment_id}/refund/", headers=moderator.headers)

    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert stripe_mock["refund"] == ["pi_to_refund"]
    assert (await client.get("/orders/", headers=user.headers)).json()[0]["status"] == "canceled"
    assert (await client.post(f"/payments/{payment_id}/refund/", headers=moderator.headers)).status_code == 400


async def test_replaying_a_payment_after_a_refund_does_not_revive_the_order(
    client, pending_order, user, moderator, stripe_mock
):
    event = paid_event(pending_order["id"], 1499, "pi_replayed")
    await client.post("/payments/webhook/", **signed_webhook(event))
    payment_id = (await client.get("/payments/", headers=user.headers)).json()[0]["id"]
    await client.post(f"/payments/{payment_id}/refund/", headers=moderator.headers)

    r = await client.post("/payments/webhook/", **signed_webhook(event))  # the same old event again

    assert r.status_code == 200
    assert (await client.get("/orders/", headers=user.headers)).json()[0]["status"] == "canceled"
    payments = (await client.get("/payments/", headers=user.headers)).json()
    assert [p["status"] for p in payments] == ["refunded"]


async def test_moderators_can_filter_all_payments(client, pending_order, user, moderator):
    await client.post("/payments/webhook/", **signed_webhook(paid_event(pending_order["id"], 1499)))

    everything = await client.get("/payments/all/", headers=moderator.headers)
    other_status = await client.get("/payments/all/", params={"status": "refunded"}, headers=moderator.headers)

    assert len(everything.json()) == 1
    assert other_status.json() == []
    assert (await client.get("/payments/all/", headers=user.headers)).status_code == 403
