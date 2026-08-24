# ColonyV

Automated AI video news pipeline. Monitors RSS feeds, researches stories with LLMs, writes scripts, renders portrait videos (1080x1920), and publishes to YouTube — all from a web dashboard.

## How It Works

```
RSS Feeds → Monitor → Research → Scriptwriter → Video Renderer → YouTube
              (LLM)    (LLM)      (LLM)        (Remotion)      (OAuth2)
```

**6 autonomous agents** run sequentially per story:

| Step | Agent | What it does | Output |
|------|-------|-------------|--------|
| 1 | **Monitor** | Scans RSS feeds, scores stories by relevance/novelty/urgency via LLM | `*_monitor.json` |
| 2 | **Research** | Crawls source URLs, extracts content, fact-checks via LLM | `*_research.json` |
| 3 | **Scriptwriter** | Generates hook/body/CTA script with visual beats via LLM | `*_script.json` |
| 4 | **Producer** | TTS narration + Remotion video render (portrait 1080x1920) | `*.mp4` |
| 5 | **Publisher** | OAuth2 upload to YouTube with title/description/tags | YouTube URL |
| 6 | **Analyst** | Post-run performance analysis, learns from feedback signals | `analyst_output.json` |

## Tech Stack

- **LLM**: Groq via LiteLLM (`groq/openai/gpt-oss-120b`)
- **TTS**: edge-tts (`en-US-AndrewNeural`)
- **Video**: Remotion 4.0.514 + Chromium
- **Dashboard**: FastAPI + Jinja2 + WebSocket (10-tab SPA)
- **YouTube**: Google API OAuth2 with auto token refresh
- **Framework**: AWS Strands Agents SDK

## Prerequisites

- Python 3.13+
- Node.js 18+
- Chromium (`/usr/bin/chromium`)
- FFmpeg
- A [Groq API key](https://console.groq.com) (free tier works)
- A Google Cloud project with YouTube Data API v3 enabled (for publishing)

## Installation

```bash
# Clone
git clone https://github.com/salmansanusisani/colonyv.git
cd colonyv

# Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Node dependencies (Producer)
cd producer && npm install && cd ..

# Set your Groq API key
export GROQ_API_KEY="gsk_..."
```

## Running

### Web Dashboard

```bash
source .venv/bin/activate
python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — 10 tabs:

| Tab | Purpose |
|-----|---------|
| **Pipeline** | Start/stop pipeline, live terminal logs, progress bar |
| **Past Runs** | History of all runs, click for per-story detail modal |
| **Analytics** | Charts: stories/day, avg score, YouTube views, success rate |
| **YouTube** | Connect/disconnect channel, view uploaded videos, retry failed |
| **Feeds** | Edit/add/remove RSS feeds, enable/disable per feed |
| **Scheduler** | Set auto-run interval (hourly/daily/weekly), next run time |
| **Alerts** | Configure Slack webhook or email notifications |
| **Costs** | LLM call counts, estimated spend per run |
| **Logs** | Full terminal output from every agent (streams live via WebSocket) |
| **Manual** | Architecture guide, tab-by-tab docs, tech stack reference |

### CLI

```bash
# Run full pipeline (1 story, skip YouTube)
python3 agents/pipeline.py --stories 1 --skip-publish

# Run with sandbox mode (no YouTube upload)
python3 agents/pipeline.py --stories 2 --sandbox

# Run individual agents
python3 agents/monitor/monitor.py --top 5
python3 agents/research/research.py --story-json output/xxx_monitor.json
python3 agents/scriptwriter/scriptwriter.py --research-json output/xxx_research.json
python3 agents/publisher/youtube.py upload video.mp4 --title "Title" --privacy unlisted
python3 agents/publisher/youtube.py auth  # Re-authenticate YouTube
```

### YouTube Setup

1. Create a Google Cloud project at [console.cloud.google.com](https://console.cloud.google.com)
2. Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop App type)
4. Download `client_secret.json` and place it at `agents/publisher/client_secret.json`
5. Either:
   - **Dashboard**: Go to YouTube tab → Upload Secret → Connect (browser popup flow)
   - **CLI**: `python3 agents/publisher/youtube.py auth`
6. First upload will open a browser for Google consent

### Custom RSS Feeds

Edit `agents/monitor/feeds.json` or use the **Feeds** tab in the dashboard:

```json
[
  {
    "name": "TechCrunch AI",
    "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "enabled": true,
    "category": "tech"
  }
]
```

## Project Structure

```
colonyv/
├── agents/
│   ├── monitor/monitor.py      # RSS feed scanner + LLM scoring
│   ├── research/research.py    # Web crawl + extraction + LLM analysis
│   ├── scriptwriter/scriptwriter.py  # LLM script generation
│   ├── publisher/youtube.py    # YouTube OAuth2 + upload
│   ├── analyst/analyst.py      # Performance analysis + learning
│   ├── pipeline.py             # Sequential pipeline orchestrator
│   ├── cleanup.py              # Old output cleanup
│   └── status.py               # Health checks + recent runs
├── producer/
│   ├── build_video.py          # TTS + SFX + image gen + Remotion render
│   ├── src/
│   │   ├── Video.tsx           # Main Remotion composition
│   │   ├── Root.tsx            # Composition registration
│   │   └── index.ts            # Entry point
│   └── public/                 # Audio, images, SFX
├── dashboard/
│   ├── app.py                  # FastAPI backend (API + pipeline runner)
│   └── templates/dashboard.html  # 10-tab SPA frontend
├── contracts/                  # JSON schemas for all agent I/O
├── tests/
│   ├── test_parser.py          # JSON parser tests
│   └── test_agents.py          # Agent integration tests
├── requirements.txt
├── .gitignore
└── README.md
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for LLM calls |
| `REMOTION_CHROMIUM_EXECUTABLE_PATH` | No | Path to Chromium (default: `/usr/bin/chromium`) |

## Key Files

| File | Purpose |
|------|---------|
| `agents/monitor/feeds.json` | RSS feed URLs (dashboard-editable) |
| `agents/monitor/seen.json` | Dedup state — already-processed stories |
| `agents/publisher/youtube_token.json` | YouTube OAuth2 tokens (auto-generated) |
| `output/cost_log.json` | LLM cost tracking across runs |
| `output/feedback_signals.json` | Analyst learned signals |

## License

MIT
