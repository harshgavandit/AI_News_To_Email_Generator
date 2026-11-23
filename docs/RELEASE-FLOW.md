# Release flow

Every change to Informa AI reaches production the same way:

1. **Push to `Staging`.** All new work is committed and pushed to the `Staging` branch first. Nothing is pushed directly to `main`.
2. **Open a pull request from `Staging` to `main`.** CI (`.github/workflows/ci.yml`) runs on the pull request.
3. **Review and approve.** The owner reviews the pull request and approves it before it is merged.
4. **Merge to `main`.** Vercel deploys `main` to production at getinformdaily.com.

## Notes

- Keep `Staging` a fast-forward of `main` where possible: start new work from the latest `main`, so the pull request contains only the new changes.
- Run the checks before pushing: `npm run lint`, `npm run build`, `npm test`, `uv run ruff check app tests scripts main.py` and `uv run pytest -q`.
- If a change adds tables or columns, run owner `POST /api/admin/setup` before the release reaches production (see `docs/LAUNCH.md`).
- Automated helpers (including AI assistants) follow the same flow: they push to `Staging` or hand over a branch for the owner to push there, and never merge into `main` themselves.
