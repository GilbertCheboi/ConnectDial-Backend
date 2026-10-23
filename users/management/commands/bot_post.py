"""
bot_post.py  —  ConnectDial Sports Post Bot (Apify Edition)
═══════════════════════════════════════════════════════════
Data sources (priority cascade):
  1. API-Football  — live scores, standings, top scorers  (set RAPID_API_KEY)
  2. football-data.org — free EPL/UCL/La Liga etc.        (set FOOTBALL_DATA_API_KEY)
  3. Apify Google News — real, filtered sports headlines  (set APIFY_TOKEN)  ← NEW
  4. NewsAPI        — fallback headlines                   (set NEWS_API_KEY)
  5. Offline templates — always works, high variety

Key fixes vs previous version:
  ✅ IMAGES   — Apify Google Images, content-matched per post
  ✅ DEDUP    — Apify image query built from post content
  ✅ CONTENT  — Apify queries "{league} news/football" so results are on-topic
  ✅ SPAM     — casino/betting/listicle/net-worth junk filtered before posting
  ✅ RECENCY  — only articles ≤ 2 days old
  ✅ CAPTIONS — 12 varied wrappers; never the same opener twice in a run
  ✅ CROSS-BOT DEDUP — same story not posted by multiple bots in same day

Usage:
  python manage.py bot_post "Premier League"
  python manage.py bot_post "Saudi Pro League" --source apify
  python manage.py bot_post "Champions League" --dry-run
"""

import os
import re
import time
import random
import hashlib
import requests
from datetime import timedelta, datetime, timezone as _dt_tz
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from posts.models import Post, Hashtag
from leagues.models import League, Team

User = get_user_model()

# ─── API KEYS — set via environment variables, never hardcode ────────────────
RAPID_API_KEY         = os.environ.get("RAPID_API_KEY", "")
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
APIFY_TOKEN           = os.environ.get("APIFY_TOKEN", "")
NEWS_API_KEY          = os.environ.get("NEWS_API_KEY", "")

# ─── QUALITY CONTROLS ────────────────────────────────────────────────────────
NEWS_MAX_AGE_DAYS = 2        # reject articles older than this

NEWS_SPAM_KEYWORDS = {
    "slot", "slots", "casino", "gambling", "gamble", "bet365", "1xbet", "betway",
    "mines", "aviator", "jackpot", "roulette", "poker", "free spins", "bonus code",
    "promo code", "no deposit", "odds boost", "crypto", "bitcoin", "nft", "coupon",
    "giveaway", "how to win", "best sites", "sign up offer", "net worth", "net worths",
    "celebrities and their", "richest", "pickleball", "darts", "snooker celebrity",
    "reality tv", "love island",
}

_DANGLING_WORDS = {
    "as", "the", "and", "to", "of", "for", "with", "in", "on", "at", "a", "an",
    "but", "or", "that", "this", "is", "are", "was", "were", "by", "from",
    "his", "her", "their", "its", "amid", "after", "before", "over", "into", "ma",
}

# ─── LEAGUE CONFIG ───────────────────────────────────────────────────────────
LEAGUE_CONFIG = {
    "premier league":   {
        "api_id": 39,  "fd_code": "PL",  "emoji": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "season": 2025, "hashtags": ["PremierLeague", "EPL", "PL"],
        "apify_query": "Premier League football 2026",
    },
    "la liga":          {
        "api_id": 140, "fd_code": "PD",  "emoji": "🇪🇸",
        "season": 2025, "hashtags": ["LaLiga", "PrimeraDivision"],
        "apify_query": "La Liga Barcelona Real Madrid 2026",
    },
    "serie a":          {
        "api_id": 135, "fd_code": "SA",  "emoji": "🇮🇹",
        "season": 2025, "hashtags": ["SerieA", "calcio"],
        "apify_query": "Serie A Italian football 2026",
    },
    "bundesliga":       {
        "api_id": 78,  "fd_code": "BL1", "emoji": "🇩🇪",
        "season": 2025, "hashtags": ["Bundesliga"],
        "apify_query": "Bundesliga German football 2026",
    },
    "ligue 1":          {
        "api_id": 61,  "fd_code": "FL1", "emoji": "🇫🇷",
        "season": 2025, "hashtags": ["Ligue1", "FrenchFootball"],
        "apify_query": "Ligue 1 French football PSG 2026",
    },
    "champions league": {
        "api_id": 2,   "fd_code": "CL",  "emoji": "⭐",
        "season": 2025, "hashtags": ["UCL", "ChampionsLeague"],
        "apify_query": "UEFA Champions League 2026 final",
    },
    "saudi pro league": {
        "api_id": 307, "fd_code": None,  "emoji": "🇸🇦",
        "season": 2025, "hashtags": ["SPL", "SaudiProLeague", "RoshnLeague"],
        "apify_query": "Saudi Pro League Roshn football 2026",
    },
    "nba":              {
        "api_id": None,"fd_code": None,  "emoji": "🏀",
        "season": 2025, "hashtags": ["NBA", "Basketball"],
        "apify_query": "NBA basketball playoffs 2026",
    },
    "mls":              {
        "api_id": 253, "fd_code": None,  "emoji": "🇺🇸",
        "season": 2026, "hashtags": ["MLS", "MLSSoccer"],
        "apify_query": "MLS Major League Soccer World Cup 2026",
    },
    "fifa world cup":   {
        "api_id": 1,   "fd_code": "WC",  "emoji": "🏆",
        "season": 2026, "hashtags": ["FIFAWorldCup2026", "WorldCup2026", "WC2026"],
        "apify_query": "FIFA World Cup 2026 squad news",
    },
}

