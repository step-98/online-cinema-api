from tests.helpers import mail_params

REGISTER = "/accounts/register/"


async def test_registration_sends_an_activation_mail(client, outbox):
    r = await client.post(REGISTER, json={"email": "New@Example.com", "password": "Passw0rd!"})

    assert r.status_code == 201
    assert r.json()["email"] == "new@example.com"  # stored in lower case
    assert len(outbox) == 1
    assert outbox[0]["to"] == "new@example.com"
    assert outbox[0]["subject"] == "Activate your account"


async def test_the_same_email_cannot_register_twice_whatever_the_case(client, make_user):
    await make_user("dup@example.com")

    r = await client.post(REGISTER, json={"email": "DUP@example.com", "password": "Passw0rd!"})

    assert r.status_code == 409


async def test_a_weak_password_is_rejected(client):
    r = await client.post(REGISTER, json={"email": "weak@example.com", "password": "weak"})

    assert r.status_code == 422


async def test_login_is_refused_until_the_account_is_activated(client):
    await client.post(REGISTER, json={"email": "late@example.com", "password": "Passw0rd!"})

    r = await client.post("/accounts/login/", json={"email": "late@example.com", "password": "Passw0rd!"})

    assert r.status_code == 403


async def test_activation_needs_the_right_token(client, outbox):
    await client.post(REGISTER, json={"email": "act@example.com", "password": "Passw0rd!"})
    token = mail_params(outbox[-1])["token"][0]

    wrong = await client.post("/accounts/activate/", json={"email": "act@example.com", "token": "wrong"})
    right = await client.post("/accounts/activate/", json={"email": "act@example.com", "token": token})
    reused = await client.post("/accounts/activate/", json={"email": "act@example.com", "token": token})

    assert wrong.status_code == 400
    assert right.status_code == 200
    assert reused.status_code == 400  # the token is spent


async def test_a_wrong_password_and_an_unknown_email_look_the_same(client, user):
    wrong_password = await client.post("/accounts/login/", json={"email": user.email, "password": "Wrong0Pass!"})
    unknown_email = await client.post("/accounts/login/", json={"email": "nobody@example.com", "password": "Passw0rd!"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_the_refresh_token_gives_a_working_access_token(client, user):
    r = await client.post("/accounts/refresh/", json={"refresh_token": user.refresh_token})
    assert r.status_code == 200

    protected = await client.get("/cart/", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert protected.status_code == 200


async def test_logout_revokes_the_refresh_token(client, user):
    r = await client.post("/accounts/logout/", json={"refresh_token": user.refresh_token})
    assert r.status_code == 200

    again = await client.post("/accounts/refresh/", json={"refresh_token": user.refresh_token})
    assert again.status_code == 401


async def test_protected_endpoints_need_a_valid_token(client):
    assert (await client.get("/cart/")).status_code in (401, 403)
    assert (await client.get("/cart/", headers={"Authorization": "Bearer garbage"})).status_code == 401


async def test_change_password(client, user):
    wrong_old = await client.post(
        "/accounts/change-password/",
        json={"old_password": "Wrong0Pass!", "new_password": "NewPassw0rd!"},
        headers=user.headers,
    )
    assert wrong_old.status_code == 400

    ok = await client.post(
        "/accounts/change-password/",
        json={"old_password": user.password, "new_password": "NewPassw0rd!"},
        headers=user.headers,
    )
    assert ok.status_code == 200

    old_login = await client.post("/accounts/login/", json={"email": user.email, "password": user.password})
    new_login = await client.post("/accounts/login/", json={"email": user.email, "password": "NewPassw0rd!"})
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_resending_replaces_the_activation_token(client, outbox):
    email = "resend@example.com"
    await client.post(REGISTER, json={"email": email, "password": "Passw0rd!"})
    first = mail_params(outbox[-1])["token"][0]

    r = await client.post("/accounts/activate/resend/", json={"email": email})
    second = mail_params(outbox[-1])["token"][0]

    assert r.status_code == 200
    assert second != first
    assert (await client.post("/accounts/activate/", json={"email": email, "token": first})).status_code == 400
    assert (await client.post("/accounts/activate/", json={"email": email, "token": second})).status_code == 200


async def test_password_reset_flow(client, user, outbox):
    outbox.clear()
    r = await client.post("/accounts/password-reset/request/", json={"email": user.email})
    assert r.status_code == 200
    assert len(outbox) == 1 and outbox[0]["subject"] == "Reset your password"
    token = mail_params(outbox[0])["token"][0]

    body = {"email": user.email, "token": token, "password": "NewPassw0rd!"}
    assert (await client.post("/accounts/password-reset/complete/", json=body)).status_code == 200
    assert (await client.post("/accounts/password-reset/complete/", json=body)).status_code == 400  # token is spent

    new_login = await client.post("/accounts/login/", json={"email": user.email, "password": "NewPassw0rd!"})
    old_login = await client.post("/accounts/login/", json={"email": user.email, "password": user.password})
    assert new_login.status_code == 200
    assert old_login.status_code == 401


async def test_password_reset_request_does_not_reveal_whether_an_email_exists(client, user, outbox):
    outbox.clear()
    known = await client.post("/accounts/password-reset/request/", json={"email": user.email})
    outbox.clear()
    unknown = await client.post("/accounts/password-reset/request/", json={"email": "nobody@example.com"})

    assert known.json() == unknown.json()
    assert outbox == []
