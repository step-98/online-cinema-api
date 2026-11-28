from tests.helpers import movie_payload


async def test_only_moderators_and_admins_can_create_movies(client, user, moderator, admin):
    assert (await client.post("/movies/", json=movie_payload())).status_code in (401, 403)
    assert (await client.post("/movies/", json=movie_payload(), headers=user.headers)).status_code == 403
    assert (await client.post("/movies/", json=movie_payload(), headers=moderator.headers)).status_code == 201
    r = await client.post("/movies/", json=movie_payload("Ronin", 1998), headers=admin.headers)
    assert r.status_code == 201


async def test_only_admins_can_change_a_users_group(client, user, moderator, admin):
    url = f"/admin/users/{user.id}/group/"
    body = {"group": "moderator"}

    assert (await client.patch(url, json=body, headers=user.headers)).status_code == 403
    assert (await client.patch(url, json=body, headers=moderator.headers)).status_code == 403
    assert (await client.patch(url, json=body, headers=admin.headers)).status_code == 200

    assert (await client.post("/movies/", json=movie_payload(), headers=user.headers)).status_code == 201


async def test_an_admin_can_activate_an_account_manually(client, admin):
    r = await client.post("/accounts/register/", json={"email": "manual@example.com", "password": "Passw0rd!"})
    user_id = r.json()["id"]

    assert (await client.post(f"/admin/users/{user_id}/activate/", headers=admin.headers)).status_code == 200
    login = await client.post("/accounts/login/", json={"email": "manual@example.com", "password": "Passw0rd!"})
    assert login.status_code == 200


async def test_only_moderators_can_look_into_a_users_cart(client, user, moderator):
    url = f"/cart/users/{user.id}/"

    assert (await client.get(url, headers=user.headers)).status_code == 403
    assert (await client.get(url, headers=moderator.headers)).status_code == 200
