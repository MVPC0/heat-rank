Heat Rank (Global)

Heat Rank provides live, ping-based server ranking and DNS recommendations to help players find the smoothest possible online gaming experience worldwide.

FEATURES
- Live HTTP-based ping checks to global DynamoDB regions
- Relative Botty / Average / Sweaty classification using global ping percentiles
- Real-world activity realism (time-of-day, weekends, holidays, tournament seasons)
- Public JSON APIs:
  - /api/status
  - /api/player
- IP-based approximate region + timezone detection
- Global heat-map UI with best-server banner
- Light / Night / Pro Gamer / OLED themes
- Smart DNS recommendations (routing optimization only)

SUPPORTED GAMES (CONCEPTUAL)
- PUBG
- Call of Duty: Warzone
- Apex Legends
- Fortnite
- Overwatch 2
- Valorant
- Counter-Strike 2 (CS2)
- Destiny 2

HOW IT WORKS
- Uses live ping data smoothed with EMA
- Servers ranked relative to each other
- Activity modifiers adjust ratings dynamically
- Prevents ratings from getting stuck as always sweaty or botty

RUNNING LOCALLY
pip install -r requirements.txt
python app.py

Open in browser:
http://127.0.0.1:5000/

NOTES
DNS does not force matchmaking.
Matchmaking is always controlled by the game.

LICENSE
MIT License
© MVP Production  (MVPC0)
