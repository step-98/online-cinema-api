import pytest

from src.models.validators import accounts as validators


def test_a_strong_password_is_returned_unchanged():
    assert validators.validate_password_strength("Passw0rd!") == "Passw0rd!"


@pytest.mark.parametrize(
    "password",
    [
        "Sh0rt!",  # fewer than 8 characters
        "alllower1!",  # no uppercase letter
        "ALLUPPER1!",  # no lowercase letter
        "NoDigits!!",  # no digit
        "NoSpecial1A",  # no special character
    ],
)
def test_weak_passwords_are_rejected(password):
    with pytest.raises(ValueError):
        validators.validate_password_strength(password)


def test_a_valid_email_is_accepted():
    assert "@" in validators.validate_email("someone@example.com")


@pytest.mark.parametrize("value", ["not-an-email", "missing@tld", "@example.com"])
def test_invalid_emails_are_rejected(value):
    with pytest.raises(ValueError):
        validators.validate_email(value)
