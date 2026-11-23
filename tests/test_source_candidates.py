import json

import pytest

from app.sources import DEFAULT_SOURCES, Source, validate_source
from scripts import promote_sources

PACK = "docs/research/source-candidates-2026-11-21.json"


def load_rows():
    with open(PACK, encoding="utf-8") as handle:
        return json.load(handle)


def test_candidate_pack_is_valid_new_and_english():
    rows = load_rows()
    by_id = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        rechecked = {row["id"]: row["url"] for row in json.load(handle)}
    assert len(rows) >= 150
    assert len({row["id"] for row in rows}) == len(rows) and len({row["url"] for row in rows}) == len(rows)
    for row in rows:
        # Either still a candidate, or promoted under the same id (unchanged, or corrected in the recheck pack).
        if row["id"] in by_id:
            assert by_id[row["id"]] in (row["url"], rechecked.get(row["id"]))
        else:
            assert row["url"].rstrip("/") not in known_urls
        assert row["language"] == "en" and row["url"].startswith("https://")
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))


def test_candidate_pack_covers_each_requested_area():
    rows = load_rows()
    kinds = {row["kind"] for row in rows}
    topics = {row["topic"] for row in rows}
    assert {"news", "engineering", "research", "video", "podcast"} <= kinds
    assert {"ai", "software", "security", "startups", "chips", "industry"} <= topics
    assert sum(row["coverage"] == "release" for row in rows) >= 40
    assert any(row["coverage"] == "preprint" for row in rows)


def test_promotion_adds_only_listed_candidates_and_validates(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text("[]", encoding="utf-8")
    rows = load_rows()
    added = promote_sources.promote(PACK, [rows[0]["id"], rows[1]["id"]], catalog=catalog, today="2026-11-21")
    saved = json.loads(catalog.read_text(encoding="utf-8"))
    assert added == [rows[0]["id"], rows[1]["id"]] and len(saved) == 2
    assert all(row["reviewed_at"] == "2026-11-21" and row["require_english"] for row in saved)
    assert promote_sources.promote(PACK, [rows[0]["id"]], catalog=catalog) == []  # Idempotent.
    with pytest.raises(SystemExit):
        promote_sources.promote(PACK, ["not-a-candidate"], catalog=catalog)


def test_language_policy_trusts_review_for_short_title_feeds_only():
    from types import SimpleNamespace
    from scripts.check_source_pack import english_enough, requires_english
    release = SimpleNamespace(coverage="release", kind="engineering")
    blog = SimpleNamespace(coverage="article", kind="engineering")
    assert english_enough(release, 10, 1, 0) and not english_enough(release, 10, 0, 3)
    assert english_enough(blog, 20, 13, 1) and not english_enough(blog, 20, 11, 0) and not english_enough(blog, 20, 18, 3)
    assert not requires_english({"coverage": "release", "kind": "engineering"})
    assert not requires_english({"coverage": "publisher", "kind": "video"})
    assert requires_english({"coverage": "reporting", "kind": "news"})


def test_english_only_feeds_keep_undetectable_headlines_but_drop_foreign_ones():
    from app.article_language import is_not_foreign_article
    assert is_not_foreign_article({"title": "Bun 1.3", "description": ""})
    assert is_not_foreign_article({"title": "OpenAI releases a new reasoning model for developers", "description": ""})
    assert not is_not_foreign_article({"title": "Le gouvernement français annonce un nouveau plan pour l'intelligence artificielle",
                                       "description": ""})


def test_recheck_pack_is_valid_and_promoted_unchanged():
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        rows = json.load(handle)
    by_id = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    assert len(rows) == 50 and len({row["id"] for row in rows}) == 50
    for row in rows:
        if row["id"] in by_id:
            assert by_id[row["id"]] == row["url"]  # Promoted unchanged.
        else:
            assert row["url"].rstrip("/") not in known_urls
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))


def test_promoted_release_and_video_sources_do_not_filter_by_detected_language():
    from app.sources import BY_ID
    assert not BY_ID["release-oven-sh-bun"].require_english and not BY_ID["yt-openai"].require_english
    assert BY_ID["engadget"].require_english and BY_ID["engadget"].reviewed_at


def test_a_working_feed_without_recent_posts_is_quiet_and_promotable():
    from scripts.check_source_pack import PROMOTABLE, feed_status
    assert feed_status({"available": True}, recent=[]) == "quiet"
    assert feed_status({"available": True}, recent=[{}]) == "active"
    assert feed_status({"available": False, "error": "feed_not_found"}, recent=[]) == "unavailable"
    assert {"active", "quiet"} == PROMOTABLE


