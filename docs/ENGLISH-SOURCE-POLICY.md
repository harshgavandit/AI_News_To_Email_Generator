# English-language source policy

Informa AI gives readers a daily overview of global technology news in English. Each story links to the original publisher for the full article.

## Source selection

- Add only English-language feeds or official English editions. Select publishers by the language of their content, regardless of where they are based.
- Give priority to reputable outlets with original reporting in underrepresented regions and topics. Include regional technology publications, official announcements, engineering blogs, research, standards, and security advisories.
- Use a publisher-declared RSS or Atom feed, documented API, or another permitted endpoint. Review the publisher, attribution, article URL patterns, and content rights before promotion.
- Check the language of actual headlines and excerpts in the feed. A new source must declare English. Its recent sample must contain at least 80% verified English and zero detected non-English entries. Ambiguous entries count against the threshold. Confirm editorial relevance and recent activity before adding the feed.
- Require a verified English headline or enough English headline and excerpt text to identify the story reliably. Skip new items when the language is undetermined or their supplied excerpt is detected as non-English.
- Keep existing multilingual feeds and archived articles. An on-device English preview can help readers understand a legacy headline and excerpt. It does not qualify a non-English feed for addition.

## Reading and attribution

- Show the original publisher name, publication date when available, and a direct link to the original. Keep the supplied headline and a short excerpt or a clearly labeled summary.
- Leave the full article and language options to the publisher. Respect paywalls and publisher restrictions. Label machine-translated previews and preserve access to the original text and link.
- Mark uncertain language as undetermined. Headlines that are mostly product names, version numbers, or code may provide too little text for reliable identification.

## Synchronization and verification

- Use the owner's requested 8 a.m. India time refresh as the routine collection window. Run a targeted check only when necessary. Ordinary builds, tests, and interface or ranking changes should use fixtures or archived data.
- Check a small group of new feeds once during review. Respect rate limits and backoff, preserve archived content during outages, and record feed availability separately from the age of the latest article.
- Evaluate additions by the distinct, relevant stories they contribute after deduplication. Record the region, subject, publisher, feed endpoint, and review date for each approved addition.

The [source network guide](SOURCE-NETWORK.md) documents the validation and promotion commands.
