# Quickstart

## What this app does

This app turns RSS feeds into daily editorial candidates.

Pipeline outcome:

- ranked topics (`data/daily_board.md`)
- generated outlines (`data/top_outlines.md`)
- evidence pack (`data/research_pack.json`)

## One-time setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
cp .env.example .env
```

## Configure sources

Edit `feeds.txt` and add one RSS/Atom URL per line.

Example:

```text
https://www.reddit.com/r/programming/hot.rss
https://www.reddit.com/r/MachineLearning/new.rss
```

## First full run

```bash
python3 run_pipeline.py
```

Expected outputs after a successful run:

- `data/daily_board.md`
- `data/top_outlines.md`
- `data/research_pack.json`
- `data/daily-blog.db`

## Fast health check

```bash
python3 -m unittest discover -s tests
```
