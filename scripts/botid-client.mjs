import { initBotId } from "botid/client/core";

if (!["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
  initBotId({
    protect: [{ path: "/api/intelligence/watch-draft", method: "POST", advancedOptions: { checkLevel: "basic" } }],
  });
}
