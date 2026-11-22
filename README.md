# Online Cinema

Бекенд онлайн-кінотеатру на FastAPI: реєстрація з активацією через пошту, JWT-авторизація, каталог фільмів із
пошуком і фільтрами, кошик, замовлення та оплата через Stripe.

## Можливості

- **Акаунти.** Реєстрація, лист із посиланням активації, повторне надсилання токена, вхід (пара JWT: access і
  refresh), оновлення токена, вихід (refresh-токен відкликається), зміна пароля, скидання забутого пароля через пошту.
  Три ролі: користувач, модератор, адміністратор (кожна наступна успадковує права попередньої).
- **Каталог.** Пагінація, фільтри (рік, рейтинг IMDb, жанр), сортування (ціна, рік виходу, популярність), пошук за
  назвою, описом, актором і режисером. Лайки й дизлайки, оцінки 1–10, улюблені (із тими самими фільтрами),
  коментарі з відповідями, лайки коментарів, сповіщення про відповіді й лайки, список жанрів із кількістю фільмів.
- **Модератор.** Створення, зміна й видалення фільмів, керування жанрами й акторами. Фільм, який хтось купив,
  видалити не можна.
- **Кошик і замовлення.** Куплений фільм не можна додати в кошик чи замовити вдруге. Ціна фіксується на момент
  замовлення. Скасувати можна лише замовлення, яке ще не оплачене.
- **Платежі.** Stripe Checkout, підтвердження оплати через вебхук (з перевіркою підпису), історія платежів,
  повернення коштів модератором, лист із підтвердженням оплати.
- **Фонові задачі.** Celery з Redis: відправка листів і періодичне видалення прострочених токенів активації (`celery-beat`).
- **Документація API.** Swagger UI, ReDoc і схема OpenAPI доступні лише авторизованим користувачам.

## Стек

Python 3.12, FastAPI, SQLAlchemy 2 (async) з asyncpg, PostgreSQL 16, Alembic, Celery + Redis, Stripe,
Poetry, Docker Compose, pytest, black, flake8, mypy, GitHub Actions. Для розробки в Compose також є MailHog
(перехоплює листи) і MinIO (S3-сховище).

## Швидкий старт (Docker)

Потрібен запущений Docker Desktop.

1. Скопіюй `.env.example` у `.env` і заповни значення (список змінних нижче). Секрети для JWT можна згенерувати так
   (виконай двічі, для двох ключів):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Запусти все однією командою:
   ```
   docker compose up --build
   ```
   Контейнер `web` сам застосує міграції (`alembic upgrade head`), створить групи користувачів і запустить сервер.
3. Створи демонстраційні акаунти (докладніше в розділі «Демонстраційні дані»):
   ```
   docker compose exec web python -m src.test_fixture
   ```

| Що | Адреса |
|---|---|
| API і документація | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Пошта для розробки (MailHog) | http://localhost:8025 |
| Консоль MinIO | http://localhost:9001 |

### Вхід у документацію

Сторінки документації закриті: браузер запитає **пошту й пароль** зареєстрованого активного користувача
(наприклад, демонстраційного, див. нижче). Щоб виконувати захищені запити зі Swagger UI, викличи
`POST /accounts/login/`, натисни **Authorize** і встав `access_token`.

## Демонстраційні дані (фікстура)

Скрипт `src/text_fixture.py` створює три готові до роботи акаунти, по одному на кожну роль. Вони вже активні, тож
листа активації не потрібно. Каталог фільмів скрипт **не** наповнює: фільми створює модератор через `POST /movies/`.

| Роль | Пошта | Пароль |
|---|---|---|
| Користувач | demo.user@example.com | Demo1234! |
| Модератор | demo.moderator@example.com | Demo1234! |
| Адміністратор | demo.admin@example.com | Demo1234! |

**Запуск у Docker** (після `docker compose up`):

```
docker compose exec web python -m src.test_fixture
```

**Запуск без Docker.** Потрібні запущена база, правильний `DATABASE_URL` у `.env` і застосовані міграції:

```
poetry run alembic upgrade head
poetry run python -m src.test_fixture
```

У консолі з'явиться список створених акаунтів.

**Власний пароль.** Пароль за замовчуванням призначений лише для локальної перевірки. Задати інший можна змінною
`DEMO_PASSWORD`:

```
docker compose exec -e DEMO_PASSWORD='MyStr0ng!Pass' web python -m src.test_fixture
DEMO_PASSWORD='MyStr0ng!Pass' poetry run python -m src.test_fixture
```

Пароль має відповідати вимогам: від 8 символів, велика й мала літери, цифра та спецсимвол із `@ $ ! % * ? & #`.

**Повторний запуск безпечний.** Дублів не буде: скрипт приводить акаунти до стану з таблиці вище (активні, у правильній
групі) і **заново ставить пароль**. Так можна змінити пароль, наприклад, після перевірки. Пароль не варто зберігати
в репозиторії, коли застосунок розгорнуто на сервері.

