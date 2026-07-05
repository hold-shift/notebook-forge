"""SEO/AEO structured data (plan §4–§6): the pure JSON-LD @graph + head builders."""

import json

from notebook_forge.structured_data import (
    DocSeoContext,
    article_graph,
    article_jsonld_script,
    head_meta,
    iso_duration_from_minutes,
    iso_duration_from_seconds,
    iso_duration_from_words,
)

BASE = "https://history.skitch.me"
CANON = f"{BASE}/rfs/1934-1945_junior.html"


def _ctx(**over) -> DocSeoContext:
    base = dict(
        base_url=BASE,
        canonical_url=CANON,
        title="Junior",
        description="The boy I once knew.",
        author_name="R.F. Skitch",
        author_birth="1934",
        publisher_name="The Skitch Family Archive",
        site_title="Robert Francis Skitch",
        series_id=f"{BASE}/index.html#collection",
        series_name="Robert Francis Skitch",
        homepage_url=f"{BASE}/index.html",
        date_published="2026-06-09T00:00:00+00:00",
        date_modified="2026-07-05T00:00:00+00:00",
        section="Early life & service",
        word_count=31000,
        time_required="PT2H35M",
        image_url=f"{BASE}/rfs/1934-1945_junior_assets/figure-1-original.jpeg",
        places=["Collie, Western Australia", "Nui Dat"],
        people=["Robert Skitch", "Mavis Skitch"],
    )
    base.update(over)
    return DocSeoContext(**base)


# ------------------------------------------------------------- durations


def test_iso_duration_from_minutes() -> None:
    assert iso_duration_from_minutes(25) == "PT25M"
    assert iso_duration_from_minutes(185) == "PT3H5M"
    assert iso_duration_from_minutes(120) == "PT2H"
    assert iso_duration_from_minutes(0) == ""


def test_iso_duration_from_words() -> None:
    assert iso_duration_from_words(5000) == "PT25M"  # 200 wpm
    assert iso_duration_from_words(0) == ""


def test_iso_duration_from_seconds() -> None:
    assert iso_duration_from_seconds(11104) == "PT3H5M4S"
    assert iso_duration_from_seconds(3600) == "PT1H"
    assert iso_duration_from_seconds(None) == ""
    assert iso_duration_from_seconds(0) == ""


# ------------------------------------------------------------- @graph


def test_graph_shares_entities_by_id() -> None:
    graph = article_graph(_ctx())["@graph"]
    types = [n["@type"] for n in graph]
    assert types == ["Person", "Organization", "CreativeWorkSeries", "Article", "BreadcrumbList"]

    person = next(n for n in graph if n["@type"] == "Person")
    org = next(n for n in graph if n["@type"] == "Organization")
    article = next(n for n in graph if n["@type"] == "Article")

    assert person["@id"] == f"{BASE}/index.html#author"
    assert person["birthDate"] == "1934"
    assert org["@id"] == f"{BASE}/index.html#publisher"
    # Article references the shared entities by @id (de-duplication).
    assert article["author"] == {"@id": person["@id"]}
    assert article["publisher"] == {"@id": org["@id"]}
    assert article["isPartOf"] == {"@id": f"{BASE}/index.html#collection"}


def test_article_fields() -> None:
    article = next(
        n for n in article_graph(_ctx())["@graph"] if n["@type"] == "Article"
    )
    assert article["inLanguage"] == "en-AU"
    assert article["datePublished"] == "2026-06-09T00:00:00+00:00"
    assert article["dateModified"] == "2026-07-05T00:00:00+00:00"
    assert article["articleSection"] == "Early life & service"
    assert article["wordCount"] == 31000
    assert article["timeRequired"] == "PT2H35M"
    assert article["image"].endswith("figure-1-original.jpeg")
    assert article["speakable"]["@type"] == "SpeakableSpecification"
    # about = Place (geo), mentions = Person (people)
    assert {"@type": "Place", "name": "Nui Dat"} in article["about"]
    assert {"@type": "Person", "name": "Mavis Skitch"} in article["mentions"]


def test_breadcrumb_positions() -> None:
    crumbs = next(
        n for n in article_graph(_ctx())["@graph"] if n["@type"] == "BreadcrumbList"
    )["itemListElement"]
    assert [c["position"] for c in crumbs] == [1, 2, 3]
    assert crumbs[0]["item"] == f"{BASE}/index.html"
    assert crumbs[1]["name"] == "Early life & service"
    assert crumbs[-1]["item"] == CANON


def test_no_audio_object_without_audio() -> None:
    article = next(
        n for n in article_graph(_ctx())["@graph"] if n["@type"] == "Article"
    )
    assert "audio" not in article
    assert "potentialAction" not in article
    assert "accessibilityFeature" not in article


def test_audio_object_and_accessibility() -> None:
    ctx = _ctx(
        audio_url=f"{BASE}/audio/junior/document.mp3", audio_duration="PT3H5M"
    )
    article = next(
        n for n in article_graph(ctx)["@graph"] if n["@type"] == "Article"
    )
    audio = article["audio"]
    assert audio["@type"] == "AudioObject"
    assert audio["contentUrl"].endswith("/document.mp3")
    assert audio["encodingFormat"] == "audio/mpeg"
    assert audio["duration"] == "PT3H5M"
    assert article["accessibilityFeature"] == ["synchronizedAudioText", "readingOrder"]
    assert article["potentialAction"]["@type"] == "ListenAction"
    assert article["potentialAction"]["target"] == f"{CANON}#ttsPlayer"


def test_jsonld_script_is_valid_json() -> None:
    script = article_jsonld_script(_ctx())
    assert script.startswith('<script type="application/ld+json">')
    inner = script[len('<script type="application/ld+json">') : -len("</script>")]
    # The </ escape keeps the script un-terminatable inside HTML; undo it to parse.
    parsed = json.loads(inner.replace("<\\/", "</"))
    assert parsed["@context"] == "https://schema.org"
    assert isinstance(parsed["@graph"], list)


# ------------------------------------------------------------- head meta


def test_head_meta_fields() -> None:
    head = head_meta(_ctx(twitter_site="@skitch"))
    assert head["lang"] == "en-AU"
    assert head["locale"] == "en_AU"
    assert "max-image-preview:large" in head["robots"]
    assert head["site_name"] == "Robert Francis Skitch"
    assert head["author"] == "R.F. Skitch"
    assert head["article_section"] == "Early life & service"
    assert head["twitter_site"] == "@skitch"
    # tags drawn from places + people, de-duplicated & capped
    assert "Nui Dat" in head["article_tags"]


def test_head_meta_audio_present_only_with_audio() -> None:
    assert head_meta(_ctx())["audio_url"] == ""
    assert head_meta(_ctx(audio_url="x/document.mp3"))["audio_url"] == "x/document.mp3"