# ─── OFFLINE TEMPLATES ───────────────────────────────────────────────────────
OFFLINE_TEMPLATES = {
    "premier league": [
        "🏴󠁧󠁢󠁥󠁮󠁧󠁿 ARSENAL ARE PREMIER LEAGUE CHAMPIONS 2025-26! The Gunners did it — fourth title in club history. What a season! 🏆 #Arsenal #PL #ConnectDial",
        "📊 Haaland wins the 2025-26 PL Golden Boot with 27 goals. Three Golden Boots in four seasons. The most clinical striker alive. #Haaland #PL",
        "🎯 Bruno Fernandes — 21 Premier League assists in 2025-26. A RECORD. Never been done before. #Fernandes #MUFC #PL #ConnectDial",
        "🔴 West Ham relegated after 14 consecutive top-flight seasons. Football is brutal. #WestHam #PL",
        "⚽ Matchday drama in the Premier League: every fixture feels like a cup final. The standard never drops. #PL #ConnectDial",
    ],
    "la liga": [
        "🔵🔴 BARCELONA WIN LA LIGA 2025-26! Hansi Flick's side sealed their 29th title. Back-to-back champions! #Barca #LaLiga",
        "⚡ Mbappé finishes La Liga 2025-26 as top scorer with 24 goals. Second season, already a Bernabéu legend. #Mbappe #LaLiga",
        "🏟️ Real Madrid 2-1 Barca at the Bernabéu in October. Then Barca won 1-0 at Camp Nou to seal the title. Greatest rivalry in football. #ElClasico",
        "🧠 La Liga's positional play and tactical triggers are a masterclass. You genuinely learn football just by watching. #LaLiga #ConnectDial",
    ],
    "champions league": [
        "⭐ The 2025-26 UCL Final is set for May 30 at Puskás Aréna in Budapest. The greatest night in club football. #UCL #ChampionsLeague",
        "🥅 Mbappé is the UCL top scorer in 2025-26 with 15 goals. Turning Europe's biggest stage into his personal highlight reel. #Mbappe #UCL",
        "📊 3.49 goals per game average in the 2025-26 Champions League. Most entertaining edition in years. #UCL #ConnectDial",
        "🌍 Champions League nights are a different sport. Same pitches, same players — but the intensity? Nothing in football matches it. #UCL",
    ],
    "saudi pro league": [
        "🇸🇦 Julián Quiñones — Saudi Pro League top scorer 2025-26 with 28 goals. Absolutely unstoppable. #Quinones #SPL #ConnectDial",
        "🔥 Al-Nassr's 16-match winning run. Al-Hilal's 29-match unbeaten run. Same season. The SPL is HISTORIC. #SPL #RoshnLeague",
        "🧤 Bento: 13 clean sheets. Best keeper in the Saudi Pro League, no debate. The Brazilian wall. #Bento #AlHilal #SPL",
        "🏟️ 53,883 fans for Al-Nassr vs Al-Ittihad. Bigger than most Premier League games. Saudi football is a movement. #SPL",
        "📊 3.1 goals per game in the SPL. More than the Premier League. More than La Liga. The Roshn League is electric. #SPL #ConnectDial",
    ],
    "bundesliga": [
        "🥅 Harry Kane: 33 Bundesliga goals, 2025-26. Three consecutive Golden Boots. The greatest English striker ever. #Kane #Bayern #Bundesliga",
        "🏆 Bayern Munich: Bundesliga champions for the 34th time. 16 points clear. Kompany's side were DOMINANT. #Bayern #Bundesliga",
        "🌟 Michael Olise — 19 assists AND 15 goals in 2025-26 Bundesliga. Won Player of the Season. France's next superstar. #Olise #Bayern",
        "📊 3.2 goals per game average — the highest-scoring major European league this season. Bundesliga is BUILT RIGHT. #Bundesliga",
    ],
    "serie a": [
        "🖤💙 INTER MILAN WIN SERIE A 2025-26! Lautaro Martínez with 16 goals was their heartbeat all season. #Inter #SerieA",
        "⚡ AC Milan's 24-match unbeaten run in Serie A 2025-26. They couldn't win the title but that sequence is ELITE. #ACMilan #SerieA",
        "🔥 Inter 6-2 Pisa in January — the highest-scoring game of the Serie A season. When Inter are flying they are RELENTLESS. #Inter",
        "♟️ Serie A title races are chess on grass. Most carefully built football anywhere in Europe. #SerieA #Calcio",
    ],
    "nba": [
        "🏀 OKC Thunder won the 2025 NBA Championship in a Game 7 thriller. SGA won Finals MVP, regular season MVP AND scoring title. #OKC #NBA",
        "👑 Shai Gilgeous-Alexander: reigning champion, MVP and scoring champion. Most complete player in basketball right now. #SGA #Thunder #NBA",
        "🔥 2025-26 NBA Playoffs: OKC vs Spurs in the Western Conference Finals. Defending champs vs Wembanyama's rising Spurs. MUST WATCH. #NBA",
        "🌹 Wembanyama eliminated the Lakers to reach the Conference Finals. Doing things that shouldn't be possible at his age. #Wemby #Spurs",
    ],
    "mls": [
        "🇺🇸 62 million soccer fans in the USA — fourth-largest fanbase globally. The World Cup on home soil is about to make that EXPLODE. #MLS #WorldCup2026",
        "⚽ MLS 2026 plays alongside the World Cup being hosted in the USA. Perfect moment for American soccer to take over the world. #MLS",
        "🌎 Soccer in the USA has never been bigger. MLS quality rising, big names arriving, World Cup is HERE. #MLS #ConnectDial",
    ],
    "fifa world cup": [
        "🏆 FIFA World Cup 2026 kicks off June 11 in Mexico City. 48 nations, 104 matches, 3 host countries. The greatest show on earth. #WorldCup2026",
        "🗽 July 19. MetLife Stadium. The 2026 World Cup Final. The whole planet stops for 90 minutes. #WorldCup2026 #FIFA",
        "🌟 Mbappé. Bellingham. Vinicius. Yamal. The talent at the 2026 World Cup is the most extraordinary ever assembled. #WorldCup2026",
        "🇵🇹 Portugal playing for Diogo Jota at the 2026 World Cup. Bruno Fernandes said the squad is motivated by him. Something SPECIAL. #WorldCup2026",
    ],
    "generic": [
        "⚽ Football in 2026 is having its greatest year ever — from the SPL to the World Cup. What a time to be a fan. #ConnectDial",
        "🔥 Sport doesn't take a day off and neither does ConnectDial. Locked in all day every day. #Sports #ConnectDial",
    ],
}

