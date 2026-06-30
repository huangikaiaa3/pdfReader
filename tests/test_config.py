from app.core.config import Settings


def test_settings_parse_cors_allowed_origins():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/pdfreader",
        redis_url="redis://localhost:6379/0",
        cors_allowed_origins="http://localhost:5173, https://app.example.com ",
    )

    assert settings.cors_allowed_origin_list == ["http://localhost:5173", "https://app.example.com"]
