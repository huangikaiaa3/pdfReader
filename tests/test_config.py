from app.core.config import Settings


def test_settings_parse_cors_allowed_origins():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/pdfreader",
        redis_url="redis://localhost:6379/0",
        cors_allowed_origins="http://localhost:5173, https://app.example.com ",
    )

    assert settings.cors_allowed_origin_list == ["http://localhost:5173", "https://app.example.com"]


def test_app_database_url_overrides_database_url():
    settings = Settings(
        _env_file=None,
        app_database_url="postgresql://override-user:override-pass@db.example.com:5432/pdfreader",
        database_url="postgresql://postgres:postgres@localhost:5432/pdfreader",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.database_url == "postgresql+psycopg://override-user:override-pass@db.example.com:5432/pdfreader"