# ─── PER-TYPE VOICE SYSTEM ───────────────────────────────────────────────────
# fan          → passionate supporter, opinionated, emoji-heavy, first person
# organization → official club/org voice, measured, authoritative
# news         → journalist voice, factual, breaking-news format

FAN_INTROS = [
    "",                                          # no prefix — raw passion
    "Okay this is HUGE — ",
    "Not gonna lie, ",
    "Every fan needs to see this — ",
    "Not calm about this at all — ",
    "The timeline needs to talk about this: ",
    "Posting this for every real supporter — ",
]
ORG_INTROS = [
    "📣 Official update: ",
    "⚽ Club news: ",
    "🏛️ From the organisation: ",
    "📋 Statement: ",
    "🔵 Club update: ",
    "Official: ",
]
NEWS_INTROS = [
    "📰 BREAKING: ",
    "🗞️ JUST IN: ",
    "📡 CONFIRMED: ",
    "⚡ NEWS: ",
    "📢 REPORT: ",
    "🔴 LIVE UPDATE: ",
]


def _apply_persona(text: str, bot_type: str) -> str:
    bt = (bot_type or "fan").lower()
    if bt == "news":
        return random.choice(NEWS_INTROS) + text
    elif bt in ("organization", "organisation", "club"):
        return random.choice(ORG_INTROS) + text
    else:
        intro = random.choice(FAN_INTROS)
        return (intro + text) if intro else text

