from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from users.management.commands import bot_post


def _published(hours_ago):
    """published_at as johnvc~GoogleNewsAPI writes it, e.g. '2026-01-11 11:30:00 UTC'."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _response(status_code, items):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = items
    return resp


@patch.object(bot_post, "APIFY_TOKEN", "test-token")
@patch("users.management.commands.bot_post.requests.post")
class ApifyNewsFetchTests(SimpleTestCase):
    def setUp(self):
        # One results page, trimmed to the fields bot_post reads
        self.page = {
            "page_number": 1,
            "search_parameters": {"q": "Premier League football 2026"},
            "news_results": [
                {
                    "position": 1,
                    "title": "Arsenal beat Chelsea to go top of the Premier League - BBC Sport",
                    "link": "https://example.com/arsenal-chelsea",
                    "source": "BBC Sport",
                    "snippet": "A late winner sent Arsenal three points clear.",
                    "date": "3 hours ago",
                    "published_at": _published(3),
                },
                {
                    "position": 2,
                    "title": "Premier League season preview: every club rated",
                    "link": "https://example.com/season-preview",
                    "source": "The Guardian",
                    "snippet": "Twenty clubs, twenty verdicts.",
                    "date": "2 months ago",
                    "published_at": _published(24 * 60),
                },
            ],
        }

    def _fetch(self):
        cmd = bot_post.Command(stdout=StringIO())
        return cmd._fetch_apify_news("Premier League", ["Arsenal", "Chelsea"])

    def test_news_results_become_candidates(self, mock_post):
        """Articles are read from each page's news_results; stale ones are dropped."""
        mock_post.return_value = _response(201, [self.page])

        candidates = self._fetch()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["title"], "Arsenal beat Chelsea to go top of the Premier League"
        )
        self.assertIn("A late winner", candidates[0]["text"])
        self.assertIn("(via BBC Sport)", candidates[0]["text"])

        self.assertIn("johnvc~GoogleNewsAPI", mock_post.call_args.args[0])
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["q"], "Premier League football 2026")
        self.assertEqual(sent["hl"], "en")

    def test_page_without_articles_gives_no_candidates(self, mock_post):
        mock_post.return_value = _response(201, [{"page_number": 1, "news_results": []}])

        self.assertEqual(self._fetch(), [])

    def test_error_status_gives_no_candidates(self, mock_post):
        mock_post.return_value = _response(404, {"error": {"type": "record-not-found"}})

        self.assertEqual(self._fetch(), [])