**Почати з чистої бази.** `docker compose down -v` видаляє контейнери й **усі дані**, потім `docker compose up --build`
і знову команда запуску.

**Типові помилки:**

| Повідомлення | Причина | Що робити |
|---|---|---|
| `password authentication failed for user "..."` або `role "..." does not exist` | ім'я чи пароль у `DATABASE_URL` не збігаються з `POSTGRES_USER` і `POSTGRES_PASSWORD` | виправ `.env` |
| `Connect call failed` або `Connection refused` | база не запущена або вказано не той порт | `docker compose up -d db`, перевір порт у `DATABASE_URL` |
| `relation "user_groups" does not exist` | таблиці ще не створені | `poetry run alembic upgrade head` (у Docker це робить контейнер `web` під час старту) |
| `ValueError: Password must contain ...` | `DEMO_PASSWORD` надто простий | пароль за вимогами вище |

## Змінні оточення

Приклад лежить у `.env.example`. Значення без «за замовчуванням» обов'язкові: без них застосунок не запуститься.

| Змінна | Призначення | За замовчуванням |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | база даних (для Docker Compose) | немає |
| `DATABASE_URL` | рядок підключення (`postgresql+asyncpg://...`); у Docker підставляється автоматично | немає |
| `SECRET_KEY_ACCESS`, `SECRET_KEY_REFRESH` | ключі підпису access- і refresh-токенів (різні, від 32 символів) | немає |
| `JWT_SIGNING_ALGORITHM` | алгоритм підпису | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | термін життя access-токена | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | термін життя refresh-токена | `7` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | ключі Stripe | немає |
| `STRIPE_CURRENCY` | валюта платежів | `usd` |
| `PAYMENT_SUCCESS_URL`, `PAYMENT_CANCEL_URL` | куди Stripe повертає користувача | `http://localhost:8000/docs` |
| `REDIS_URL` | брокер Celery; у Docker підставляється автоматично | `redis://localhost:6379/0` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_FROM` | SMTP; у Docker це MailHog | `localhost`, `1025`, `no-reply@online-cinema.local` |
| `ACTIVATION_URL`, `PASSWORD_RESET_URL` | сторінки, на які ведуть посилання з листів (додаються `?email=...&token=...`) | `http://localhost:8000/docs` |

## Перевірка оплати (Stripe, тестовий режим)

1. У `.env` вкажи тестовий `STRIPE_SECRET_KEY`.
2. Запусти пересилання вебхуків: `stripe listen --forward-to localhost:8000/payments/webhook/`. Команда виведе
   `whsec_...`, це значення для `STRIPE_WEBHOOK_SECRET`. Після зміни `.env` перезапусти контейнери.
3. Створи замовлення, викличи `POST /payments/orders/{order_id}/checkout/` і відкрий отриманий `checkout_url`.
4. Оплати тестовою карткою `4242 4242 4242 4242` (будь-яка майбутня дата й CVC). Замовлення стане `paid`.

## API

Повний опис із прикладами відкривається в Swagger UI. Коротко:

**Акаунти**

| Запит | Опис |
|---|---|
| `POST /accounts/register/` | реєстрація, лист активації |
| `POST /accounts/activate/` | активація за токеном із листа |
| `POST /accounts/activate/resend/` | новий токен активації |
| `POST /accounts/login/` | вхід, повертає access- і refresh-токени |
| `POST /accounts/refresh/` | новий access-токен |
| `POST /accounts/logout/` | відкликає refresh-токен |
| `POST /accounts/change-password/` | зміна пароля за старим паролем |
| `POST /accounts/password-reset/request/` | запит на скидання пароля |
| `POST /accounts/password-reset/complete/` | новий пароль за токеном із листа |
| `PATCH /admin/users/{user_id}/group/` | зміна групи користувача (адміністратор) |
| `POST /admin/users/{user_id}/activate/` | ручна активація (адміністратор) |

**Каталог**

| Запит | Опис |
|---|---|
| `GET /movies/` | список: `page`, `per_page`, `year`, `imdb_min`, `genre_id`, `q`, `sort_by`, `order` |
| `GET /movies/{movie_id}/` | деталі фільму |
| `POST /movies/` | створити фільм (модератор) |
| `PATCH /movies/{movie_id}/` | змінити фільм (модератор) |
| `DELETE /movies/{movie_id}/` | видалити фільм (модератор) |
| `PUT /movies/{movie_id}/like/` | лайк або дизлайк |
| `DELETE /movies/{movie_id}/like/` | прибрати свою реакцію |
| `PUT /movies/{movie_id}/rating/` | оцінка від 1 до 10 |
| `GET /movies/{movie_id}/stats/` | лайки, дизлайки, середня оцінка |
| `POST /movies/{movie_id}/favorite/` | додати в улюблені |
| `DELETE /movies/{movie_id}/favorite/` | прибрати з улюблених |
| `GET /movies/favorites/` | улюблені з тими самими фільтрами, що й каталог |
| `GET /movies/{movie_id}/comments/` | коментарі до фільму |
| `POST /movies/{movie_id}/comments/` | написати коментар або відповідь (`parent_id`) |
| `POST /comments/{comment_id}/like/` | лайк коментаря |
| `DELETE /comments/{comment_id}/like/` | прибрати лайк коментаря |
| `GET /notifications/` | мої сповіщення |
| `POST /notifications/{notification_id}/read/` | позначити сповіщення прочитаним |
| `GET /genres/` | жанри з кількістю фільмів |
| `GET /stars/` | актори |