# Varied caption wrappers — rotate so same opener never appears twice per run
_NEWS_WRAPPERS = [
    "{emoji} {title}",
    "🔥 Big one: {title}",
    "👀 Just in: {title}",
    "📣 {emoji} {title}",
    "💬 Talking point: {title}",
    "📊 Worth your time: {title}",
    "⚡ {title}",
    "🌍 {emoji} {title}",
    "📱 On the ConnectDial radar: {title}",
    "🗞️ {title}",
    "🎯 {emoji} {title}",
    "🏆 Must read: {title}",
]


class Command(BaseCommand):
    help = "Posts world-class sports content using Apify for news and images"

    # Class-level image dedup — track Apify images used this run
    _used_wrappers: list = []    # track wrapper indices used this run

    def add_arguments(self, parser):
        parser.add_argument("league_name", type=str)
        parser.add_argument(
            "--source", default="auto",
            choices=["auto", "apifootball", "football-data", "apify", "newsapi", "template"],
        )
        parser.add_argument("--dry-run", action="store_true")

    # ─── DEDUP ───────────────────────────────────────────────────────────────
    def _already_posted_this_week(self, bot, content_hash):
        cutoff = timezone.now() - timedelta(days=7)
        for c in Post.objects.filter(author=bot, created_at__gte=cutoff).values_list("content", flat=True):
            if hashlib.md5(c.encode()).hexdigest()[:8] == content_hash:
                return True
        return False

    def _seen_globally(self, snippet, days=NEWS_MAX_AGE_DAYS):
        key = (snippet or "").strip()[:60]
        if not key:
            return True
        cutoff = timezone.now() - timedelta(days=days)
        return Post.objects.filter(created_at__gte=cutoff, content__icontains=key).exists()

    def _bot_post_count_today(self, bot):
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return Post.objects.filter(author=bot, created_at__gte=today).count()

    # ─── NEWS QUALITY ────────────────────────────────────────────────────────
    def _is_spam(self, text):
        t = (text or "").lower()
        return any(kw in t for kw in NEWS_SPAM_KEYWORDS)

    def _is_recent(self, pub):
        if not pub:
            return False
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            return (datetime.now(_dt_tz.utc) - dt) <= timedelta(days=NEWS_MAX_AGE_DAYS)
        except Exception:
            return False

    def _clean_title(self, title, source=""):
        title = (title or "").strip()
        title = re.sub(r"\s*[-|–]\s*" + re.escape(source) + r"\s*$", "", title, flags=re.I).strip()
        return title

    def _is_truncated(self, title):
        words = (title or "").rstrip(" .!?…").split()
        return (not words) or words[-1].lower() in _DANGLING_WORDS

    def _is_relevant(self, title, desc, league_name, team_names):
        blob = f"{title} {desc}".lower()
        if league_name.lower() in blob:
            return True
        aliases = {a.lower() for a in LEAGUE_CONFIG.get(league_name.lower(), {}).get("hashtags", [])}
        if any(a in blob.replace(" ", "") for a in aliases):
            return True
        return any(tn.lower() in blob for tn in team_names if len(tn) > 3)

    # ─── IMAGE: Apify Google Images (content-matched, never article urlToImage) ──
    def _fetch_image_apify(self, search_query):
        """
        Fetch a content-matched image via Apify Google Images Scraper.
        Returns raw image bytes or None.
        Actor: apify~google-images-scraper
        """
        if not APIFY_TOKEN:
            return None
        try:
            r = requests.post(
                "https://api.apify.com/v2/acts/apify~google-images-scraper"
                "/run-sync-get-dataset-items",
                params={"token": APIFY_TOKEN},
                json={
                    "queries": search_query,
                    "maxImagesPerQuery": 10,
                    "imageSize": "medium",
                    "safesearch": "active",
                },
                timeout=45,
            )
            if r.status_code != 200:
                return None
            items = r.json()
            if not items:
                return None
            item = random.choice(items[:8])
            img_url = item.get("imageUrl") or item.get("url")
            if not img_url:
                return None
            res = requests.get(
                img_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if res.status_code == 200 and len(res.content) > 3000:
                return res.content
        except Exception:
            pass
        return None

    def _build_image_query(self, content, source_label, league_name, team_name=None):
        """
        Derive a specific image search query from the post content so the
        Apify Google Images query matches what the post is actually about.
        """
        if source_label in ("Apify", "NewsAPI"):
            # Use the headline (first line), strip emoji/punctuation
            first_line = content.split("\n")[0].strip()
            first_line = re.sub(r"[^\w\s\-']", " ", first_line).strip()
            first_line = re.sub(r"\s+", " ", first_line)
            query = first_line[:60].strip()
            if len(query) > 15:
                return f"{query} football"

        if source_label in ("API-Football", "football-data.org"):
            # Standings format: "Club lead League with Xpts"
            # Results format:   "FULL TIME: Team1 X–Y Team2"
            # Extract the first proper-noun club name only
            match = re.search(r"(?:TABLE:|FULL TIME[^:]*:)\s*([A-Z][A-Za-z\s]+?)(?:\s+\d|\s+lead|\s+FC\b)", content)
            if match:
                club = match.group(1).strip()
                return f"{club} football"
            # Fallback: grab first capitalised phrase before a number
            match = re.search(r"([A-Z][A-Za-z\s]{3,25}?)\s+\d", content)
            if match:
                return f"{match.group(1).strip()} football match"

        # Template or fallback
        if team_name:
            return f"{team_name} football"
        return f"{league_name} football stadium"

    # ─── SOURCE 1: API-Football ───────────────────────────────────────────────
    def _fetch_apifootball(self, league_id, league_name, season):
        base = "https://api-football-v1.p.rapidapi.com/v3"
        hdrs = {"X-RapidAPI-Key": RAPID_API_KEY, "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"}
        emoji = LEAGUE_CONFIG.get(league_name.lower(), {}).get("emoji", "⚽")
        posts = []
        try:
            r = requests.get(f"{base}/fixtures", params={"league": league_id, "last": 5, "status": "FT"},
                             headers=hdrs, timeout=8).json()
            for fx in r.get("response", [])[:3]:
                home = fx["teams"]["home"]["name"]
                away = fx["teams"]["away"]["name"]
                gh, ga = fx["goals"]["home"], fx["goals"]["away"]
                winner = home if gh > ga else (away if ga > gh else None)
                date_str = fx.get("fixture", {}).get("date", "")[:10]
                if winner:
                    posts.append(f"{emoji} FULL TIME [{date_str}]: {home} {gh}–{ga} {away} | "
                                 f"{winner} take all three points! 🔥 #{league_name.replace(' ','')} #ConnectDial")
                else:
                    posts.append(f"{emoji} FULL TIME [{date_str}]: {home} {gh}–{ga} {away} | "
                                 f"A hard-fought draw. #{league_name.replace(' ','')} #ConnectDial")
        except Exception:
            pass
        try:
            r = requests.get(f"{base}/players/topscorers", params={"league": league_id, "season": season},
                             headers=hdrs, timeout=8).json()
            scorers = r.get("response", [])[:1]
            if scorers:
                top = scorers[0]
                player = top["player"]["name"]
                team = top["statistics"][0]["team"]["name"]
                goals = top["statistics"][0]["goals"]["total"]
                posts.append(f"{emoji} GOLDEN BOOT: {player} ({team}) leads {league_name} "
                             f"with {goals} goals 🥅 #{league_name.replace(' ','')} #ConnectDial")
        except Exception:
            pass
        return posts

    # ─── SOURCE 2: football-data.org ─────────────────────────────────────────
    def _fetch_football_data(self, fd_code, league_name):
        if not fd_code:
            return []
        base = "https://api.football-data.org/v4"
        hdrs = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
        emoji = LEAGUE_CONFIG.get(league_name.lower(), {}).get("emoji", "⚽")
        posts = []
        try:
            r = requests.get(f"{base}/competitions/{fd_code}/matches",
                             params={"status": "FINISHED", "limit": 5},
                             headers=hdrs, timeout=8).json()
            matches = r.get("matches", [])
            if matches:
                m = random.choice(matches[:3])
                home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
                fts = m.get("score", {}).get("fullTime", {})
                gh, ga = fts.get("home", 0), fts.get("away", 0)
                winner = home if gh > ga else (away if ga > gh else None)
                if winner:
                    posts.append(f"{emoji} {home} {gh}–{ga} {away} | {winner} WIN! "
                                 f"Massive three points 🔥 #{league_name.replace(' ','')} #ConnectDial")
        except Exception:
            pass
        try:
            r = requests.get(f"{base}/competitions/{fd_code}/standings",
                             headers=hdrs, timeout=8).json()
            table = r.get("standings", [{}])[0].get("table", [])
            if len(table) >= 1:
                leader = table[0]
                club = leader.get("team", {}).get("name", "")
                pts = leader.get("points", 0)
                gd = leader.get("goalDifference", 0)
                posts.append(f"{emoji} TABLE: {club} lead {league_name} with {pts}pts "
                             f"(GD {'+' if gd>=0 else ''}{gd}) 📊 "
                             f"#{league_name.replace(' ','')} #ConnectDial")
        except Exception:
            pass
        return posts

    # ─── SOURCE 3: APIFY Google News ─────────────────────────────────────────
    def _fetch_apify_news(self, league_name, team_names):
        """
        Runs the Apify Google News Scraper Actor synchronously.
        Actor: johnvc~GoogleNewsAPI
        Returns list of {text, title} dicts — image fetched separately via Apify Google Images.
        """
        if not APIFY_TOKEN:
            return []

        cfg = LEAGUE_CONFIG.get(league_name.lower(), {})
        query = cfg.get("apify_query", f"{league_name} football news")
        emoji = cfg.get("emoji", "📰")

        try:
            # Synchronous run — blocks until done, returns dataset directly
            r = requests.post(
                "https://api.apify.com/v2/acts/johnvc~GoogleNewsAPI"
                "/run-sync-get-dataset-items",
                params={"token": APIFY_TOKEN},
                json={
                    "q": query,
                    "hl": "en",
                    "max_pages": 1,        # one results page, about 10 to 25 articles
                    "time_range": "week",  # newest first; the 2-day check below still applies
                },
                timeout=60,  # Apify may take up to 30s
            )
            if r.status_code not in (200, 201):  # run-sync answers 201 Created
                self.stdout.write(self.style.WARNING(
                    f"  ⚠️  Apify returned HTTP {r.status_code}"
                ))
                return []
            # One dataset item per results page; the articles are in news_results
            items = [a for page in r.json() for a in (page.get("news_results") or [])]
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  ⚠️  Apify request failed: {e}"))
            return []

        candidates = []
        for item in items:
            title   = self._clean_title(item.get("title", "") or "", item.get("source", "") or "")
            desc    = item.get("description", "") or item.get("snippet", "") or ""
            # published_at is "2026-01-11 11:30:00 UTC"; make it ISO for _is_recent
            pub     = (item.get("published_at", "") or "").replace(" UTC", "+00:00")
            source  = item.get("source", "") or item.get("publisher", "") or ""

            if not title or len(title) < 15:
                continue
            if not self._is_recent(pub):
                continue
            if self._is_spam(title) or self._is_spam(desc):
                continue
            if self._is_truncated(title):
                continue
            if not self._is_relevant(title, desc, league_name, team_names):
                continue

            # Pick a varied caption wrapper, avoid repeating this run
            available = [i for i in range(len(_NEWS_WRAPPERS)) if i not in self._used_wrappers]
            if not available:
                self._used_wrappers.clear()
                available = list(range(len(_NEWS_WRAPPERS)))
            idx = random.choice(available)
            self._used_wrappers.append(idx)

            caption_line = _NEWS_WRAPPERS[idx].format(emoji=emoji, title=title)
            body = desc[:200].strip()
            source_line = f"(via {source})" if source else ""
            tags = f"#{league_name.replace(' ', '')} #ConnectDial"

            text = f"{caption_line}\n\n{body}{'...' if len(desc)>200 else ''}\n\n{source_line} {tags}".strip()
            candidates.append({"text": text, "title": title})

        return candidates

    # ─── SOURCE 4: NewsAPI (fallback) ────────────────────────────────────────
    def _fetch_newsapi(self, league_name, team_names):
        if not NEWS_API_KEY:
            return []
        query = "FIFA World Cup 2026" if "world cup" in league_name.lower() else league_name
        from_date = (timezone.now() - timedelta(days=NEWS_MAX_AGE_DAYS)).strftime("%Y-%m-%d")
        cfg = LEAGUE_CONFIG.get(league_name.lower(), {})
        emoji = cfg.get("emoji", "📰")
        try:
            data = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": query, "searchIn": "title,description", "from": from_date,
                        "sortBy": "publishedAt", "language": "en", "pageSize": 30,
                        "apiKey": NEWS_API_KEY},
                timeout=8,
            ).json()
        except Exception:
            return []

        candidates = []
        for article in data.get("articles", []):
            title  = self._clean_title(article.get("title", "") or "",
                                       (article.get("source") or {}).get("name", "") or "")
            desc   = article.get("description", "") or ""
            pub    = article.get("publishedAt", "")
            source = (article.get("source") or {}).get("name", "") or ""

            if not title or len(title) < 15:               continue
            if not self._is_recent(pub):                   continue
            if self._is_spam(title) or self._is_spam(desc):continue
            if self._is_truncated(title):                  continue
            if not self._is_relevant(title, desc, league_name, team_names): continue

            available = [i for i in range(len(_NEWS_WRAPPERS)) if i not in self._used_wrappers]
            if not available:
                self._used_wrappers.clear()
                available = list(range(len(_NEWS_WRAPPERS)))
            idx = random.choice(available)
            self._used_wrappers.append(idx)

            caption_line = _NEWS_WRAPPERS[idx].format(emoji=emoji, title=title)
            body = desc[:200].strip()
            text = (f"{caption_line}\n\n{body}{'...' if len(desc)>200 else ''}\n\n"
                    f"(via {source}) #{league_name.replace(' ', '')} #ConnectDial").strip()
            candidates.append({"text": text, "title": title})

        return candidates

    # ─── SOURCE 5: Offline template ───────────────────────────────────────────
    _OPENERS = ["Hot take:", "Real talk —", "Say it louder:", "Stat of the day:",
                "Calling it now —", "Quietly brilliant:", "Unpopular opinion?",
                "Matchday thought:", "This needs saying:"]
    _TAKES = [
        "{subject} have been the story of the {league} season and it's not close.",
        "the form {subject} are showing right now is genuinely special to watch.",
        "you can't talk about {league} in 2025-26 without mentioning {subject}.",
        "{subject} on their day can beat anyone in {league}. Anyone.",
        "watching {subject} this season is a reminder of why we fell for this sport.",
        "{subject} are doing the hard work brilliantly and the table shows it.",
    ]
    _CTAS = ["Who's with me? 👇", "Tell me I'm wrong. 😤", "Drop your take. 💬",
             "Agree or disagree? 👀", ""]

    def _offline_template(self, league_name, bot_type="fan", subject=None):
        subject = subject or league_name
        if random.random() < 0.5:
            text = random.choice(OFFLINE_TEMPLATES.get(
                league_name.lower(), OFFLINE_TEMPLATES["generic"]))
        else:
            opener = random.choice(self._OPENERS)
            take   = random.choice(self._TAKES).format(subject=subject, league=league_name)
            cta    = random.choice(self._CTAS)
            tag    = league_name.replace(" ", "")
            text   = f"{opener} {take}" + (f" {cta}" if cta else "")
            text   = f"{text} #{tag} #ConnectDial"
        return _apply_persona(text, bot_type)

    # ─── MAIN ────────────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        league_query = options["league_name"]
        source_pref  = options["source"]
        dry_run      = options.get("dry_run", False)

        league = League.objects.filter(name__icontains=league_query).first()
        if not league:
            self.stdout.write(self.style.ERROR(f"League '{league_query}' not found."))
            return

        cfg        = LEAGUE_CONFIG.get(league.name.lower(), {})
        league_id  = cfg.get("api_id")
        fd_code    = cfg.get("fd_code")
        season     = cfg.get("season", 2025)
        tags_cfg   = cfg.get("hashtags", [])
        team_names = list(Team.objects.filter(league=league).values_list("name", flat=True))

        # Pick a bot under daily cap
        bot = None
        for candidate in User.objects.filter(
            profile__is_bot=True, favorite_league=league
        ).order_by("?")[:10]:
            if self._bot_post_count_today(candidate) < 3:
                bot = candidate
                break
        if not bot:
            bot = User.objects.filter(profile__is_bot=True).order_by("?").first()
            if not bot:
                self.stdout.write(self.style.ERROR("No bots found."))
                return
            bot.favorite_league = league
            bot.save()

        bot_type = getattr(bot, "account_type", "fan") or "fan"
        self.stdout.write(f"🤖 @{bot.username} [{bot_type}] → {league.name}")

        content = None
        source_label = "Template"

        # ── Cascade ──────────────────────────────────────────────────────────
        if source_pref in ("auto", "apifootball") and league_id and RAPID_API_KEY:
            self.stdout.write("  📡 API-Football...")
            posts = self._fetch_apifootball(league_id, league.name, season)
            if posts:
                content      = random.choice(posts)
                source_label = "API-Football"
                self.stdout.write(self.style.SUCCESS("  ✅ Live score data"))

        if not content and source_pref in ("auto", "football-data") and fd_code and FOOTBALL_DATA_API_KEY:
            self.stdout.write("  📡 football-data.org...")
            posts = self._fetch_football_data(fd_code, league.name)
            if posts:
                content      = random.choice(posts)
                source_label = "football-data.org"
                self.stdout.write(self.style.SUCCESS("  ✅ Standings/results data"))

        if not content and source_pref in ("auto", "apify"):
            self.stdout.write("  🕷️  Apify Google News...")
            candidates = self._fetch_apify_news(league.name, team_names)
            for cand in candidates:
                if self._seen_globally(cand["title"]):
                    continue
                content      = cand["text"]
                source_label = "Apify"
                self.stdout.write(self.style.SUCCESS(
                    f"  ✅ Apify headline: {cand['title'][:70]}"
                ))
                break
            if not content:
                self.stdout.write("  ⏭️  Apify: no fresh on-topic articles — trying NewsAPI...")

        if not content and source_pref in ("auto", "newsapi"):
            self.stdout.write("  📰 NewsAPI...")
            candidates = self._fetch_newsapi(league.name, team_names)
            for cand in candidates:
                if self._seen_globally(cand["title"]):
                    continue
                content      = cand["text"]
                source_label = "NewsAPI"
                self.stdout.write(self.style.SUCCESS(
                    f"  ✅ NewsAPI headline: {cand['title'][:70]}"
                ))
                break

        if not content:
            self.stdout.write("  📋 Offline template...")
            fav_team = getattr(bot, "favorite_team", None)
            subj     = fav_team.name if fav_team else league.name
            content  = self._offline_template(league.name, bot_type, subject=subj)
            for _ in range(12):
                h   = hashlib.md5(content.encode()).hexdigest()[:8]
                if not self._already_posted_this_week(bot, h) and not self._seen_globally(content, days=1):
                    break
                content = self._offline_template(league.name, bot_type, subject=subj)
            source_label = "Template"

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"\n[DRY RUN] Source: {source_label}\n{content}\n"
            ))
            return

        # ── Create post ───────────────────────────────────────────────────────
        teams = list(Team.objects.filter(league=league))
        target_team = getattr(bot, "favorite_team", None) or (random.choice(teams) if teams else None)

        new_post = Post.objects.create(
            author=bot,
            content=content,
            post_type="text",  # upgrade to 'image' once media attached below
            league=league,
            team=target_team,
            is_short=False,
        )

        # ── Image: Apify Google Images (content-matched) ─────────────────────
        fav_team_name = getattr(bot, "favorite_team", None)
        fav_team_name = fav_team_name.name if fav_team_name else None
        img_query = self._build_image_query(
            content, source_label, league.name, fav_team_name
        )
        self.stdout.write(f"  🔍 Image query: {img_query}")

        if APIFY_TOKEN:
            img_data = self._fetch_image_apify(img_query)
            if img_data:
                try:
                    new_post.media_file.save(
                        f"post_{new_post.id}.jpg",
                        ContentFile(img_data),
                        save=True,
                    )
                    new_post.post_type = "image"
                    new_post.save(update_fields=["post_type"])
                    self.stdout.write("  🖼️  Apify image attached")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Image save failed: {e}"))
            else:
                self.stdout.write("  ℹ️  Apify returned no image for this query")
        else:
            self.stdout.write("  ℹ️  No image — set APIFY_TOKEN to enable images")

        # ── Hashtags ──────────────────────────────────────────────────────────
        base_tags = ["Sports", "ConnectDial", league.name.replace(" ", "")]
        for t in list(set(base_tags + tags_cfg)):
            tag_obj, _ = Hashtag.objects.get_or_create(name=t)
            new_post.hashtags.add(tag_obj)

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ POSTED — @{bot.username} [{bot_type}]\n"
            f"   League : {league.name}\n"
            f"   Source : {source_label}\n"
            f"   Preview: {content[:120]}...\n"
        ))