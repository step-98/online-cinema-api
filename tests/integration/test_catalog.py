from tests.helpers import movie_payload


def names(response):
    return [item["name"] for item in response.json()["items"]]


async def test_catalog_pagination(client, catalog):
    page1 = await client.get("/movies/", params={"page": 1, "per_page": 2})
    page2 = await client.get("/movies/", params={"page": 2, "per_page": 2})

    assert names(page1) == ["Heat", "Ronin"]
    assert names(page2) == ["Casino"]
    assert page1.json()["total"] == 3


async def test_catalog_filters(client, catalog):
    by_year = await client.get("/movies/", params={"year": 1995})
    by_rating = await client.get("/movies/", params={"imdb_min": 8.25})
    both = await client.get("/movies/", params={"year": 1995, "imdb_min": 8.25})

    assert names(by_year) == ["Heat", "Casino"]
    assert names(by_rating) == ["Heat"]
    assert names(both) == ["Heat"]
    assert both.json()["total"] == 1  # the total follows the filters


async def test_catalog_sorting(client, catalog):
    cheapest_first = await client.get("/movies/", params={"sort_by": "price"})
    most_popular_first = await client.get("/movies/", params={"sort_by": "popularity", "order": "desc"})

    assert names(cheapest_first) == ["Ronin", "Casino", "Heat"]
    assert names(most_popular_first) == ["Heat", "Casino", "Ronin"]
    assert (await client.get("/movies/", params={"sort_by": "bogus"})).status_code == 422


async def test_catalog_search_by_title_star_and_director(client, catalog):
    by_title = await client.get("/movies/", params={"q": "heat"})
    by_star = await client.get("/movies/", params={"q": "de niro"})  # three movies, each listed once
    by_director = await client.get("/movies/", params={"q": "scorsese"})

    assert names(by_title) == ["Heat"]
    assert names(by_star) == ["Heat", "Ronin", "Casino"]
    assert names(by_director) == ["Casino"]


async def test_movie_details_and_duplicates(client, catalog, moderator):
    detail = await client.get(f"/movies/{catalog['Heat']}/")
    assert detail.status_code == 200
    assert sorted(g["name"] for g in detail.json()["genres"]) == ["Crime", "Drama"]
    assert detail.json()["certification"]["name"] == "R"

    assert (await client.get("/movies/9999/")).status_code == 404
    duplicate = await client.post("/movies/", json=movie_payload("Heat", 1995), headers=moderator.headers)
    assert duplicate.status_code == 409


async def test_genres_are_listed_with_the_number_of_movies(client, catalog):
    r = await client.get("/genres/")
    counts = {genre["name"]: genre["movies_count"] for genre in r.json()}
    assert counts == {"Action": 1, "Crime": 2, "Drama": 2}

    crime_id = next(g["id"] for g in r.json() if g["name"] == "Crime")
    by_genre = await client.get("/movies/", params={"genre_id": crime_id})
    assert names(by_genre) == ["Heat", "Casino"]


async def test_likes_and_ratings(client, catalog, user, other_user):
    movie = catalog["Heat"]

    await client.put(f"/movies/{movie}/like/", json={"is_like": True}, headers=user.headers)
    stats = (await client.put(f"/movies/{movie}/like/", json={"is_like": False}, headers=other_user.headers)).json()
    assert (stats["likes"], stats["dislikes"]) == (1, 1)

    # one reaction per user: changing it does not add a second one
    stats = (await client.put(f"/movies/{movie}/like/", json={"is_like": False}, headers=user.headers)).json()
    assert (stats["likes"], stats["dislikes"]) == (0, 2)

    await client.put(f"/movies/{movie}/rating/", json={"score": 8}, headers=user.headers)
    stats = (await client.put(f"/movies/{movie}/rating/", json={"score": 6}, headers=other_user.headers)).json()
    assert stats["average_rating"] == 7.0 and stats["ratings_count"] == 2
    assert (await client.put(f"/movies/{movie}/rating/", json={"score": 11}, headers=user.headers)).status_code == 422


async def test_favorites_support_the_same_search_filters_and_sorting(client, catalog, user, other_user):
    for name in ("Heat", "Ronin"):
        await client.post(f"/movies/{catalog[name]}/favorite/", headers=user.headers)

    everything = await client.get("/movies/favorites/", headers=user.headers)
    searched = await client.get("/movies/favorites/", params={"q": "ronin"}, headers=user.headers)
    sorted_ = await client.get("/movies/favorites/", params={"sort_by": "price", "order": "desc"}, headers=user.headers)

    assert names(everything) == ["Heat", "Ronin"]
    assert names(searched) == ["Ronin"]
    assert names(sorted_) == ["Heat", "Ronin"]
    assert (await client.get("/movies/favorites/", headers=other_user.headers)).json()["total"] == 0

    await client.delete(f"/movies/{catalog['Heat']}/favorite/", headers=user.headers)
    assert names(await client.get("/movies/favorites/", headers=user.headers)) == ["Ronin"]


async def test_a_reply_and_a_like_notify_the_author_of_the_comment(client, catalog, user, other_user):
    movie = catalog["Heat"]
    written = await client.post(f"/movies/{movie}/comments/", json={"text": "Great film"}, headers=user.headers)
    comment = written.json()

    reply = {"text": "Agree!", "parent_id": comment["id"]}
    await client.post(f"/movies/{movie}/comments/", json=reply, headers=other_user.headers)
    await client.post(f"/comments/{comment['id']}/like/", headers=other_user.headers)
    await client.post(f"/comments/{comment['id']}/like/", headers=user.headers)  # your own like notifies nobody

    notifications = (await client.get("/notifications/", headers=user.headers)).json()
    assert len(notifications) == 2
    assert (await client.get("/notifications/", headers=other_user.headers)).json() == []

    listed = (await client.get(f"/movies/{movie}/comments/")).json()
    assert next(c for c in listed if c["id"] == comment["id"])["likes_count"] == 2
