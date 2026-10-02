"""Tests for configuration parsing."""

from app.config import Settings


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_cors_origin_list_handles_single_value() -> None:
    assert Settings(cors_origins="http://a.test").cors_origin_list == ["http://a.test"]


def test_is_production_flag() -> None:
    assert Settings(env="production").is_production is True
    assert Settings(env="PROD").is_production is True
    assert Settings(env="development").is_production is False
