from flask import Flask, render_template, jsonify, request
from datetime import datetime
import pytz
import time
import requests
import threading
import socket

app = Flask(__name__)

# -----------------------------
# Health check (Render / uptime)
# -----------------------------
@app.route("/health")
def health():
    return "ok", 200


# ------------------------------------------------------
# Servers + DNS + region tag
# ------------------------------------------------------
servers = [
    # --- North America ---
    {"name": "US-East", "region": "North America", "timezone": "US/Eastern",
     "url": "https://dynamodb.us-east-1.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
    {"name": "US-West", "region": "North America", "timezone": "US/Pacific",
     "url": "https://dynamodb.us-west-2.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
    {"name": "US-Central", "region": "North America", "timezone": "US/Central",
     "url": "https://dynamodb.us-east-2.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
    {"name": "US-South", "region": "North America", "timezone": "US/Central",
     "url": "https://dynamodb.us-west-1.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},

    # --- Europe ---
    {"name": "Europe-West", "region": "Europe", "timezone": "Europe/Berlin",
     "url": "https://dynamodb.eu-west-1.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},
    {"name": "Europe-East", "region": "Europe", "timezone": "Europe/Kyiv",
     "url": "https://dynamodb.eu-central-1.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},
    {"name": "UK", "region": "Europe", "timezone": "Europe/London",
     "url": "https://dynamodb.eu-west-2.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},
    {"name": "Europe-North", "region": "Europe", "timezone": "Europe/Stockholm",
     "url": "https://dynamodb.eu-north-1.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},

    # --- South America ---
    {"name": "Brazil", "region": "South America", "timezone": "America/Sao_Paulo",
     "url": "https://dynamodb.sa-east-1.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},

    # --- Asia-Pacific ---
    {"name": "Japan", "region": "Asia-Pacific", "timezone": "Asia/Tokyo",
     "url": "https://dynamodb.ap-northeast-1.amazonaws.com/", "primary_dns": "8.8.8.8", "secondary_dns": "8.8.4.4"},
    {"name": "South Korea", "region": "Asia-Pacific", "timezone": "Asia/Seoul",
     "url": "https://dynamodb.ap-northeast-2.amazonaws.com/", "primary_dns": "8.8.8.8", "secondary_dns": "8.8.4.4"},
    {"name": "Singapore", "region": "Asia-Pacific", "timezone": "Asia/Singapore",
     "url": "https://dynamodb.ap-southeast-1.amazonaws.com/", "primary_dns": "8.8.8.8", "secondary_dns": "8.8.4.4"},
    {"name": "Hong Kong", "region": "Asia-Pacific", "timezone": "Asia/Hong_Kong",
     "url": "https://dynamodb.ap-east-1.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},
    {"name": "Mumbai", "region": "Asia-Pacific", "timezone": "Asia/Kolkata",
     "url": "https://dynamodb.ap-south-1.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},

    # --- Oceania ---
    {"name": "Australia-East", "region": "Oceania", "timezone": "Australia/Sydney",
     "url": "https://dynamodb.ap-southeast-2.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
    # Melbourne region is ap-southeast-4; keeping as distinct AU endpoint
    {"name": "Australia-West", "region": "Oceania", "timezone": "Australia/Perth",
     "url": "https://dynamodb.ap-southeast-4.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
    # NZ has no AWS region; keeping Sydney as "closest practical"
    {"name": "New Zealand", "region": "Oceania", "timezone": "Pacific/Auckland",
     "url": "https://dynamodb.ap-southeast-2.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},

    # --- Africa / Middle East ---
    {"name": "South Africa", "region": "Africa", "timezone": "Africa/Johannesburg",
     "url": "https://dynamodb.af-south-1.amazonaws.com/", "primary_dns": "9.9.9.9", "secondary_dns": "149.112.112.112"},
    {"name": "Dubai", "region": "Middle East", "timezone": "Asia/Dubai",
     "url": "https://dynamodb.me-central-1.amazonaws.com/", "primary_dns": "1.1.1.1", "secondary_dns": "1.0.0.1"},
]

# ------------------------------------------------------
# Ping state + smoothing + history
# ------------------------------------------------------
PING_STATE = {s["name"]: {"ema": None, "last_raw": None} for s in servers}
PING_HISTORY = {s["name"]: [] for s in servers}
SERVER_CACHE = []
CACHE_LOCK = threading.Lock()

HOLIDAYS = {(12, 24), (12, 25), (12, 31), (1, 1), (7, 4), (10, 31)}
TOURNAMENT_MONTHS = {3, 4, 5, 9, 10, 11}

def is_holiday(dt):
    return (dt.month, dt.day) in HOLIDAYS


# ------------------------------------------------------
# ✅ BEST OVERALL: TCP connect “ping” (port 443)
# ------------------------------------------------------
PING_TIMEOUT = 0.8  # seconds (single source of truth)

def _host_from_url(url: str) -> str:
    # accepts full URL; returns hostname without port
    if "://" in url:
        url = url.split("://", 1)[1]
    host = url.split("/", 1)[0]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host

def measure_ping(url, attempts=3, timeout=PING_TIMEOUT):
    """
    TCP connect time to port 443.
    Failed attempts count as full timeout (so failures look slow, not fast).
    """
    host = _host_from_url(url)
    vals = []
    for _ in range(attempts):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                pass
            vals.append((time.perf_counter() - start) * 1000)
        except Exception:
            vals.append(timeout * 1000)
    return (sum(vals) / len(vals)) if vals else (timeout * 1000)


# ------------------------------------------------------
# Enhancements: Activity / Trend / Confidence
# ------------------------------------------------------
def get_activity_level(server):
    tz = pytz.timezone(server["timezone"])
    now = datetime.now(tz)
    hour = now.hour
    weekday = now.weekday()

    score = 0
    if 18 <= hour <= 23:
        score += 3
    elif 3 <= hour < 8:
        score -= 2

    if weekday in (4, 5, 6):
        score += 2
    if is_holiday(now):
        score += 2
    if now.month in TOURNAMENT_MONTHS:
        score += 1
    if server["region"] in ("Asia-Pacific", "Europe"):
        score += 1

    if score <= 1:
        return "Low"
    if score <= 4:
        return "Medium"
    return "High"

def push_history(server_name, ping_ui):
    h = PING_HISTORY[server_name]
    h.append(int(ping_ui))
    if len(h) > 6:
        h.pop(0)

def get_trend(server_name):
    h = PING_HISTORY[server_name]
    if len(h) < 3:
        return "Stable"
    if h[-1] < h[-2] < h[-3]:
        return "Cooling"
    if h[-1] > h[-2] > h[-3]:
        return "Heating"
    return "Stable"

def get_confidence(server_name):
    h = PING_HISTORY[server_name]
    if len(h) < 4:
        return "Low"
    spread = max(h) - min(h)
    if spread <= 10:
        return "High"
    if spread <= 25:
        return "Medium"
    return "Low"


# ------------------------------------------------------
# Ping buckets → relative Botty / Average / Sweaty
# ------------------------------------------------------
def compute_ping_buckets(pings):
    sorted_p = sorted(pings)
    n = len(sorted_p)
    if n == 0:
        return 120.0, 180.0
    idx33 = max(0, int((n - 1) * 0.33))
    idx66 = max(0, int((n - 1) * 0.66))
    return float(sorted_p[idx33]), float(sorted_p[idx66])

def get_status(server, ping_ms: float, bot_cutoff: float, avg_cutoff: float):
    tz = pytz.timezone(server["timezone"])
    now = datetime.now(tz)
    hour = now.hour
    weekday = now.weekday()

    bot_max = float(bot_cutoff)
    avg_max = float(avg_cutoff)

    if weekday in (4, 5, 6):
        bot_max -= 3
        avg_max -= 7
    if weekday == 4 and 18 <= hour <= 23:
        bot_max -= 7
        avg_max -= 10
    if 18 <= hour <= 23:
        bot_max -= 3
        avg_max -= 5
    if 3 <= hour < 8:
        bot_max += 8
        avg_max += 12
    if server["region"] in ("Asia-Pacific", "Europe") and 18 <= hour <= 23:
        avg_max -= 3
    if is_holiday(now):
        avg_max -= 8
    if now.month in TOURNAMENT_MONTHS:
        avg_max -= 5

    # keep Average band alive (prevents only Botty/Sweaty)
    min_gap = 12.0
    if avg_max < bot_max + min_gap:
        avg_max = bot_max + min_gap

    if ping_ms <= bot_max:
        return "Botty"
    if ping_ms <= avg_max:
        return "Average"
    return "Sweaty"


# ------------------------------------------------------
# Build JSON snapshot for API
# ------------------------------------------------------
def build_snapshot():
    # Ensure EMA exists
    for s in servers:
        state = PING_STATE[s["name"]]
        if state["ema"] is None:
            state["ema"] = measure_ping(s["url"])

    timeout_ms = PING_TIMEOUT * 1000.0

    # Compute buckets using only healthy pings (Down shouldn't distort the percentiles)
    healthy_pings = [
        float(PING_STATE[s["name"]]["ema"])
        for s in servers
        if float(PING_STATE[s["name"]]["ema"]) < (0.95 * timeout_ms)
    ]
    if not healthy_pings:
        healthy_pings = [float(PING_STATE[s["name"]]["ema"]) for s in servers]

    bot_cutoff, avg_cutoff = compute_ping_buckets(healthy_pings)

    data = []
    for s in servers:
        state = PING_STATE[s["name"]]
        ping_raw = float(state["ema"])
        ping_ui = int(min(max(round(ping_raw), 1), 999))

        push_history(s["name"], ping_ui)

        # ✅ Down detection consistent with timeout
        is_down = ping_raw >= (0.95 * timeout_ms)

        tz = pytz.timezone(s["timezone"])
        data.append({
            "name": s["name"],
            "region": s["region"],
            "ping": ping_ui,
            "status": ("Down" if is_down else get_status(s, ping_raw, bot_cutoff, avg_cutoff)),
            "trend": get_trend(s["name"]),
            "confidence": get_confidence(s["name"]),
            "activity": get_activity_level(s),
            "local_time": datetime.now(tz).strftime("%H:%M"),
            "primary_dns": s["primary_dns"],
            "secondary_dns": s["secondary_dns"],
        })
    return data


# ------------------------------------------------------
# Background refresh loop
# ------------------------------------------------------
def refresh_loop(interval=8, alpha=0.40):
    global SERVER_CACHE
    while True:
        try:
            for s in servers:
                raw = measure_ping(s["url"])
                state = PING_STATE[s["name"]]
                state["ema"] = raw if state["ema"] is None else (alpha * raw + (1 - alpha) * state["ema"])
                state["last_raw"] = raw

            snap = build_snapshot()
            with CACHE_LOCK:
                SERVER_CACHE = snap
        except Exception as e:
            print("refresh error:", e)

        time.sleep(interval)


# ------------------------------------------------------
# Player IP → approximate region / timezone
# ------------------------------------------------------
def get_client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or ""

def mask_ip(ip: str) -> str:
    if not ip:
        return "unknown"
    if ip.startswith(("127.", "192.168.", "10.")) or ip == "::1":
        return "local / LAN"
    if ":" in ip:
        return ip.split(":", 1)[0] + "::/64"
    parts = ip.split(".")
    return (".".join(parts[:3]) + ".x") if len(parts) == 4 else ip

def lookup_player_region(ip: str):
    if not ip or ip.startswith(("127.", "192.168.", "10.")) or ip == "::1":
        local_tz = datetime.now().astimezone().tzinfo
        return "Local / Testing", str(local_tz)

    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=0.8)
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError("geo failed")

        country = data.get("countryCode", "")
        tzname = data.get("timezone", "Unknown")

        if country in ("US", "CA", "MX"):
            region = "North America"
        elif country in ("BR", "AR", "CL", "PE", "CO"):
            region = "South America"
        elif country in ("GB", "DE", "FR", "ES", "IT", "NL", "PL", "SE", "NO", "DK", "IE", "PT", "FI"):
            region = "Europe"
        elif country in ("AU", "NZ"):
            region = "Oceania"
        elif country in ("JP", "KR", "CN", "SG", "HK", "TW", "PH", "TH", "VN", "MY", "ID"):
            region = "Asia-Pacific"
        elif country in ("ZA", "NG", "EG", "KE", "MA"):
            region = "Africa"
        elif country in ("AE", "SA", "QA", "KW", "BH", "OM", "TR", "IL"):
            region = "Middle East"
        else:
            region = "Global"

        return region, tzname
    except Exception:
        local_tz = datetime.now().astimezone().tzinfo
        return "Unknown", str(local_tz)


# ------------------------------------------------------
# Routes
# ------------------------------------------------------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/servers")
def servers_page():
    return render_template("index.html")

@app.route("/dns")
def dns_page():
    return render_template("dns.html")

@app.route("/api/status")
def api_status():
    with CACHE_LOCK:
        if isinstance(SERVER_CACHE, list) and SERVER_CACHE:
            return jsonify(SERVER_CACHE)
    return jsonify(build_snapshot())

@app.route("/api/player")
def api_player():
    ip = get_client_ip()
    region, tzname = lookup_player_region(ip)
    return jsonify({"ip": mask_ip(ip), "region": region, "timezone": tzname})


# ------------------------------------------------------
# Start background + run app
# ------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=refresh_loop, daemon=True).start()
    app.run(debug=True, use_reloader=False)