def test_second_wave_pack_is_new_valid_and_never_reproposes():
    with open("docs/research/source-candidates-2026-11-21b.json", encoding="utf-8") as handle:
        wave = json.load(handle)
    earlier = load_rows()
    with open("docs/research/source-candidates-2026-11-21-recheck.json", encoding="utf-8") as handle:
        earlier += json.load(handle)
    tried = {row["id"] for row in earlier} | {row["url"].rstrip("/") for row in earlier}
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    known_urls = {source.url.rstrip("/") for source in DEFAULT_SOURCES}
    assert len(wave) >= 150
    assert len({row["id"] for row in wave}) == len(wave) and len({row["url"] for row in wave}) == len(wave)
    for row in wave:
        assert row["id"] not in tried and row["url"].rstrip("/") not in tried
        # Once promoted, a candidate keeps its id and URL; anything else must be new.
        assert promoted.get(row["id"], row["url"]) == row["url"]
        if row["id"] not in promoted:
            assert row["url"].rstrip("/") not in known_urls
        assert row["language"] == "en" and row["url"].startswith("https://")
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))
    coverage = {row["coverage"] for row in wave}
    assert {"release", "status", "advisory", "reporting", "publisher"} <= coverage
    assert {"ai", "software", "security", "chips", "startups", "outages"} <= {row["topic"] for row in wave}


def test_global_pack_2026_11_22_is_valid_and_its_checked_feeds_are_promoted():
    with open("docs/research/source-candidates-2026-11-22-global.json", encoding="utf-8") as handle:
        pack = json.load(handle)
    assert len({row["id"] for row in pack}) == len(pack) and len({row["url"] for row in pack}) == len(pack)
    for row in pack:
        assert row["language"] == "en" and row["url"].startswith("https://")
        validate_source(Source(**{key: tuple(value) if key in {"hosts", "article_paths"} else value
                                  for key, value in row.items()}))
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    checked = {"game-developer", "gamesindustry-biz", "eighty-level", "graphics-programming-weekly", "josh-comeau",
               "overreacted", "tkdodo", "addy-osmani", "css-tricks", "posthog-blog", "vespa-blog",
               # Validation run #6 (active or quiet, English confirmed).
               "tailwind-blog", "tigerbeetle-blog", "snowflake-engineering", "motherduck-blog", "nextjs-blog",
               "dagster-blog", "hotstar-tech", "railway-blog", "airtable-engineering", "trivago-tech", "semiwiki",
               "unity-blog", "plausible-blog", "cookpad-sourcediving", "dream11-engineering", "high-scalability",
               "klarna-engineering", "vite-blog"}
    # Feed addresses repaired after production checks on November 23 (see docs/LAUNCH.md).
    repaired = {"graphics-programming-weekly": "https://www.jendrikillner.com/index.xml",
                "hotstar-tech": "https://medium.com/feed/hotstar",
                "cookpad-sourcediving": "https://medium.com/feed/sourcediving",
                "dream11-engineering": "https://medium.com/feed/dream11-tech-blog",
                "klarna-engineering": "https://medium.com/feed/klarna-engineering"}
    # DoorDash was removed on November 23: it denies automated access (HTTP 403) from production.
    assert "doordash-blog" not in promoted
    for row in pack:
        assert (row["id"] in checked) == (row["id"] in promoted), row["id"]
        if row["id"] in promoted:
            assert promoted[row["id"]] == repaired.get(row["id"], row["url"])


def test_discovered_pack_2026_11_23_promotes_exactly_the_validated_feeds():
    with open("docs/research/source-candidates-2026-11-23-discovered.json", encoding="utf-8") as handle:
        pack = json.load(handle)
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    validated = {"remix-blog", "arize-blog", "mistral-news", "eurogamer-tech", "e2b-blog", "stripe-dev-blog", "tinybird-blog",
                 "zed-blog", "materialize-blog", "phonepe-engineering", "linear-now", "encore-blog", "netlify-blog",
                 "shreya-shankar"}
    for row in pack:
        assert (row["id"] in validated) == (row["id"] in promoted), row["id"]
        if row["id"] in promoted:
            assert promoted[row["id"]] == row["url"]


def test_round_one_pack_2026_11_23_promotes_exactly_the_validated_feeds():
    with open("docs/research/source-candidates-2026-11-23-round1.json", encoding="utf-8") as handle:
        pack = json.load(handle)
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    # Validation run #8: active or quiet with English confirmed.
    validated = set("""engineer-s-codex,shrivu-shankar,transactional-alex-miller,circleci-blog,django-weblog,ee-times-asia,ruby-on-rails-blog,sans-internet-storm-center,sitepoint,influxdata-blog,singlestore-blog,duolingo-blog,metadata-murat-demirbas,o-reilly-radar,allegro-tech-blog,data-science-at-microsoft,all-things-distributed,coding-horror,myntra-engineering,strava-engineering,sean-goedecke,twilio-blog,drew-breunig,hellofresh-tech,ing-tech-blog,whatnot-engineering,daniel-lemire,techtrends-kenya,marc-brooker,monday-com-engineering,philipp-schmid,teads-engineering,the-hindu-businessline-info-tech,tech-world-with-milan,angular-blog,val-town-blog,wix-engineering,adevinta-tech-blog,answer-ai,asos-tech-blog,back-market-engineering,bbc-product-technology,bumble-tech,disney-streaming-technology,fasterthanli-me,guardian-engineering,joel-on-software,miro-engineering,olx-engineering,riskified-technology,square-developer-blog,squarespace-engineering,tokopedia-engineering,traveloka-engineering,trendforce-news,udemy-engineering,vue-js-blog""".split(","))
    assert len(validated) == 57
    for row in pack:
        assert (row["id"] in validated) == (row["id"] in promoted), row["id"]
        if row["id"] in promoted:
            assert promoted[row["id"]] == row["url"]


