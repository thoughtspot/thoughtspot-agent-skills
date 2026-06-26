"""Unit tests for ts tableau commands — profile loading, request construction, response parsing."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.commands.tableau import (
    _slugify_tableau,
    load_tableau_profiles,
    TABLEAU_PROFILES_PATH,
    TableauClient,
)


class TestSlugifyTableau:
    @pytest.mark.parametrize("name,expected", [
        ("My Tableau Cloud", "my-tableau-cloud"),
        ("Production", "production"),
        ("Tableau Dev", "tableau-dev"),
        ("  Spaces  ", "spaces"),
        ("A--B", "a-b"),
    ])
    def test_slug_derivation(self, name, expected):
        assert _slugify_tableau(name) == expected


class TestLoadTableauProfiles:
    def test_load_array_format(self, tmp_path):
        profiles_file = tmp_path / "tableau-profiles.json"
        profiles_file.write_text(json.dumps([
            {"name": "Dev", "server_url": "https://example.com",
             "site_content_url": "mysite", "auth": "password",
             "username": "user@test.com", "password_env": "TAB_PW_DEV"},
        ]))
        with patch("ts_cli.commands.tableau.TABLEAU_PROFILES_PATH", profiles_file):
            result = load_tableau_profiles()
        assert len(result) == 1
        assert result[0]["name"] == "Dev"

    def test_load_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("ts_cli.commands.tableau.TABLEAU_PROFILES_PATH", missing):
            result = load_tableau_profiles()
        assert result == []


class TestTableauClientSignin:
    def test_password_signin_body(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "mysite",
            "auth": "password",
            "username": "user@test.com",
            "password_env": "TABLEAU_PASSWORD_DEV",
        }
        client = TableauClient(profile)
        with patch("ts_cli.commands.tableau.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "credentials": {
                    "token": "abc123",
                    "site": {"id": "site-uuid"},
                    "user": {"id": "user-uuid"},
                }
            }
            mock_post.return_value = mock_resp

            with patch.object(client, "_get_credential", return_value="s3cret"):
                result = client.signin()

            actual_data = mock_post.call_args.kwargs.get("data", "")
            assert 'name="user@test.com"' in actual_data
            assert 'password="s3cret"' in actual_data
            assert 'contentUrl="mysite"' in actual_data
            assert "personalAccessTokenName" not in actual_data

            assert result["site_id"] == "site-uuid"
            assert result["user_id"] == "user-uuid"

    def test_pat_signin_body(self):
        profile = {
            "name": "Prod",
            "server_url": "https://tableau.example.com",
            "site_content_url": "prodsite",
            "auth": "pat",
            "pat_name": "my-token",
            "pat_secret_env": "TABLEAU_PAT_SECRET_PROD",
        }
        client = TableauClient(profile)

        with patch("ts_cli.commands.tableau.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "credentials": {
                    "token": "xyz789",
                    "site": {"id": "prod-site-uuid"},
                    "user": {"id": "prod-user-uuid"},
                }
            }
            mock_post.return_value = mock_resp

            with patch.object(client, "_get_credential", return_value="pat-secret"):
                result = client.signin()

            actual_data = mock_post.call_args.kwargs.get("data", "")
            assert 'personalAccessTokenName="my-token"' in actual_data
            assert 'personalAccessTokenSecret="pat-secret"' in actual_data
            assert 'contentUrl="prodsite"' in actual_data
            assert result["site_id"] == "prod-site-uuid"

    def test_signin_401_exits(self):
        profile = {
            "name": "Bad",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "user@test.com",
            "password_env": "TAB_PW",
        }
        client = TableauClient(profile)

        with patch("ts_cli.commands.tableau.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_post.return_value = mock_resp

            with patch.object(client, "_get_credential", return_value="wrong"):
                with pytest.raises(SystemExit):
                    client.signin()


class TestTableauClientRetry:
    def test_retryable_status_retries(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "u",
            "password_env": "PW",
        }
        client = TableauClient(profile)
        client._token = "valid-token"
        client._site_id = "site-id"

        fail_resp = MagicMock()
        fail_resp.status_code = 502
        fail_resp.ok = False

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.ok = True
        ok_resp.json.return_value = {"result": "ok"}

        with patch("ts_cli.commands.tableau.requests.request",
                    side_effect=[fail_resp, ok_resp]):
            with patch("ts_cli.commands.tableau.time.sleep"):
                resp = client.request("GET", "/api/test")

        assert resp.status_code == 200

    def test_non_retryable_exits(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "u",
            "password_env": "PW",
        }
        client = TableauClient(profile)
        client._token = "valid-token"
        client._site_id = "site-id"

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.ok = False
        resp_403.json.return_value = {"error": {"summary": "Forbidden"}}
        resp_403.text = "Forbidden"

        with patch("ts_cli.commands.tableau.requests.request", return_value=resp_403):
            with pytest.raises(SystemExit):
                client.request("GET", "/api/test")


class TestDatasourceParsing:
    def test_datasources_parses_array(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "u",
            "password_env": "PW",
        }
        client = TableauClient(profile)
        client._token = "token"
        client._site_id = "site-id"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "datasources": {
                "datasource": [
                    {"id": "ds-1", "name": "Sales"},
                    {"id": "ds-2", "name": "Orders"},
                ]
            },
            "pagination": {"totalAvailable": "2", "pageNumber": "1", "pageSize": "100"},
        }

        with patch.object(client, "request", return_value=mock_resp):
            result = client.datasources()

        assert len(result) == 2
        assert result[0]["name"] == "Sales"

    def test_datasources_single_item_not_array(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "u",
            "password_env": "PW",
        }
        client = TableauClient(profile)
        client._token = "token"
        client._site_id = "site-id"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "datasources": {
                "datasource": {"id": "ds-1", "name": "Solo"}
            },
            "pagination": {"totalAvailable": "1", "pageNumber": "1", "pageSize": "100"},
        }

        with patch.object(client, "request", return_value=mock_resp):
            result = client.datasources()

        assert len(result) == 1
        assert result[0]["name"] == "Solo"

    def test_datasource_fields_parses_data(self):
        profile = {
            "name": "Dev",
            "server_url": "https://tableau.example.com",
            "site_content_url": "site",
            "auth": "password",
            "username": "u",
            "password_env": "PW",
        }
        client = TableauClient(profile)
        client._token = "token"
        client._site_id = "site-id"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": [
                {"fieldCaption": "Sales", "dataType": "real",
                 "columnClass": "COLUMN", "formula": None},
                {"fieldCaption": "Profit Ratio", "dataType": "real",
                 "columnClass": "CALCULATION", "formula": "SUM([Profit])/SUM([Sales])"},
            ]
        }

        with patch.object(client, "request", return_value=mock_resp):
            result = client.datasource_fields("ds-uuid")

        assert len(result) == 2
        assert result[1]["formula"] == "SUM([Profit])/SUM([Sales])"
