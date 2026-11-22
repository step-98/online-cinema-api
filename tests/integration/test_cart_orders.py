async def test_cart_add_view_remove_and_clear(client, catalog, user):
    first = await client.post(f"/cart/movies/{catalog['Heat']}/", headers=user.headers)
    assert first.status_code == 201
    item = first.json()["items"][0]
    assert (item["name"], item["price"], item["year"]) == ("Heat", "9.99", 1995)
    assert sorted(item["genres"]) == ["Crime", "Drama"]

    assert (await client.post(f"/cart/movies/{catalog['Heat']}/", headers=user.headers)).status_code == 409
    assert (await client.post("/cart/movies/9999/", headers=user.headers)).status_code == 404

    await client.post(f"/cart/movies/{catalog['Ronin']}/", headers=user.headers)
    removed = await client.delete(f"/cart/movies/{catalog['Heat']}/", headers=user.headers)
    assert [i["name"] for i in removed.json()["items"]] == ["Ronin"]
    assert (await client.delete(f"/cart/movies/{catalog['Heat']}/", headers=user.headers)).status_code == 404

    assert (await client.delete("/cart/", headers=user.headers)).status_code == 200
    assert (await client.get("/cart/", headers=user.headers)).json() == {"items": []}


async def test_carts_are_private(client, catalog, user, other_user):
    await client.post(f"/cart/movies/{catalog['Heat']}/", headers=user.headers)

    assert (await client.get("/cart/", headers=other_user.headers)).json() == {"items": []}


async def test_an_order_cannot_be_placed_from_an_empty_cart(client, user):
    assert (await client.post("/orders/", headers=user.headers)).status_code == 400


async def test_an_order_is_pending_and_keeps_the_prices_of_that_moment(client, pending_order, catalog, moderator, user):
    assert pending_order["status"] == "pending"
    assert pending_order["total_amount"] == "14.99"
    assert [(i["name"], i["price"]) for i in pending_order["items"]] == [("Heat", "9.99"), ("Ronin", "5.00")]

    # a later price change must not touch an existing order
    await client.patch(f"/movies/{catalog['Heat']}/", json={"price": "99.00"}, headers=moderator.headers)
    mine = (await client.get("/orders/", headers=user.headers)).json()
    assert mine[0]["items"][0]["price"] == "9.99"
    assert mine[0]["total_amount"] == "14.99"


async def test_the_same_movies_cannot_be_ordered_twice_while_pending(client, pending_order, user):
    r = await client.post("/orders/", headers=user.headers)

    assert r.status_code == 409


async def test_a_canceled_order_can_be_replaced_by_a_new_one(client, pending_order, user, other_user):
    assert (await client.post(f"/orders/{pending_order['id']}/cancel/", headers=other_user.headers)).status_code == 404
    assert (await client.post(f"/orders/{pending_order['id']}/cancel/", headers=user.headers)).status_code == 200
    assert (await client.post(f"/orders/{pending_order['id']}/cancel/", headers=user.headers)).status_code == 400

    assert (await client.post("/orders/", headers=user.headers)).status_code == 201


async def test_moderators_can_filter_all_orders(client, pending_order, user, moderator):
    by_user = await client.get("/orders/all/", params={"user_id": user.id}, headers=moderator.headers)
    pending = await client.get("/orders/all/", params={"status": "pending"}, headers=moderator.headers)
    paid = await client.get("/orders/all/", params={"status": "paid"}, headers=moderator.headers)

    assert len(by_user.json()) == len(pending.json()) == 1
    assert paid.json() == []
    assert (await client.get("/orders/all/", headers=user.headers)).status_code == 403
