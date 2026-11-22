from tests.helpers import mail_params, movie_payload, paid_event, signed_webhook


async def test_from_registration_to_a_paid_movie(client, outbox, moderator, stripe_mock):
    """One complete story, told only through the public API."""
    # 1. A visitor registers, activates the account with the e-mailed token and logs in.
    outbox.clear()
    email, password = "viewer@example.com", "Passw0rd!"
    assert (await client.post("/accounts/register/", json={"email": email, "password": password})).status_code == 201
    token = mail_params(outbox[-1])["token"][0]
    assert (await client.post("/accounts/activate/", json={"email": email, "token": token})).status_code == 200
    login = await client.post("/accounts/login/", json={"email": email, "password": password})
    assert login.status_code == 200
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 2. A moderator fills the catalog.
    heat_payload = movie_payload("Heat", 1995, "9.99", stars=("Al Pacino",))
    ronin_payload = movie_payload("Ronin", 1998, "5.00", stars=("Jean Reno",))
    heat = (await client.post("/movies/", json=heat_payload, headers=moderator.headers)).json()["id"]
    await client.post("/movies/", json=ronin_payload, headers=moderator.headers)

    # 3. The viewer finds a movie by actor and by year, then reads its details.
    found = await client.get("/movies/", params={"q": "pacino", "year": 1995})
    assert [m["name"] for m in found.json()["items"]] == ["Heat"]
    assert (await client.get(f"/movies/{heat}/")).json()["price"] == "9.99"

    # 4. They put it in the cart and place an order.
    assert (await client.post(f"/cart/movies/{heat}/", headers=viewer)).status_code == 201
    order = (await client.post("/orders/", headers=viewer)).json()
    assert order["status"] == "pending" and order["total_amount"] == "9.99"

    # 5. They are sent to the payment page; Stripe then confirms the payment through the webhook.
    checkout = await client.post(f"/payments/orders/{order['id']}/checkout/", headers=viewer)
    assert checkout.status_code == 200 and checkout.json()["checkout_url"].startswith("https://")
    outbox.clear()
    assert (await client.post("/payments/webhook/", **signed_webhook(paid_event(order["id"], 999)))).status_code == 200

    # 6. The order is paid, the payment is in their history, and a confirmation e-mail was sent.
    assert (await client.get("/orders/", headers=viewer)).json()[0]["status"] == "paid"
    assert (await client.get("/payments/", headers=viewer)).json()[0]["status"] == "successful"
    assert [m["subject"] for m in outbox] == ["Payment confirmation"]
    assert (await client.get("/cart/", headers=viewer)).json() == {"items": []}

    # 7. A purchased movie cannot be bought again, nor deleted from the catalog.
    again = await client.post(f"/cart/movies/{heat}/", headers=viewer)
    assert again.status_code == 409
    assert (await client.delete(f"/movies/{heat}/", headers=moderator.headers)).status_code == 409