def test_round_two_pack_2026_11_24_promotes_exactly_the_validated_feeds():
    with open("docs/research/source-candidates-2026-11-24-round2.json", encoding="utf-8") as handle:
        pack = json.load(handle)
    promoted = {source.id: source.url for source in DEFAULT_SOURCES}
    # Validation run #9: active or quiet with English confirmed.
    validated = set("""crunchy-data-blog,release-coredns-coredns,release-lightning-ai-pytorch-lightning,release-longhorn-longhorn,release-redpanda-data-redpanda,databricks-blog,ettelecom,percona-blog,release-anchore-grype,release-anchore-syft,release-appwrite-appwrite,release-cloudflare-workerd,release-confident-ai-deepeval,release-dagster-io-dagster,release-elixir-lang-elixir,release-getsentry-sentry,release-grafana-mimir,release-honojs-hono,release-invoke-ai-invokeai,release-langchain-ai-langchainjs,release-meilisearch-meilisearch,release-open-policy-agent-opa,release-pingcap-tidb,release-rollup-rollup,release-semgrep-semgrep,release-sqlalchemy-sqlalchemy,release-strapi-strapi,release-sveltejs-kit,release-tikv-tikv,release-trufflesecurity-trufflehog,release-vitessio-vitess,release-webpack-webpack,release-zaproxy-zaproxy,xe-iaso,devclass,datadog-security-labs,drew-devault,jessie-frazelle,release-apache-doris,release-apache-hudi,release-apache-tvm,release-expressjs-express,release-hashicorp-packer,release-kedacore-keda,release-knative-serving,release-osquery-osquery,release-ossf-scorecard,release-questdb-questdb,the-information,itwire,release-bevyengine-bevy,release-celery-celery,release-crowdsecurity-crowdsec,release-gleam-lang-gleam,release-google-osv-scanner,release-huggingface-tokenizers,release-jestjs-jest,release-ml-explore-mlx-lm,release-onnx-onnx,release-payloadcms-payload,release-vercel-turborepo,release-goharbor-harbor,release-grafana-k6,release-kubernetes-sigs-cluster-api,release-kubernetes-sigs-karpenter,release-nextcloud-server,release-open-telemetry-opentelemetry-python,release-rancher-rancher,release-storybookjs-storybook,release-wazuh-wazuh,atlassian-engineering,eli-bendersky,release-huggingface-huggingface-hub,release-python-poetry-poetry,release-wandb-wandb,release-zenml-io-zenml,ken-shirriff,release-crossplane-crossplane,release-fastify-fastify,release-gohugoio-hugo,release-grafana-tempo,release-immich-app-immich,release-julialang-julia,release-mintplex-labs-anything-llm,release-prettier-prettier,release-risingwavelabs-risingwave,release-cockroachdb-cockroach,release-cypress-io-cypress,release-directus-directus,release-hoppscotch-hoppscotch,release-mattermost-mattermost,release-nodejs-node,release-nrwl-nx,release-prefecthq-prefect,release-timescale-timescaledb,release-authelia-authelia,release-pnpm-pnpm,release-keycloak-keycloak,release-pocketbase-pocketbase,release-surrealdb-surrealdb,release-swc-project-swc,release-tailscale-tailscale,bartosz-ciechanowski,brandur-leach,python-insider,release-airbytehq-airbyte,release-automatic1111-stable-diffusion-webui,release-calcom-cal-com,release-encode-httpx,release-evanw-esbuild,release-explodinggradients-ragas,release-facebook-react-native,release-gitleaks-gitleaks,release-godotengine-godot,release-helix-editor-helix,release-jetbrains-kotlin,release-kubernetes-ingress-nginx,release-lancedb-lancedb,release-lm-sys-fastchat,release-neondatabase-neon,release-oobabooga-text-generation-webui,release-ory-kratos,release-pallets-flask,release-prisma-prisma,release-psf-requests,release-typesense-typesense,russ-cox,soundcloud-backstage,the-korea-herald-tech,without-boats""".split(","))
    assert len(validated) == 130
    for row in pack:
        assert (row["id"] in validated) == (row["id"] in promoted), row["id"]
        if row["id"] in promoted:
            assert promoted[row["id"]] == row["url"]
