# Curiosity Cards upkeep

Curiosity Cards stay valuable because every reviewed card links to a live primary source and its summary
says only what that source says. Two scheduled jobs keep it that way; an editor spends about fifteen
minutes a month acting on them.

| Job | When | What it does |
| --- | --- | --- |
| `Check Curiosity Card links` | Mondays 04:17 UTC | Requests every reviewed seed URL and flags broken, moved or blocked links. Fails the run on broken links. |
| `Curiosity Cards monthly upkeep` | 1st of the month, 03:41 UTC | One report: seed link results plus recent incident write-ups that are not yet cards (reads `NEWS_DATABASE_URL`). |

Neither job fetches feeds, so the twice-daily feed schedule (08:00 and 20:00 IST) is unchanged.

## Monthly routine

1. Open the latest **Curiosity Cards monthly upkeep** run in GitHub Actions and read the job summary.
2. **Broken links.** Find the new address on the publisher's site, read the page again, and update the
   seed's `url` (and summary if the page changed). Remove the card if the page is gone for good.
   Treat **unreachable** results as network noise until a second run agrees.
3. **Review queue.** Open each queued write-up. Pick the two or three that explain a real problem and how it
   was handled. For each, read the page in full and add a `_seed(...)` entry in `app/curiosity.py` with a
   `REVIEWED_BREAKDOWNS` line and `REVIEWED_PROBLEMS` labels. Never add a number or claim the page does not state.
4. Run `uv run pytest tests/test_curiosity.py` and commit.

To run the same report locally against your archive:

```bash
uv run python -m scripts.curiosity_upkeep --days 35 --report reports/curiosity-upkeep.md
```

## Growing the collection

Add cards in small, themed batches (8 to 10) where coverage is thin, rather than chasing a total. Prefer the
company's own engineering post, postmortem or conference talk over third-party summaries.
