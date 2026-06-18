"""Cron job entrypoints (Slice 4). Railway runs these as separate services:

    python -m app.jobs.scrape    # daily ~06:00 UTC
    python -m app.jobs.digest    # daily ~07:00 UTC (after scrape)
"""