Жанри й актори (`/genres/`, `/stars/`) створюють, перейменовують і видаляють модератори.

**Кошик, замовлення, платежі**

| Запит | Опис |
|---|---|
| `GET /cart/` | мій кошик |
| `POST /cart/movies/{movie_id}/` | додати фільм |
| `DELETE /cart/movies/{movie_id}/` | прибрати фільм |
| `DELETE /cart/` | очистити кошик |
| `GET /cart/users/{user_id}/` | кошик користувача (модератор) |
| `POST /orders/` | оформити замовлення з кошика |
| `GET /orders/` | мої замовлення |
| `POST /orders/{order_id}/cancel/` | скасувати неоплачене замовлення |
| `GET /orders/all/` | усі замовлення з фільтрами (модератор) |
| `POST /payments/orders/{order_id}/checkout/` | посилання на оплату в Stripe |
| `POST /payments/webhook/` | вебхук Stripe |
| `GET /payments/` | моя історія платежів |
| `GET /payments/all/` | усі платежі з фільтрами (модератор) |
| `POST /payments/{payment_id}/refund/` | повернення коштів (модератор) |

## Структура проєкту

```
.
├── .github/workflows/ci.yml   конвеєр CI/CD
├── alembic/                   міграції бази даних
├── src/
│   ├── main.py                застосунок і підключення роутів
│   ├── config.py              налаштування з .env
│   ├── database.py            підключення до бази
│   ├── celery_app.py, tasks.py   Celery: листи й періодичне очищення
│   ├── test_fixture.py  початкові дані: групи користувачів, демо-акаунти
│   ├── models/                моделі бази даних
│   ├── schemas/               схеми запитів і відповідей
│   ├── routes/                ендпоінти
│   ├── security/              JWT, паролі, перевірка прав
│   ├── notifications/         відправка листів
│   └── utils/
├── tests/                     unit, integration, functional
├── Dockerfile, docker-compose.yml
├── pyproject.toml, poetry.lock
└── pytest.ini, coveragerc, .flake8, .env.example
```

## Розробка без Docker

```
poetry install
alembic upgrade head          # потрібна запущена база з DATABASE_URL у .env
python -m src.test_fixture           # групи користувачів
uvicorn src.main:app --reload
```

Нова міграція після зміни моделей: `alembic revision --autogenerate -m "опис"`.

## Тести та якість коду

```
poetry run pytest                                   # усі тести
poetry run pytest --cov=src --cov-report=term-missing   # із покриттям
poetry run black --check .
poetry run flake8 .
poetry run mypy src
```

Тести використовують окрему базу в пам'яті (SQLite), підміняють Stripe й пошту та не потребують запущених
сервісів: ані Docker, ані Redis. Є три рівні: `tests/unit` (перевірки пароля, JWT, дат), `tests/integration`
(ендпоінти разом із базою) і `tests/functional` (наскрізний сценарій від реєстрації до оплаченого фільму).

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`):

- на кожен pull request і push у `main`: `black`, `flake8`, `mypy` і тести з покриттям (звіт зберігається як артефакт);
- після успішного злиття в `main` застосунок розгортається на AWS EC2 по SSH (`git pull` і `docker compose up -d --build`).

Для розгортання потрібні секрети репозиторію `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`. На сервері мають бути Docker,
склонований репозиторій у `~/online-cinema` і файл `.env` із робочими значеннями. На сервері не відкривай назовні
порти бази даних, Redis і MinIO.

## Ключові рішення

- Access- і refresh-токени підписуються різними ключами. Refresh-токени зберігаються в базі, тому вихід їх
  справді відкликає. У кожного токена є унікальний `jti`.
- Відповіді на вхід, повторну активацію та скидання пароля однакові для існуючої й неіснуючої пошти.
- Вебхук Stripe перевіряє підпис і вік запиту, а повторна доставка події нічого не змінює.
- Позиції замовлення зберігають ціну на момент замовлення (`price_at_order`).
- Лист ставиться в чергу тільки після коміту, а недоступна черга не ламає реєстрацію чи вебхук.
