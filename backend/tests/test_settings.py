from app.core.config import Settings


def test_settings_parse_cors_origins() -> None:
    settings = Settings(BACKEND_CORS_ORIGINS="http://localhost:5173, http://127.0.0.1:5173")

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
