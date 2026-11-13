# World Tech Brief

Use the existing archive to cover breaking tech stories across regions. Add independently reported news, official company releases, and official status feeds. Label the type of coverage, show timestamps and source health, and never interpret a missing feed item as proof of normal service.

1. Verify feeds with the production parser. Add reviewed URLs and a shared classification for archive filters and brief selection. Test source availability, topic filtering and cursor isolation with a temporary database.
2. Add a global edition to the existing digest endpoint: select varied, recent headlines and use attributed feed excerpts. It must work without AI, avoid duplicate incident reports in the edition, and still support the existing verified inbox preview. Keep the personalized AI edition and mail quota.
3. Put global coverage and the edition on the home page. Keep custom interests below the main news view. Show the actual time of the last check and a clear stale state.
4. Configure frequent archive refresh through an authenticated scheduled workflow and preserve the daily Vercel fallback. Run the automated suite, refresh staged production data, check today’s Microsoft reporting and NVIDIA coverage, then verify the public deployment.
