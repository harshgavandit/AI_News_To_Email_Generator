# English-language source policy

Informa AI gives readers a daily overview of global technology news in English. Each story links to the original publisher for the full article.

The product is a discovery layer for daily global technology and AI news: readers browse headlines, short summaries and relevant details, then follow a direct link to the publisher for the full story. We do not need to reproduce full articles or force every source to publish on a schedule.

## Source selection

- Add only English-language feeds or official English editions. Select publishers by the language of their content, regardless of where they are based.
- Give priority to reputable outlets with original reporting in underrepresented regions and topics. Include regional technology publications, official announcements, engineering blogs, research, standards, and security advisories.
- Preserve a broad directory of reliable sources. Do not reject, remove, or mark a source failed only because it has published nothing in the last 90 days; quiet periods are normal.
- Use a publisher-declared RSS or Atom feed, documented API, or another permitted endpoint. Review the publisher, attribution, article URL patterns, and content rights before promotion.
- Check the language of actual headlines and excerpts in the feed. A new source must declare English. When a recent sample exists, it must contain at least 80% verified English and zero detected non-English entries; ambiguous entries count against the threshold. If a reputable English-language source has no recent entries to sample, review its official language designation and feed format manually, and keep it classified as quiet until it publishes again.
- Require a verified English headline or enough English headline and excerpt text to identify the story reliably. Skip new items when the language is undetermined or their supplied excerpt is detected as non-English.
- Keep existing multilingual feeds and archived articles. An on-device English preview can help readers understand a legacy headline and excerpt. It does not qualify a non-English feed for addition.

## Reading and attribution

- Show the original publisher name, publication date when available, and a direct link to the original. Keep the supplied headline and a short excerpt or a clearly labeled summary.
- Leave the full article and language options to the publisher. Respect paywalls and publisher restrictions. Label machine-translated previews and preserve access to the original text and link.
- Mark uncertain language as undetermined. Headlines that are mostly product names, version numbers, or code may provide too little text for reliable identification.

## Synchronization and verification

- Refresh eligible feeds twice daily, at 8:00 a.m. and 8:00 p.m. India time. Run a targeted check only when necessary. Ordinary builds, tests, and interface or ranking changes should use fixtures or archived data.
- Distinguish feed health from publication activity. A reachable, parseable feed that returns no new eligible articles is valid and quiet, not failed. Mark a feed failed only when checks confirm an integration problem, such as repeated transport errors, invalid feed data, or a missing endpoint; retain reliable sources through quiet periods.
- Respect rate limits and backoff, preserve archived content during outages, and record feed availability, last check time, and latest publication time separately. Freshness describes when a feed was checked; it does not require the publisher to have posted recently.
- Evaluate additions by the distinct, relevant stories they contribute after deduplication. Record the region, subject, publisher, feed endpoint, and review date for each approved addition.

The [source network guide](SOURCE-NETWORK.md) documents the validation and promotion commands.
