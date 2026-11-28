# Informa AI MCP connector

The connector URL is `https://getinformdaily.com/mcp`. For a local server, use `http://127.0.0.1:8000/mcp`. Configure a remote **Streamable HTTP** server with **no authentication**. The [connection guide](https://getinformdaily.com/connect.html) covers Claude, ChatGPT, Cursor, OpenCode and Google Antigravity.

- **OpenCode 2.** Run `opencode mcp add informa-ai --url https://getinformdaily.com/mcp` in your project, then run `opencode mcp list`. For OpenCode 1, use the configuration under **Setup for OpenCode 1**. [Informa’s OpenCode setup](https://getinformdaily.com/connect.html#opencode) · [OpenCode MCP guide](https://opencode.ai/docs/mcp-servers/)
- **Google Antigravity.** In the agent panel, open **MCP Servers → Manage MCP Servers → View raw config**. In `mcp_config.json`, set `mcpServers.informa-ai.serverUrl` to `https://getinformdaily.com/mcp`. [Informa’s Antigravity setup](https://getinformdaily.com/connect.html#antigravity) · [Antigravity MCP guide](https://antigravity.google/docs/ide-mcp)

The endpoint uses the official Python MCP SDK with JSON responses and no server-side session. It implements the SDK's initialization, ping, tool listing and tool call support. Each request owns its lifecycle, so handling a request does not rely on an ASGI startup hook or a warm function. Long-lived SSE sessions and browser cross-origin calls are outside the connector's transport.

| Tool | Arguments | Public result |
| --- | --- | --- |
| `search_news` | `query`, optional `topic`, `region`, `days` (1–30), `limit` (1–20) | Ranked archive headlines and excerpts |
| `get_story` | `id` | A public story with matching publisher coverage |
| `latest_headlines` | Optional `topic`, `limit` (1–20) | Current front-page selections and developing coverage |
| `get_tracker` | `name` of `ai-models`, `incidents`, `security` or `releases` | Published tracker records |
| `curiosity_cards` | Optional `subject` or theme and `limit` (1–12) | Reviewed cards and archived source excerpts |
| `weekly_recap` | Optional ISO `week`, such as `2026-W47` | A saved recap |
| `ask_informa` | `question` | The same checked answer and citations as the website |
| `deep_research` | `question`, optional `topic` and `days` (1–90) | A checked report with a summary, sections, dated coverage timeline, and numbered Informa story links |
| `list_watch_examples` | None | Public examples of plain-language technology watches |
| `preview_watch` | `sentence` (8–320 characters) | A structured watch and checked matches from a bounded sample of the last 48 hours |

`deep_research` uses the same 45-second deadline, six-hour cache, and database-backed request limits as the website’s Deep research mode. It returns a complete report in one tool response. See [Deep Ask](DEEP-ASK.md).

Watch previews draw on the public archive and share the Watch agent model budgets. They have no access to browser monitoring profiles or alert feedback. To collect future alerts, review and save a watch in the Research Desk.

Use topic and region IDs from [the public source catalog](https://getinformdaily.com/api/sources). Results link to pages on Informa and preserve publisher links. A tool error appears as an MCP `isError` result. The HTTP transport permits 120 requests per 10 minutes per IP per warm instance. `ask_informa` additionally shares the public Ask and story-question database-backed rate limit and AI budgets. Tool calls do not fetch publishers. The Curiosity tool reads source excerpts and reviewed cards without generating summaries or saving library cards.

Use `uv run python -m pytest -q tests/test_mcp_connector.py` to run the official SDK client against the FastAPI route and a temporary archive. To connect an assistant to a deployed preview, use that preview's `/mcp` URL with a client that can reach it. The connector accepts the canonical host, the linked Vercel host and Vercel's configured preview hostname. Workspace settings can determine whether a client allows custom connectors.

Client references [Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [ChatGPT custom MCP connections](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt), and [Cursor MCP](https://cursor.com/docs/mcp).
