# Invome Content Autopilot

A small always-on web app for Invome that:

1. Generates a fresh Invome marketing post.
2. Creates a branded 1080x1920 image and a 10-second vertical MP4 automatically.
3. Publishes directly to the InvoMe Facebook Page through Meta's official API.
4. Repeats on a daily schedule when Autopilot is ON.

## What is already built

- Invome-specific content templates.
- Optional OpenAI-powered copy generation.
- Automatic branded video creation using Pillow + FFmpeg.
- Facebook-only Meta publishing connector.
- Safe test mode that uploads an unpublished Facebook video.
- Simple browser dashboard.
- SQLite post history and failure logging.
- Background scheduler.
- Dockerfile and Render deployment config.

## One-time setup

Automatic publishing uses a Meta system-user token with `pages_manage_posts`, `pages_read_engagement`, and `pages_show_list`. In Railway set `FACEBOOK_PAGE_ACCESS_TOKEN`, `FACEBOOK_PAGE_ID`, `FACEBOOK_GRAPH_API_VERSION`, and optionally `FACEBOOK_TIMEZONE` (defaults to `America/New_York`). Never commit the token to GitHub.

For AI-written copy, add `OPENAI_API_KEY` and set `OPENAI_MODEL` to a model available in your OpenAI API account. If you don't add these, Invome Autopilot still works using the built-in content library.

Set `BASE_URL` to the public Railway URL so Facebook can fetch generated media.

## Controlled test

1. Leave Publishing mode on **TEST — drafts only** and Autopilot **OFF**.
2. Click **Send Controlled Unpublished Test**.
3. Review the uploaded video in Meta's unpublished content. The request uses `published=false`, so it does not appear on the Page timeline.

## Enabling live autopilot

Only after the controlled upload looks correct: confirm the InvoMe Facebook Page, switch Publishing mode to **LIVE — auto-publish**, then turn Autopilot **ON**. Both settings are required; the scheduled job and API route refuse to publish if either safety control is off. TikTok and Instagram are not targeted.

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
