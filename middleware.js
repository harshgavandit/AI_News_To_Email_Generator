import { next } from "@vercel/functions";
import { checkBotId } from "botid/server";

export const config = {
  runtime: "nodejs",
  matcher: "/api/intelligence/watch-draft",
};

export default async function middleware(request) {
  if (request.method !== "POST") return next();
  const headers = { "Cache-Control": "no-store" };
  try {
    const verdict = await checkBotId({ advancedOptions: { checkLevel: "basic" } });
    if (verdict.isBot === false && !verdict.bypassed) return next();
    if (verdict.isBot === true) {
      return Response.json({ detail: "The browser verification did not pass. Reload the page or set the watch filters directly." },
        { status: 403, headers });
    }
  } catch {
    console.warn("BotID could not verify the watch draft request.");
  }
  return Response.json({ detail: "Browser verification is temporarily unavailable. You can set the watch filters directly." },
    { status: 503, headers });
}
