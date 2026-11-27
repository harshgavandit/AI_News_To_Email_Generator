# Informa AI MCP connector

The connector URL is `https://getinformdaily.com/mcp` after deployment. For a local server, use `http://127.0.0.1:8000/mcp`. Configure a remote **Streamable HTTP** server with **no authentication**. The [connection guide](https://getinformdaily.com/connect.html) has steps and copyable configuration for Claude, ChatGPT and Cursor.

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

Use topic and region IDs from [the public source catalog](https://getinformdaily.com/api/sources). Results link to pages on Informa and preserve publisher links. A tool error appears as an MCP `isError` result. The HTTP transport permits 120 requests per 10 minutes per IP per warm instance. `ask_informa` additionally shares the public Ask and story-question database-backed rate limit and AI budgets. Tool calls do not fetch publishers. The Curiosity tool reads source excerpts and reviewed cards without generating summaries or saving library cards.

Use `uv run python -m pytest -q tests/test_mcp_connector.py` to run the official SDK client against the FastAPI route and a temporary archive. To connect an assistant to a deployed preview, use that preview's `/mcp` URL with a client that can reach it. The connector accepts the canonical host, the linked Vercel host and Vercel's configured preview hostname. Workspace settings can determine whether a client allows custom connectors.

Client references [Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [ChatGPT custom MCP connections](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt), and [Cursor MCP](https://cursor.com/docs/mcp).
