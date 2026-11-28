from tests.helpers import mail_params, movie_payload, paid_event, signed_webhook


async def test_from_registration_to_a_paid_movie(client, outbox, moderator, stripe_mock):
    outbox.clear()
    email, password = "viewer@example.com", "Passw0rd!"
    assert (await client.post("/accounts/register/", json={"email": email, "password": password})).status_code == 201
    token = mail_params(outbox[-1])["token"][0]
    assert (await client.post("/accounts/activate/", json={"email": email, "token": token})).status_code == 200
    login = await client.post("/accounts/login/", json={"email": email, "password": password})
    assert login.status_code == 200
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}

    heat_payload = movie_payload("Heat", 1995, "9.99", stars=("Al Pacino",))
    ronin_payload = movie_payload("Ronin", 1998, "5.00", stars=("Jean Reno",))
    heat = (await client.post("/movies/", json=heat_payload, headers=moderator.headers)).json()["id"]
    await client.post("/movies/", json=ronin_payload, headers=moderator.headers)

    found = await client.get("/movies/", params={"q": "pacino", "year": 1995})
    assert [m["name"] for m in found.json()["items"]] == ["Heat"]
    assert (await client.get(f"/movies/{heat}/")).json()["price"] == "9.99"

    assert (await client.post(f"/cart/movies/{heat}/", headers=viewer)).status_code == 201
    order = (await client.post("/orders/", headers=viewer)).json()
    assert order["status"] == "pending" and order["total_amount"] == "9.99"

    checkout = await client.post(f"/payments/orders/{order['id']}/checkout/", headers=viewer)
    assert checkout.status_code == 200 and checkout.json()["checkout_url"].startswith("https://")
    outbox.clear()
    assert (await client.post("/payments/webhook/", **signed_webhook(paid_event(order["id"], 999)))).status_code == 200

    assert (await client.get("/orders/", headers=viewer)).json()[0]["status"] == "paid"
    assert (await client.get("/payments/", headers=viewer)).json()[0]["status"] == "successful"
    assert [m["subject"] for m in outbox] == ["Payment confirmation"]
    assert (await client.get("/cart/", headers=viewer)).json() == {"items": []}

    again = await client.post(f"/cart/movies/{heat}/", headers=viewer)
    assert again.status_code == 409
    assert (await client.delete(f"/movies/{heat}/", headers=moderator.headers)).status_code == 409
