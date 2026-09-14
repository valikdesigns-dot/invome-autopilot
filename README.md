# Invome Content Autopilot

A small always-on web app for Invome that:

1. Generates a fresh Invome marketing post.
2. Creates a branded 1080x1920 image and a 10-second vertical MP4 automatically.
3. Publishes the post through Ayrshare to the selected social networks.
4. Repeats on a daily schedule when Autopilot is ON.

## What is already built

- Invome-specific content templates.
- Optional OpenAI-powered copy generation.
- Automatic branded video creation using Pillow + FFmpeg.
- Facebook / Instagram / TikTok / Pinterest platform selection.
- Ayrshare publishing connector.
- Simple browser dashboard.
- SQLite post history and failure logging.
- Background scheduler.
- Dockerfile and Render deployment config.

## One-time setup

Automatic publishing requires social authorization. Create/connect the social accounts in Ayrshare, then add the Ayrshare API key to the deployed app as `AYRSHARE_API_KEY`.

For AI-written copy, add `OPENAI_API_KEY` and set `OPENAI_MODEL` to a model available in your OpenAI API account. If you don't add these, Invome Autopilot still works using the built-in content library.

Set `BASE_URL` to the public URL of the deployed app so the publishing service can fetch generated media.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

Local mode can generate content and media, but live social publishing needs a public URL for the generated media. Deploy the app for unattended posting.

## Recommended deployment

The included `Dockerfile` works on container hosts such as Render, Railway, Fly.io, or a VPS. The app needs persistent storage if you want its SQLite history to survive redeployments; for production, upgrade the database to Postgres or attach a persistent disk.

## Important platform limitation

No compliant social-media automation can bypass initial account authorization. TikTok, Meta, Pinterest, etc. ultimately require permission to post. Once authorized through the publishing provider, routine generation and publishing can be automatic.
