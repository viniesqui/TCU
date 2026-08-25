"""
Tests for web_search and web_fetch tools.
All HTTP calls are mocked — no real network requests.
"""
import json
import time
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture(autouse=True)
def mock_search_cache(monkeypatch, tmp_path):
    """Isolate search cache by using a temp directory for each test run."""
    import src.tools.web_search
    monkeypatch.setattr(src.tools.web_search, "_CACHE_DIR", tmp_path / "search_cache")
    monkeypatch.setattr(src.tools.web_search, "_CACHE_FILE", tmp_path / "search_cache" / "web_search_cache.json")


class TestWebSearch:
    def test_returns_json_list_on_success(self):
        mock_results = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "body text 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "body text 2"},
        ]
        with patch("duckduckgo_search.DDGS") as mock_ddgs_class:
            mock_ddgs = MagicMock()
            mock_ddgs.text.return_value = iter(mock_results)
            mock_ddgs_class.return_value.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs_class.return_value.__exit__ = MagicMock(return_value=False)

            from src.tools.web_search import web_search
            result = web_search("empleos python Costa Rica")

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["title"] == "Result 1"

    def test_returns_error_json_on_exception(self):
        with patch("duckduckgo_search.DDGS") as mock_ddgs_class:
            mock_ddgs = MagicMock()
            mock_ddgs.text.side_effect = Exception("Network error")
            mock_ddgs_class.return_value.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs_class.return_value.__exit__ = MagicMock(return_value=False)

            with patch("time.sleep"):  # skip retry delays
                from src.tools.web_search import web_search
                result = web_search("test query")

        data = json.loads(result)
        assert "error" in data
        assert "error_code" in data  # required for base_agent to set is_error=True
        assert "query" in data

    def test_retries_on_transient_failure_then_succeeds(self):
        mock_results = [{"title": "Result", "href": "https://example.com", "body": "body"}]
        call_count = {"n": 0}

        def flaky_text(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise Exception("Transient error")
            return iter(mock_results)

        with patch("duckduckgo_search.DDGS") as mock_ddgs_class:
            mock_ddgs = MagicMock()
            mock_ddgs.text.side_effect = flaky_text
            mock_ddgs_class.return_value.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs_class.return_value.__exit__ = MagicMock(return_value=False)

            with patch("time.sleep"):  # skip retry delays
                from src.tools.web_search import web_search
                result = web_search("test query")

        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["title"] == "Result"
        assert call_count["n"] == 2  # failed once, succeeded on retry

    def test_uses_cr_es_region(self):
        """Verifies that searches are made with Costa Rica region filter."""
        called_with_region = {}

        def capture_text(*args, **kwargs):
            called_with_region["region"] = kwargs.get("region")
            return iter([])

        with patch("duckduckgo_search.DDGS") as mock_ddgs_class:
            mock_ddgs = MagicMock()
            mock_ddgs.text.side_effect = capture_text
            mock_ddgs_class.return_value.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs_class.return_value.__exit__ = MagicMock(return_value=False)

            from src.tools.web_search import web_search
            web_search("test query")

        assert called_with_region.get("region") == "cr-es"


class TestWebFetch:
    def _make_mock_response(self, status_code=200, html="<html><body><p>Test content</p></body></html>"):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_returns_text_on_success(self):
        mock_resp = self._make_mock_response(html="<html><body><p>Hello world</p></body></html>")

        with patch("httpx.get", return_value=mock_resp):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://example.com")

        assert "Hello world" in result
        assert "{" not in result  # Should not be JSON error

    def test_strips_script_and_style_tags(self):
        html = """
        <html><body>
          <script>var x = 1;</script>
          <style>.foo { color: red; }</style>
          <p>Real content here</p>
        </body></html>
        """
        mock_resp = self._make_mock_response(html=html)

        with patch("httpx.get", return_value=mock_resp):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://example.com")

        assert "Real content here" in result
        assert "var x = 1" not in result
        assert "color: red" not in result

    def test_returns_structured_error_on_403(self):
        mock_resp = self._make_mock_response(status_code=403)

        with patch("httpx.get", return_value=mock_resp):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://blocked-site.com")

        data = json.loads(result)
        assert data["error_code"] == 403
        assert "suggestion" in data

    def test_returns_structured_error_on_404(self):
        mock_resp = self._make_mock_response(status_code=404)

        with patch("httpx.get", return_value=mock_resp):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://notfound.com")

        data = json.loads(result)
        assert data["error_code"] == 404

    def test_returns_structured_error_on_timeout(self):
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout")):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://slow-site.com")

        data = json.loads(result)
        assert data["error_code"] == "timeout"
        assert "suggestion" in data

    def test_retries_on_429_then_succeeds(self):
        call_count = {"n": 0}

        def flaky_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return self._make_mock_response(status_code=429)
            return self._make_mock_response(html="<html><body><p>Content after retry</p></body></html>")

        with patch("httpx.get", side_effect=flaky_get):
            with patch("time.sleep"):  # skip actual sleep
                from src.tools.web_fetch import web_fetch
                result = web_fetch("https://rate-limited-site.com")

        assert "Content after retry" in result
        assert call_count["n"] == 2

    def test_truncates_at_max_chars(self):
        long_content = "A" * 10000
        html = f"<html><body><p>{long_content}</p></body></html>"
        mock_resp = self._make_mock_response(html=html)

        with patch("httpx.get", return_value=mock_resp):
            from src.tools.web_fetch import web_fetch
            result = web_fetch("https://example.com", max_chars=500)

        assert len(result) <= 600  # Some buffer for the truncation message
        assert "truncado" in result.lower()
