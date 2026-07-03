"""Unit tests for ts tableau commands — profile loading, request construction, response parsing."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.tableau.client import (
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
        with patch("ts_cli.tableau.client.TABLEAU_PROFILES_PATH", profiles_file):
            result = load_tableau_profiles()
        assert len(result) == 1
        assert result[0]["name"] == "Dev"

    def test_load_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("ts_cli.tableau.client.TABLEAU_PROFILES_PATH", missing):
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
        with patch("ts_cli.tableau.client.requests.post") as mock_post:
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

        with patch("ts_cli.tableau.client.requests.post") as mock_post:
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

        with patch("ts_cli.tableau.client.requests.post") as mock_post:
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

        with patch("ts_cli.tableau.client.requests.request",
                    side_effect=[fail_resp, ok_resp]):
            with patch("ts_cli.tableau.client.time.sleep"):
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

        with patch("ts_cli.tableau.client.requests.request", return_value=resp_403):
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

    def test_download_extracts_tdsx_and_validates_csv(self, tmp_path):
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

        csv_content = "Name,Amount,Date\nAlice,100,2024-01-01\nBob,200,2024-01-02\n"
        tdsx_bytes = io.BytesIO()
        with zipfile.ZipFile(tdsx_bytes, "w") as zf:
            zf.writestr("Data/SalesData.csv", csv_content)
        tdsx_bytes.seek(0)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.content = tdsx_bytes.read()
        mock_resp.headers = {"Content-Disposition": 'filename="SalesData.tdsx"'}

        with patch.object(client, "request", return_value=mock_resp):
            result = client.download_datasource("ds-uuid", tmp_path)

        assert len(result["data_files"]) == 1
        csv_file = result["data_files"][0]
        assert csv_file["type"] == "csv"
        assert csv_file["validation"]["is_valid"] is True
        assert csv_file["validation"]["data_rows"] == 2
        assert csv_file["validation"]["header_columns"] == 3
        assert Path(csv_file["path"]).exists()

    def test_download_detects_corrupt_csv_lines(self, tmp_path):
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

        csv_content = "ID,Name,Value\n1,Alice,100\ncorrupt_line\n3,Charlie,300\n"
        tdsx_bytes = io.BytesIO()
        with zipfile.ZipFile(tdsx_bytes, "w") as zf:
            zf.writestr("Data/BadData.csv", csv_content)
        tdsx_bytes.seek(0)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.content = tdsx_bytes.read()
        mock_resp.headers = {"Content-Disposition": 'filename="BadData.tdsx"'}

        with patch.object(client, "request", return_value=mock_resp):
            result = client.download_datasource("ds-uuid", tmp_path)

        csv_file = result["data_files"][0]
        assert csv_file["validation"]["is_valid"] is False
        assert len(csv_file["validation"]["corrupt_lines"]) == 1
        corrupt = csv_file["validation"]["corrupt_lines"][0]
        assert corrupt["line"] == 3
        assert corrupt["expected_columns"] == 3
        assert corrupt["actual_columns"] == 1
        assert "corrupt_line" in corrupt["content"]

    def test_download_non_zip_file(self, tmp_path):
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

        csv_content = b"Col1,Col2\nA,1\nB,2\n"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.content = csv_content
        mock_resp.headers = {"Content-Disposition": 'filename="export.csv"'}

        with patch.object(client, "request", return_value=mock_resp):
            result = client.download_datasource("ds-uuid", tmp_path)

        assert len(result["data_files"]) == 1
        assert result["data_files"][0]["type"] == "csv"
        assert result["data_files"][0]["validation"]["is_valid"] is True

    def test_validate_csv_static(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("A,B,C\n1,2,3\n4,5,6\nBAD\n7,8,9\n")
        result = TableauClient._validate_csv(csv_path)
        assert result["total_lines"] == 5
        assert result["data_rows"] == 4
        assert result["is_valid"] is False
        assert len(result["corrupt_lines"]) == 1
        assert result["corrupt_lines"][0]["line"] == 4

    def test_validate_csv_quoted_fields(self, tmp_path):
        csv_path = tmp_path / "quoted.csv"
        csv_path.write_text(
            'ID,Name,Value\n'
            '1,"First Aid Kit, Office Size",100\n'
            '2,"Hammermill, Great White, 20lb",200\n'
        )
        result = TableauClient._validate_csv(csv_path)
        assert result["is_valid"] is True
        assert result["data_rows"] == 2
        assert result["header_columns"] == 3
        assert len(result["corrupt_lines"]) == 0

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
