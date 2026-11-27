import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from django.test import TestCase, override_settings
from django.conf import settings
from django.test import TestCase
from urllib.robotparser import RobotFileParser
from html.parser import HTMLParser
import re
from django.contrib.staticfiles import finders
from .content import PAGES
import json
from . import schema
from .content import PAGES, PAGES_BY_SLUG, RELATED, REDIRECTS
import io
import shutil
import tempfile
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import Context, Template
from django.test import override_settings
from PIL import Image
import gzip
from django.test import Client
from .middleware import KNOWN_PATHS
import os
from pathlib import Path
from django.conf import settings
from .models import HubHeartbeat, PublicAlert, PublicAnnouncement, ZoneStatus
from datetime import timedelta
from django.utils import timezone


NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SitemapTests(TestCase):
    def setUp(self):
        self.response = self.client.get("/sitemap.xml")
        self.root = ET.fromstring(self.response.content)
        self.locs = [e.text for e in self.root.findall("sm:url/sm:loc", NS)]

    def test_ok_and_xml(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertIn("xml", self.response["Content-Type"])

    def test_all_pages_listed_once(self):
        self.assertEqual(len(self.locs), len(PAGES) + 1)
        self.assertEqual(len(set(self.locs)), len(self.locs))

    def test_urls_are_absolute_from_site_url(self):
        for loc in self.locs:
            self.assertTrue(loc.startswith(settings.SITE_URL + "/"), loc)

    def test_every_listed_url_returns_200(self):
        for loc in self.locs:
            self.assertEqual(self.client.get(urlparse(loc).path).status_code, 200, loc)

    def test_no_ignored_tags(self):
        self.assertNotIn(b"priority", self.response.content)
        self.assertNotIn(b"changefreq", self.response.content)

    def test_lastmod_is_iso_date(self):
        for e in self.root.findall("sm:url/sm:lastmod", NS):
            self.assertRegex(e.text, r"^\d{4}-\d{2}-\d{2}$")

class RobotsTests(TestCase):
    def setUp(self):
        self.response = self.client.get("/robots.txt")
        self.text = self.response.content.decode()
        self.parser = RobotFileParser()
        self.parser.parse(self.text.splitlines())

    def test_ok_and_plain_text(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertIn("text/plain", self.response["Content-Type"])

    def test_public_pages_allowed_admin_blocked(self):
        base = settings.SITE_URL
        self.assertTrue(self.parser.can_fetch("*", f"{base}/"))
        for page in PAGES:
            self.assertTrue(self.parser.can_fetch("*", f"{base}/{page['slug']}/"), page["slug"])
        self.assertTrue(self.parser.can_fetch("*", f"{base}/admin/"))

    def test_no_blanket_block_and_no_noindex(self):
        self.assertNotIn("Disallow: /\n", self.text)
        self.assertNotIn("noindex", self.text.lower())
        self.assertNotIn("crawl-delay", self.text.lower())

    def test_sitemap_line_is_absolute_and_works(self):
        sitemaps = self.parser.site_maps()
        self.assertEqual(sitemaps, [f"{settings.SITE_URL}/sitemap.xml"])
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 200)

    def test_sitemap_has_no_blocked_urls(self):
        sitemap = self.client.get("/sitemap.xml").content.decode()
        self.assertNotIn("/admin/", sitemap)

class IndexingTests(TestCase):
    @override_settings(ALLOW_INDEXING=False)
    def test_noindex_everywhere_when_off(self):
        for path in ["/", "/faq/", "/missing-page/", "/admin/login/"]:
            response = self.client.get(path)
            self.assertEqual(response["X-Robots-Tag"], "noindex", path)

    @override_settings(ALLOW_INDEXING=True)
    def test_public_pages_indexable_when_on(self):
        for path in ["/", "/faq/", "/contact/"]:
            self.assertNotIn("X-Robots-Tag", self.client.get(path), path)

    @override_settings(ALLOW_INDEXING=True)
    def test_admin_always_noindex(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Robots-Tag"], "noindex")

    def test_robots_does_not_block_admin(self):
        text = self.client.get("/robots.txt").content.decode()
        self.assertNotIn("Disallow", text)

class _CanonicalParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        elif tag == "link":
            a = dict(attrs)
            if a.get("rel") == "canonical":
                self.found.append((self.in_head, a.get("href")))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def _canonicals(html):
    parser = _CanonicalParser()
    parser.feed(html)
    return parser.found


class CanonicalTests(TestCase):
    def setUp(self):
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]

    def test_one_absolute_self_canonical_in_head(self):
        for path in self.paths:
            found = _canonicals(self.client.get(path).content.decode())
            self.assertEqual(found, [(True, settings.SITE_URL + path)], path)

    def test_query_string_is_dropped(self):
        html = self.client.get("/faq/?utm_source=x&ref=y").content.decode()
        self.assertEqual(_canonicals(html), [(True, f"{settings.SITE_URL}/faq/")])

    def test_canonicals_match_sitemap(self):
        root = ET.fromstring(self.client.get("/sitemap.xml").content)
        locs = {e.text for e in root.findall("sm:url/sm:loc", NS)}
        self.assertEqual(locs, {settings.SITE_URL + p for p in self.paths})

class _HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.titles = []
        self.descriptions = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        elif tag == "title" and self.in_head:
            self.in_title = True
            self.titles.append("")
        elif tag == "meta" and self.in_head and a.get("name") == "description":
            self.descriptions.append(a.get("content") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "head":
            self.in_head = False

    def handle_data(self, data):
        if self.in_title:
            self.titles[-1] += data


class MetadataTests(TestCase):
    def setUp(self):
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]
        self.heads = {}
        for path in self.paths:
            parser = _HeadParser()
            parser.feed(self.client.get(path).content.decode())
            self.heads[path] = parser

    def test_exactly_one_title_and_description(self):
        for path, head in self.heads.items():
            self.assertEqual(len(head.titles), 1, path)
            self.assertEqual(len(head.descriptions), 1, path)

    def test_title_quality(self):
        for path, head in self.heads.items():
            title = head.titles[0].strip()
            self.assertTrue(15 <= len(title) <= 65, (path, len(title)))
            self.assertEqual(title.count(settings.SITE_NAME), 1, (path, title))
            self.assertNotEqual(title.lower(), "home")

    def test_description_quality(self):
        for path, head in self.heads.items():
            desc = head.descriptions[0].strip()
            self.assertTrue(50 <= len(desc) <= 160, (path, len(desc)))
            self.assertNotEqual(desc, head.titles[0].strip(), path)

    def test_titles_and_descriptions_are_unique(self):
        titles = [h.titles[0].strip() for h in self.heads.values()]
        descs = [h.descriptions[0].strip() for h in self.heads.values()]
        self.assertEqual(len(set(titles)), len(titles))
        self.assertEqual(len(set(descs)), len(descs))

class _HeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_main = False
        self.main_count = 0
        self.current = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.main_count += 1
            self.in_main = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.current = [int(tag[1]), "", self.in_main]

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        elif self.current and tag == f"h{self.current[0]}":
            self.headings.append(tuple(self.current))
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data


class HeadingTests(TestCase):
    def setUp(self):
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]
        self.parsed = {}
        for path in self.paths:
            parser = _HeadingParser()
            parser.feed(self.client.get(path).content.decode())
            self.parsed[path] = parser

    def test_single_main_and_single_h1_inside_it(self):
        for path, p in self.parsed.items():
            self.assertEqual(p.main_count, 1, path)
            h1s = [h for h in p.headings if h[0] == 1]
            self.assertEqual(len(h1s), 1, path)
            self.assertTrue(h1s[0][2], f"h1 outside main: {path}")

    def test_h1_is_descriptive(self):
        for path, p in self.parsed.items():
            text = next(h[1] for h in p.headings if h[0] == 1).strip()
            self.assertTrue(text, path)
            self.assertNotEqual(text.lower(), settings.SITE_NAME.lower(), path)

    def test_no_skipped_heading_levels(self):
        for path, p in self.parsed.items():
            levels = [h[0] for h in p.headings]
            self.assertEqual(levels[0], 1, path)
            for prev, nxt in zip(levels, levels[1:]):
                self.assertLessEqual(nxt, prev + 1, (path, levels))

    def test_h1_unique_per_page(self):
        texts = [next(h[1] for h in p.headings if h[0] == 1).strip() for p in self.parsed.values()]
        self.assertEqual(len(set(texts)), len(texts))

class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.in_link = False
        self.link_text = ""
        self.link_imgs = []
        self.bad_links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self.in_link, self.link_text, self.link_imgs = True, "", []
        elif tag == "img":
            self.images.append(a)
            if self.in_link:
                self.link_imgs.append(a)

    def handle_data(self, data):
        if self.in_link:
            self.link_text += data

    def handle_endtag(self, tag):
        if tag == "a":
            has_alt = any((i.get("alt") or "").strip() for i in self.link_imgs)
            if self.link_imgs and not self.link_text.strip() and not has_alt:
                self.bad_links.append(self.link_imgs)
            self.in_link = False


class ImageTests(TestCase):
    GENERIC_ALTS = {"image", "photo", "picture", "img", "logo", "graphic"}

    def setUp(self):
        self.parsed = {}
        for path in ["/"] + [f"/{p['slug']}/" for p in PAGES]:
            parser = _ImageParser()
            parser.feed(self.client.get(path).content.decode())
            self.parsed[path] = parser

    def _all_images(self):
        for path, parser in self.parsed.items():
            for img in parser.images:
                yield path, img

    def test_every_img_has_alt_attribute(self):
        for path, img in self._all_images():
            self.assertIn("alt", img, (path, img.get("src")))

    def test_every_img_has_dimensions(self):
        for path, img in self._all_images():
            self.assertTrue(img.get("width") and img.get("height"), (path, img.get("src")))

    def test_alt_text_quality(self):
        for path, img in self._all_images():
            alt = (img.get("alt") or "").strip()
            if not alt:
                continue
            low = alt.lower()
            self.assertLessEqual(len(alt), 125, (path, alt))
            self.assertNotIn(low, self.GENERIC_ALTS, (path, alt))
            self.assertFalse(low.startswith(("image of", "picture of", "photo of")), (path, alt))
            self.assertFalse(re.search(r"\.(jpe?g|png|svg|webp|gif)$", low), (path, alt))
            self.assertLessEqual(alt.count(","), 3, (path, alt))

    def test_image_only_links_have_text(self):
        for path, parser in self.parsed.items():
            self.assertEqual(parser.bad_links, [], path)

    def test_images_exist_and_filenames_are_descriptive(self):
        for path, img in self._all_images():
            src = img["src"]
            self.assertTrue(src.startswith("/static/"), src)
            self.assertIsNotNone(finders.find(src.removeprefix("/static/")), src)
            name = src.rsplit("/", 1)[-1].lower()
            self.assertIsNone(re.match(r"^(img|image|pic|photo|dsc)[-_]?\d*\.", name), name)

class _LdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.text = []
        self._ld = False
        self._skip = False
        self._body = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self._body = True
        elif tag == "script":
            if a.get("type") == "application/ld+json":
                self._ld = True
                self.blocks.append("")
            else:
                self._skip = True
        elif tag == "style":
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
            self._skip = False
        elif tag == "style":
            self._skip = False

    def handle_data(self, data):
        if self._ld:
            self.blocks[-1] += data
        elif self._body and not self._skip:
            self.text.append(data)


def _ld(path, client):
    parser = _LdParser()
    parser.feed(client.get(path).content.decode())
    return parser


class StructuredDataTests(TestCase):
    def test_home_has_one_valid_block_with_expected_types(self):
        parser = _ld("/", self.client)
        self.assertEqual(len(parser.blocks), 1)
        data = json.loads(parser.blocks[0])
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual({n["@type"] for n in data["@graph"]}, {"Organization", "WebSite"})

    def test_other_pages_have_no_structured_data(self):
        for p in PAGES:
            self.assertEqual(_ld(f"/{p['slug']}/", self.client).blocks, [], p["slug"])

    def test_values_match_visible_text(self):
        parser = _ld("/", self.client)
        visible = " ".join(parser.text)
        org = next(n for n in json.loads(parser.blocks[0])["@graph"] if n["@type"] == "Organization")
        for key in ("name", "description", "email"):
            self.assertIn(org[key], visible, key)

    def test_urls_and_ids_are_consistent(self):
        parser = _ld("/", self.client)
        graph = json.loads(parser.blocks[0])["@graph"]
        ids = [n["@id"] for n in graph]
        self.assertEqual(len(set(ids)), len(ids))
        for node in graph:
            self.assertEqual(node["url"], settings.SITE_URL + "/")
            self.assertTrue(node["@id"].startswith(settings.SITE_URL + "/#"))

    def test_no_unsupported_claims(self):
        block = _ld("/", self.client).blocks[0]
        for key in ("aggregateRating", "review", "offers", "SoftwareApplication"):
            self.assertNotIn(key, block)

    def test_escaping_is_single_pass_and_safe(self):
        original = {"a": "</script><b>R&D"}
        text = schema.dumps(original)
        for char in "<>&":
            self.assertNotIn(char, text)
        self.assertEqual(json.loads(text), original)

GENERIC_ANCHORS = {"click here", "read more", "learn more", "here", "more", "link", "this page", "website", "article"}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.in_main = False
        self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "main":
            self.in_main = True
        elif tag == "a":
            self._cur = {"href": a.get("href"), "text": "", "in_main": self.in_main}
        elif tag == "img" and self._cur is not None:
            self._cur["text"] += " " + (a.get("alt") or "")

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        elif tag == "a" and self._cur is not None:
            self._cur["text"] = " ".join(self._cur["text"].split())
            self.links.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data


def _internal_path(href):
    href = href or ""
    if href.startswith(settings.SITE_URL):
        href = href[len(settings.SITE_URL):]
    if href.startswith("/") and not href.startswith("//"):
        return href.split("#")[0]
    return None


def _crawl(client):
    seen, queue, pages = set(), ["/"], {}
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        response = client.get(path)
        parser = _LinkParser()
        parser.feed(response.content.decode())
        pages[path] = (response.status_code, parser)
        for link in parser.links:
            target = _internal_path(link["href"])
            if target and not target.startswith("/admin/"):
                queue.append(target)
    return pages


class LinkTests(TestCase):
    def setUp(self):
        self.pages = _crawl(self.client)

    def test_every_crawled_page_returns_200(self):
        for path, (status, _) in self.pages.items():
            self.assertEqual(status, 200, path)

    def test_no_orphans_and_crawl_matches_sitemap(self):
        root = ET.fromstring(self.client.get("/sitemap.xml").content)
        sitemap = {urlparse(e.text).path for e in root.findall("sm:url/sm:loc", NS)}
        self.assertEqual(set(self.pages), sitemap)

    def test_hrefs_are_clean_crawlable_and_canonical(self):
        for path, (_, parser) in self.pages.items():
            for link in parser.links:
                href = link["href"]
                self.assertTrue(href, (path, link))
                if href.startswith("#"):
                    self.assertIn(href[1:], parser.ids, (path, href))
                    continue
                self.assertTrue(href.startswith(("/", "mailto:", "tel:", "https://")), (path, href))
                if href.startswith("/"):
                    self.assertNotIn("?", href, (path, href))
                    last = href.rstrip("/").rsplit("/", 1)[-1]
                    self.assertTrue(href.endswith("/") or "." in last, (path, href))

    def test_anchor_text_is_present_and_descriptive(self):
        for path, (_, parser) in self.pages.items():
            for link in parser.links:
                text = link["text"]
                self.assertTrue(text, (path, link["href"]))
                self.assertNotIn(text.lower().strip(" .!"), GENERIC_ANCHORS, (path, text))
                self.assertLessEqual(len(text), 100, (path, text))

    def test_every_page_has_contextual_internal_links(self):
        for page in PAGES:
            parser = self.pages[f"/{page['slug']}/"][1]
            in_main = [l for l in parser.links if l["in_main"] and l["href"].startswith("/")]
            self.assertTrue(in_main, page["slug"])

    def test_related_slugs_are_valid(self):
        for slug, related in RELATED.items():
            self.assertIn(slug, PAGES_BY_SLUG)
            self.assertEqual(len(set(related)), len(related), slug)
            for other in related:
                self.assertIn(other, PAGES_BY_SLUG)
                self.assertNotEqual(other, slug)

    def test_404_is_real_helpful_and_has_no_canonical(self):
        response = self.client.get("/no-such-page/")
        html = response.content.decode()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(_canonicals(html), [])
        parser = _LinkParser()
        parser.feed(html)
        hrefs = {l["href"] for l in parser.links}
        self.assertIn("/", hrefs)
        self.assertGreaterEqual(len([h for h in hrefs if h.startswith("/")]), 5)

class ImageOptimizationTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src, self.out = self.tmp / "src", self.tmp / "out"
        self.src.mkdir()
        Image.new("RGB", (1600, 900), (10, 100, 200)).save(self.src / "Kauswagan River.jpg")
        Image.new("RGB", (300, 200), (200, 10, 10)).save(self.src / "small-photo.png")
        call_command("optimize_images", source=str(self.src), output=str(self.out), stdout=io.StringIO())
        self.manifest = json.loads((self.out / "manifest.json").read_text())

    def _render(self, tag):
        with override_settings(OPTIMIZED_IMAGE_DIR=self.out):
            return Template("{% load images %}" + tag).render(Context())

    def test_widths_never_upscale(self):
        widths = lambda n: [v["width"] for v in self.manifest[n]["variants"]]
        self.assertEqual(widths("kauswagan-river"), [480, 800, 1200, 1600])
        self.assertEqual(widths("small-photo"), [300])

    def test_files_are_webp_with_correct_size(self):
        for entry in self.manifest.values():
            for v in entry["variants"]:
                with Image.open(self.out / v["file"].rsplit("/", 1)[-1]) as im:
                    self.assertEqual(im.format, "WEBP")
                    self.assertEqual(im.size, (v["width"], v["height"]))
        first = self.manifest["kauswagan-river"]["variants"][0]
        self.assertEqual((first["width"], first["height"]), (480, 270))

    def test_meaningless_filenames_are_rejected(self):
        Image.new("RGB", (100, 100)).save(self.src / "IMG_0023.jpg")
        with self.assertRaises(CommandError):
            call_command("optimize_images", source=str(self.src), output=str(self.out), stdout=io.StringIO())

    def test_lazy_tag_output(self):
        html = self._render("{% responsive_image 'kauswagan-river' 'Sensor <1> by the river' '100vw' %}")
        for part in ('loading="lazy"', 'decoding="async"', 'srcset="', 'sizes="100vw"',
                     'width="', 'height="', "Sensor &lt;1&gt; by the river"):
            self.assertIn(part, html)
        self.assertNotIn("fetchpriority", html)

    def test_eager_tag_output(self):
        html = self._render("{% responsive_image 'kauswagan-river' 'River' '100vw' True 'hero' %}")
        self.assertIn('fetchpriority="high"', html)
        self.assertNotIn("loading=", html)
        self.assertIn('class="hero"', html)

    def test_unknown_image_fails_loudly(self):
        with self.assertRaises(ValueError):
            self._render("{% responsive_image 'nope' '' '100vw' %}")


class ImagePolicyTests(TestCase):
    def setUp(self):
        self.pages = {}
        for path in ["/"] + [f"/{p['slug']}/" for p in PAGES]:
            parser = _ImageParser()
            parser.feed(self.client.get(path).content.decode())
            self.pages[path] = parser.images

    def test_raster_images_are_webp(self):
        for path, images in self.pages.items():
            for img in images:
                self.assertTrue(img["src"].endswith((".svg", ".webp")), (path, img["src"]))

    def test_srcset_always_has_sizes(self):
        for path, images in self.pages.items():
            for img in images:
                if img.get("srcset"):
                    self.assertTrue(img.get("sizes"), (path, img["src"]))

    def test_lcp_image_is_never_lazy(self):
        for path, images in self.pages.items():
            high = [i for i in images if i.get("fetchpriority") == "high"]
            self.assertLessEqual(len(high), 1, path)
            for img in images:
                self.assertFalse(img.get("loading") == "lazy" and img.get("fetchpriority") == "high")
        hero = next(i for i in self.pages["/"] if "hero" in (i.get("class") or ""))
        self.assertNotEqual(hero.get("loading"), "lazy")
        self.assertEqual(hero.get("fetchpriority"), "high")

class _ResourceParser(HTMLParser):
    RESOURCE_TAGS = {"script", "img", "link", "iframe", "source", "video", "audio"}

    def __init__(self):
        super().__init__()
        self.in_head = False
        self.scripts = []
        self.stylesheets = []
        self.external = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        if tag == "script" and a.get("src"):
            self.scripts.append(a)
        if tag == "link" and a.get("rel") == "stylesheet":
            self.stylesheets.append((a.get("href"), self.in_head))
        if tag in self.RESOURCE_TAGS and a.get("rel") not in ("canonical", "alternate"):
            for key in ("src", "href", "srcset"):
                url = a.get(key) or ""
                if url.startswith(("http://", "https://", "//")) and not url.startswith(settings.SITE_URL):
                    self.external.append((tag, url))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


class PerformanceBudgetTests(TestCase):
    HTML_LIMIT = 60_000
    CSS_LIMIT = 40_000

    def setUp(self):
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]
        self.resources = {}
        self.sizes = {}
        for path in self.paths:
            response = self.client.get(path)
            self.sizes[path] = len(response.content)
            parser = _ResourceParser()
            parser.feed(response.content.decode())
            self.resources[path] = parser

    def test_html_is_small(self):
        for path, size in self.sizes.items():
            self.assertLessEqual(size, self.HTML_LIMIT, (path, size))

    def test_css_budget_and_hygiene(self):
        css_path = Path(settings.BASE_DIR) / "static" / "css" / "site.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertLessEqual(len(css.encode()), self.CSS_LIMIT)
        self.assertNotIn("@import", css)
        self.assertNotIn("url(http", css)
        self.assertNotIn("url(//", css)
        if "@font-face" in css:
            self.assertIn("font-display", css)

    def test_scripts_never_block_rendering(self):
        for path, parser in self.resources.items():
            for script in parser.scripts:
                ok = "defer" in script or "async" in script or script.get("type") == "module"
                self.assertTrue(ok, (path, script))

    def test_few_stylesheets_all_in_head(self):
        for path, parser in self.resources.items():
            self.assertLessEqual(len(parser.stylesheets), 2, path)
            for href, in_head in parser.stylesheets:
                self.assertTrue(in_head, (path, href))

    def test_no_third_party_requests(self):
        for path, parser in self.resources.items():
            self.assertEqual(parser.external, [], path)

    def test_html_is_gzip_compressed(self):
        response = self.client.get("/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", response["Vary"])
        self.assertIn(b"<h1", gzip.decompress(response.content))

def _css_rules(css):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


class MobileLayoutTests(TestCase):
    def setUp(self):
        self.css = (Path(settings.BASE_DIR) / "static" / "css" / "site.css").read_text(encoding="utf-8")
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]

    def test_every_page_has_a_zoomable_viewport_and_language(self):
        for path in self.paths:
            html = self.client.get(path).content.decode()
            match = re.search(r'<meta name="viewport" content="([^"]*)"', html)
            self.assertIsNotNone(match, path)
            content = match.group(1)
            self.assertIn("width=device-width", content)
            self.assertIn("initial-scale=1", content)
            self.assertNotIn("user-scalable", content)
            self.assertNotIn("maximum-scale", content)
            self.assertIn('<html lang="en">', html)

    def test_navigation_tap_targets_are_at_least_44px(self):
        heights = []
        for selector, body in _css_rules(self.css):
            if "nav a" in selector or ".brand" in selector:
                for value in re.findall(r"min-height:\s*([\d.]+)rem", body):
                    heights.append(float(value))
        self.assertTrue(heights and max(heights) >= 2.75, heights)

    def test_text_is_never_tiny(self):
        for value, unit in re.findall(r"font-size:\s*([\d.]+)(rem|em|px)", self.css):
            size = float(value) * (1 if unit == "px" else 16)
            self.assertGreaterEqual(size, 14, f"{value}{unit}")

    def test_css_hides_nothing_except_the_menu(self):
            
        css = (Path(settings.BASE_DIR) / "static" / "css" / "site.css").read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            compact = re.sub(r"\s+", "", body)
            if "display:none" in compact or "visibility:hidden" in compact:
                self.assertTrue("menu-" in selector or ".site-nav" in selector, selector.strip())
        for path in ["/", "/water-levels/", "/contact/"]:
            html = self.client.get(path).content.decode()
            self.assertIsNone(re.search(r"<[^>]+\shidden[\s>]", html), path)

    def test_collapsible_menu_is_wired_up_and_keeps_every_link(self):
        paths = ["/", "/water-levels/", "/alerts-events/", "/announcements/",
                 "/flood-map/", "/safety-guide/", "/contact/"]
        for path in paths:
            html = self.client.get(path).content.decode()
            self.assertIn('<input type="checkbox" id="menu-toggle" class="menu-toggle">', html)
            self.assertIn('<label class="menu-button" for="menu-toggle">', html)
            nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
            self.assertEqual(len(re.findall(r"<a href=", nav)), 5, path)

    def test_no_wide_fixed_widths(self):
        for prop, value in re.findall(r"(?<![-\w])((?:min-)?width):\s*(\d+)px", self.css):
            self.assertLessEqual(int(value), 320, f"{prop}: {value}px")

class SecurityTests(TestCase):
    def test_django_default_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertIn("geolocation=()", response["Permissions-Policy"])

    def test_csp_is_strict_on_public_pages_only(self):
        csp = self.client.get("/").headers["Content-Security-Policy"]
        for directive in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'"):
            self.assertIn(directive, csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("Content-Security-Policy", self.client.get("/admin/login/"))

    def test_pages_are_compatible_with_the_csp(self):
        for path in ["/"] + [f"/{p['slug']}/" for p in PAGES]:
            html = self.client.get(path).content.decode()
            self.assertIsNone(re.search(r"<style[\s>]", html), path)
            self.assertIsNone(re.search(r"\sstyle=", html), path)
            self.assertIsNone(re.search(r"\son[a-z]+=", html), path)
            for tag in re.findall(r"<script\b[^>]*>", html):
                self.assertTrue("application/ld+json" in tag or "src=" in tag, (path, tag))

    def test_public_pages_set_no_cookies(self):
        for path in ["/", "/faq/", "/contact/"]:
            self.assertEqual(len(self.client.get(path).cookies), 0, path)

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_https_redirect_proxy_header_and_health_exemption(self):
        with override_settings(
            SECURE_SSL_REDIRECT=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            SECURE_REDIRECT_EXEMPT=[r"^health/$"],
        ):
            plain = Client().get("/faq/")
            self.assertEqual(plain.status_code, 301)
            self.assertTrue(plain["Location"].startswith("https://"))
            proxied = Client().get("/faq/", HTTP_X_FORWARDED_PROTO="https")
            self.assertEqual(proxied.status_code, 200)
            self.assertEqual(Client().get("/health/").status_code, 200)

    def test_hsts_only_on_secure_requests(self):
        with override_settings(SECURE_HSTS_SECONDS=3600):
            secure = Client().get("/", secure=True)
            self.assertEqual(secure["Strict-Transport-Security"], "max-age=3600")
            self.assertNotIn("Strict-Transport-Security", Client().get("/"))

class SecurityTests(TestCase):
    def test_django_default_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertIn("geolocation=()", response["Permissions-Policy"])

    def test_csp_is_strict_on_public_pages_only(self):
        csp = self.client.get("/").headers["Content-Security-Policy"]
        for directive in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'"):
            self.assertIn(directive, csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("Content-Security-Policy", self.client.get("/admin/login/"))

    def test_pages_are_compatible_with_the_csp(self):
        for path in ["/"] + [f"/{p['slug']}/" for p in PAGES]:
            html = self.client.get(path).content.decode()
            self.assertIsNone(re.search(r"<style[\s>]", html), path)
            self.assertIsNone(re.search(r"\sstyle=", html), path)
            self.assertIsNone(re.search(r"\son[a-z]+=", html), path)
            for tag in re.findall(r"<script\b[^>]*>", html):
                self.assertTrue("application/ld+json" in tag or "src=" in tag, (path, tag))

    def test_public_pages_set_no_cookies(self):
        for path in ["/", "/faq/", "/contact/"]:
            self.assertEqual(len(self.client.get(path).cookies), 0, path)

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_https_redirect_proxy_header_and_health_exemption(self):
        with override_settings(
            SECURE_SSL_REDIRECT=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            SECURE_REDIRECT_EXEMPT=[r"^health/$"],
        ):
            plain = Client().get("/faq/")
            self.assertEqual(plain.status_code, 301)
            self.assertTrue(plain["Location"].startswith("https://"))
            proxied = Client().get("/faq/", HTTP_X_FORWARDED_PROTO="https")
            self.assertEqual(proxied.status_code, 200)
            self.assertEqual(Client().get("/health/").status_code, 200)

    def test_hsts_only_on_secure_requests(self):
        with override_settings(SECURE_HSTS_SECONDS=3600):
            secure = Client().get("/", secure=True)
            self.assertEqual(secure["Strict-Transport-Security"], "max-age=3600")
            self.assertNotIn("Strict-Transport-Security", Client().get("/"))

class FontTests(TestCase):
    def setUp(self):
        self.static = Path(settings.BASE_DIR) / "static"
        self.css = (self.static / "css" / "site.css").read_text(encoding="utf-8")

    def test_font_files_are_real_woff2_and_small(self):
        files = list((self.static / "fonts").glob("*.woff2"))
        self.assertTrue(files)
        for f in files:
            data = f.read_bytes()
            self.assertEqual(data[:4], b"wOF2", f.name)
            self.assertLess(len(data), 120_000, f.name)

    def test_license_notice_ships_with_the_fonts(self):
        notice = (self.static / "fonts" / "atkinson-NOTICE.txt").read_text(encoding="utf-8", errors="ignore")
        self.assertIn("SIL OPEN FONT LICENSE", notice.upper())

    def test_font_face_rules(self):
        faces = re.findall(r"@font-face\s*\{([^}]*)\}", self.css)
        self.assertTrue(faces)
        for face in faces:
            self.assertIn("font-display: swap", face)
            self.assertIn('format("woff2")', face)

    def test_css_urls_exist_and_none_are_external(self):
        css_dir = self.static / "css"
        for url in re.findall(r"url\(\s*[\"']?([^)\"']+)[\"']?\s*\)", self.css):
            self.assertFalse(url.startswith(("http", "//")), url)
            self.assertTrue((css_dir / url).resolve().exists(), url)

    def test_body_font_stack_has_a_fallback(self):
        stacks = [b for s, b in _css_rules(self.css) if s == "body" and "font-family" in b]
        self.assertTrue(stacks)
        self.assertIn("sans-serif", stacks[-1])

    def test_exactly_one_font_preload_per_page(self):
        for path in ["/", "/faq/", "/contact/"]:
            html = self.client.get(path).content.decode()
            tags = re.findall(r'<link[^>]*rel="preload"[^>]*>', html)
            self.assertEqual(len(tags), 1, path)
            for part in ('as="font"', 'type="font/woff2"', "crossorigin"):
                self.assertIn(part, tags[0])
            href = re.search(r'href="([^"]+)"', tags[0]).group(1)
            self.assertIsNotNone(finders.find(href.removeprefix("/static/")), href)

class RedirectTests(TestCase):
    def test_slugs_are_clean(self):
        for page in PAGES:
            slug = page["slug"]
            self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$", slug)
            self.assertLessEqual(len(slug), 30, slug)
            self.assertLessEqual(slug.count("-"), 3, slug)

    def test_case_and_slash_variants_redirect_in_one_hop(self):
        for variant in ["/faq", "/FAQ", "/Faq/", "/FAQ/"]:
            response = self.client.get(variant)
            self.assertEqual(response.status_code, 301, variant)
            self.assertEqual(response["Location"], "/faq/", variant)
        self.assertEqual(self.client.get("/faq/").status_code, 200)

    def test_query_string_is_preserved(self):
        response = self.client.get("/FAQ?utm_source=x")
        self.assertEqual(response["Location"], "/faq/?utm_source=x")

    def test_legacy_aliases_redirect_to_real_pages(self):
        expected = {"/index.html": "/", "/home": "/", "/map": "/flood-map/", "/Alerts/": "/alerts-events/"}
        for old, new in expected.items():
            response = self.client.get(old)
            self.assertEqual((response.status_code, response["Location"]), (301, new), old)

    def test_redirect_map_has_no_chains_loops_or_dead_targets(self):
        for source, target in REDIRECTS.items():
            self.assertEqual(source, source.lower(), source)
            self.assertIn(target, KNOWN_PATHS, source)
            self.assertNotIn(source, KNOWN_PATHS, source)
            self.assertNotIn(target, REDIRECTS, source)

    def test_unknown_paths_get_a_404_not_a_redirect(self):
        for path in ["/nope", "/Nope/", "/nope/"]:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_post_is_never_redirected(self):
        self.assertNotEqual(self.client.post("/faq").status_code, 301)

    def test_admin_without_slash_redirects(self):
        response = self.client.get("/admin")
        self.assertEqual((response.status_code, response["Location"]), (301, "/admin/"))

    def test_https_and_host_and_path_fixed_in_a_single_hop(self):
        with override_settings(
            FORCE_HTTPS=True,
            SITE_URL="https://example.com",
            REDIRECT_HOSTS=["www.example.com"],
            ALLOWED_HOSTS=["example.com", "www.example.com", "testserver"],
        ):
            first = Client().get("/FAQ", HTTP_HOST="www.example.com")
            self.assertEqual((first.status_code, first["Location"]), (301, "https://example.com/faq/"))
            plain = Client().get("/faq/", HTTP_HOST="example.com")
            self.assertEqual((plain.status_code, plain["Location"]), (301, "https://example.com/faq/"))
            self.assertEqual(Client().get("/faq/", HTTP_HOST="example.com", secure=True).status_code, 200)
            self.assertEqual(Client().get("/health/", HTTP_HOST="example.com").status_code, 200)

class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.social = []
        self.description = []
        self.canonical = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name") or ""
            if key.startswith(("og:", "twitter:")):
                self.social.append((key, a.get("content") or ""))
            elif key == "description":
                self.description.append(a.get("content") or "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical.append(a.get("href"))


def _meta(client, path):
    parser = _MetaParser()
    parser.feed(client.get(path).content.decode())
    return parser


class OpenGraphTests(TestCase):
    REQUIRED = [
        "og:title", "og:type", "og:image", "og:url", "og:description", "og:site_name",
        "og:locale", "og:image:type", "og:image:width", "og:image:height", "og:image:alt",
        "twitter:card",
    ]

    def setUp(self):
        self.paths = ["/"] + [f"/{p['slug']}/" for p in PAGES]
        self.pages = {path: _meta(self.client, path) for path in self.paths}

    def test_every_tag_is_present_once_and_not_empty(self):
        for path, parsed in self.pages.items():
            keys = [k for k, _ in parsed.social]
            self.assertEqual(len(keys), len(set(keys)), path)
            for tag in self.REQUIRED:
                self.assertIn(tag, keys, (path, tag))
            for key, value in parsed.social:
                self.assertTrue(value.strip(), (path, key))

    def test_og_url_is_the_absolute_canonical_url(self):
        for path, parsed in self.pages.items():
            tags = dict(parsed.social)
            self.assertEqual([tags["og:url"]], parsed.canonical, path)
            self.assertEqual(tags["og:url"], settings.SITE_URL + path, path)

    def test_og_titles_have_no_brand_and_are_unique(self):
        titles = []
        for path, parsed in self.pages.items():
            title = dict(parsed.social)["og:title"]
            self.assertNotIn("|", title, path)
            titles.append(title)
        self.assertEqual(len(set(titles)), len(titles))

    def test_og_description_matches_meta_description(self):
        for path, parsed in self.pages.items():
            self.assertEqual(dict(parsed.social)["og:description"], parsed.description[0], path)

    def test_twitter_uses_the_large_card_and_nothing_else(self):
        for path, parsed in self.pages.items():
            twitter = [(k, v) for k, v in parsed.social if k.startswith("twitter:")]
            self.assertEqual(twitter, [("twitter:card", "summary_large_image")], path)

    def test_share_image_is_a_real_1200x630_png_within_limits(self):
        tags = dict(self.pages["/"].social)
        self.assertTrue(tags["og:image"].startswith(settings.SITE_URL + "/"))
        relative = urlparse(tags["og:image"]).path.removeprefix("/static/")
        file_path = finders.find(relative)
        self.assertIsNotNone(file_path, relative)
        with Image.open(file_path) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (int(tags["og:image:width"]), int(tags["og:image:height"])))
            self.assertEqual(image.size, (1200, 630))
        self.assertLess(os.path.getsize(file_path), 600_000)
        self.assertEqual(tags["og:image:type"], "image/png")
        self.assertLessEqual(len(tags["og:image:alt"]), 200)

    def test_404_page_has_no_social_tags(self):
        self.assertEqual(_meta(self.client, "/no-such-page/").social, [])

class MenuTests(TestCase):
    PATHS = ["/", "/water-levels/", "/alerts-events/", "/announcements/",
             "/flood-map/", "/safety-guide/", "/contact/"]

    def test_css_hides_nothing_except_the_menu(self):
        css_file = Path(settings.BASE_DIR) / "static" / "css" / "site.css"
        css = re.sub(r"/\*.*?\*/", "", css_file.read_text(encoding="utf-8"), flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            compact = re.sub(r"\s+", "", body)
            if "display:none" in compact or "visibility:hidden" in compact:
                self.assertTrue("menu-" in selector or ".site-nav" in selector, selector.strip())
        for path in self.PATHS:
            html = self.client.get(path).content.decode()
            self.assertIsNone(re.search(r"<[^>]+\shidden[\s>]", html), path)

    def test_collapsible_menu_is_wired_up_and_keeps_every_link(self):
        for path in self.PATHS:
            html = self.client.get(path).content.decode()
            self.assertIn('<input type="checkbox" id="menu-toggle" class="menu-toggle">', html)
            self.assertIn('<label class="menu-button" for="menu-toggle">', html)
            nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
            self.assertEqual(len(re.findall(r"<a href=", nav)), 5, path)

INGEST_TOKEN = "test-token-1234567890"


@override_settings(INGEST_TOKEN=INGEST_TOKEN)
class IngestTests(TestCase):
    URL = "/api/ingest/"

    def post(self, payload, token=INGEST_TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return self.client.post(self.URL, data=body, content_type="application/json", **headers)

    def payload(self, **overrides):
        data = {
            "schema": 1,
            "sent_at": "2026-11-23T09:00:00+08:00",
            "zones": [{"key": "zone-1", "name": "Zone 1", "state": "normal", "level_cm": 42.5,
                       "measured_at": "2026-11-23T08:59:30+08:00"}],
            "alerts": [{"id": "alert-1", "zone_key": "zone-1", "zone_name": "Zone 1",
                        "severity": "alert", "started_at": "2026-11-23T08:00:00+08:00",
                        "ended_at": None, "summary": "Water is rising."}],
            "announcements": [{"id": "note-1", "title": "Notice", "body": "Stay alert.",
                               "published_at": "2026-11-23T08:30:00+08:00", "active": True}],
        }
        data.update(overrides)
        return data

    def test_valid_payload_is_stored_and_resending_is_idempotent(self):
        for _ in range(2):
            response = self.post(self.payload())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
        self.assertEqual(ZoneStatus.objects.count(), 1)
        self.assertEqual(PublicAlert.objects.count(), 1)
        self.assertEqual(PublicAnnouncement.objects.count(), 1)
        self.assertEqual(HubHeartbeat.objects.count(), 1)
        self.assertEqual(ZoneStatus.objects.get().level_cm, 42.5)

    def test_updates_change_existing_rows(self):
        self.post(self.payload())
        changed = self.payload()
        changed["zones"][0]["state"] = "alert"
        changed["alerts"][0]["ended_at"] = "2026-11-23T10:00:00+08:00"
        changed["announcements"][0]["active"] = False
        self.assertEqual(self.post(changed).status_code, 200)
        self.assertEqual(ZoneStatus.objects.get().state, "alert")
        self.assertIsNotNone(PublicAlert.objects.get().ended_at)
        self.assertFalse(PublicAnnouncement.objects.get().is_active)

    def test_heartbeat_only_payload_is_accepted(self):
        response = self.post({"schema": 1, "sent_at": "2026-11-23T09:00:00+08:00"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(HubHeartbeat.objects.count(), 1)
        self.assertEqual(ZoneStatus.objects.count(), 0)

    def test_missing_or_wrong_token_is_rejected(self):
        for token in (None, "wrong", INGEST_TOKEN + "x"):
            response = self.post(self.payload(), token=token)
            self.assertEqual(response.status_code, 401, token)
            self.assertEqual(response["WWW-Authenticate"], "Bearer")
        self.assertEqual(ZoneStatus.objects.count(), 0)

    @override_settings(INGEST_TOKEN="")
    def test_disabled_when_no_token_is_configured(self):
        self.assertEqual(self.post(self.payload(), token="anything").status_code, 403)
        self.assertEqual(self.post(self.payload(), token="").status_code, 403)

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)

    def test_bad_payloads_are_rejected_and_nothing_is_saved(self):
        bad = []
        p = self.payload(); p["zones"][0]["state"] = "flooded"; bad.append(p)
        p = self.payload(); p["zones"][0]["measured_at"] = "2026-11-23T08:59:30"; bad.append(p)
        p = self.payload(); p["zones"][0]["level_cm"] = -5; bad.append(p)
        p = self.payload(); p["zones"][0]["key"] = "Zone 1!"; bad.append(p)
        p = self.payload(); p["alerts"][0]["severity"] = "panic"; bad.append(p)
        p = self.payload(); p["announcements"][0]["active"] = "yes"; bad.append(p)
        bad.append(self.payload(schema=2))
        bad.append(self.payload(zones=[
            {"key": f"z-{i}", "name": "Z", "state": "normal", "measured_at": "2026-11-23T08:59:30+08:00"}
            for i in range(51)]))
        for payload in bad:
            self.assertEqual(self.post(payload).status_code, 400, payload)
        for model in (ZoneStatus, PublicAlert, PublicAnnouncement, HubHeartbeat):
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_not_json_and_non_object_json_are_rejected(self):
        for body in ("not json", "[]", '"text"'):
            self.assertEqual(self.post(body).status_code, 400, body)

    def test_oversized_body_is_rejected(self):
        big = self.payload()
        big["announcements"][0]["body"] = "x" * 70_000
        self.assertEqual(self.post(json.dumps(big)).status_code, 413)

    def test_response_headers_and_no_cookies(self):
        response = self.post(self.payload())
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertEqual(len(response.cookies), 0)

class LivePagesTests(TestCase):
    LIVE_PATHS = ["/water-levels/", "/alerts-events/", "/announcements/"]

    def page(self, path):
        return self.client.get(path).content.decode()

    def beat(self, minutes_ago=0):
        HubHeartbeat.objects.update_or_create(
            pk=1, defaults={"last_seen": timezone.now() - timedelta(minutes=minutes_ago)})

    def zone(self, state="normal", minutes_ago=0, level=42.5):
        return ZoneStatus.objects.create(
            key="zone-1", name="Zone 1", state=state, level_cm=level,
            measured_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_empty_state_says_no_data_yet(self):
        html = self.page("/water-levels/")
        self.assertIn("No data has been received yet.", html)
        self.assertNotIn('class="zones"', html)

    def test_fresh_data_shows_state_and_level(self):
        self.beat(0)
        self.zone("alert")
        html = self.page("/water-levels/")
        self.assertIn('class="badge badge-alert"', html)
        self.assertIn("42.5 cm", html)
        self.assertIn("Live data.", html)
        self.assertNotIn("Data may be delayed.", html)

    def test_stale_heartbeat_turns_every_zone_unknown(self):
        self.beat(30)
        self.zone("normal")
        html = self.page("/water-levels/")
        self.assertIn("Data may be delayed.", html)
        self.assertIn("badge-unknown", html)
        self.assertNotIn("badge-normal", html)
        self.assertNotIn("42.5 cm", html)

    def test_old_zone_reading_turns_unknown_even_if_hub_is_live(self):
        self.beat(0)
        self.zone("normal", minutes_ago=30)
        html = self.page("/water-levels/")
        self.assertIn("badge-unknown", html)
        self.assertNotIn("badge-normal", html)

    def test_alerts_page_lists_active_and_recent(self):
        self.beat(0)
        now = timezone.now()
        PublicAlert.objects.create(external_id="a1", zone_key="zone-1", zone_name="Zone 1",
                                   severity="alert", started_at=now)
        PublicAlert.objects.create(external_id="a2", zone_key="zone-2", zone_name="Zone 2",
                                   severity="watch", started_at=now - timedelta(hours=2), ended_at=now)
        html = self.page("/alerts-events/")
        self.assertIn("Zone 1: Alert", html)
        self.assertIn("Zone 2: Watch", html)
        self.assertNotIn("There are no active alerts.", html)

    def test_no_alerts_claim_only_while_data_is_live(self):
        self.beat(0)
        self.assertIn("There are no active alerts.", self.page("/alerts-events/"))
        self.beat(30)
        html = self.page("/alerts-events/")
        self.assertNotIn("There are no active alerts.", html)
        self.assertIn("Alert information is unavailable right now.", html)

    def test_announcements_show_active_only_and_escape_html(self):
        now = timezone.now()
        PublicAnnouncement.objects.create(external_id="n1", title="Road closed",
                                          body="<script>alert(1)</script>", published_at=now)
        PublicAnnouncement.objects.create(external_id="n2", title="Old news", body="x",
                                          published_at=now, is_active=False)
        html = self.page("/announcements/")
        self.assertIn("Road closed", html)
        self.assertNotIn("Old news", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_live_pages_are_uncached_and_refresh_themselves(self):
        for path in self.LIVE_PATHS:
            response = self.client.get(path)
            self.assertIn("no-cache", response["Cache-Control"], path)
            self.assertRegex(response.content.decode(),
                             r'<script src="[^"]*live-refresh[^"]*" defer></script>')
        self.assertNotIn("live-refresh", self.page("/faq/"))

    def test_heading_levels_stay_valid_with_data(self):
        self.beat(0)
        self.zone("watch")
        now = timezone.now()
        PublicAlert.objects.create(external_id="a1", zone_key="zone-1", zone_name="Zone 1",
                                   severity="alert", started_at=now)
        PublicAnnouncement.objects.create(external_id="n1", title="Notice", body="Hello", published_at=now)
        for path in self.LIVE_PATHS:
            parser = _HeadingParser()
            parser.feed(self.page(path))
            levels = [h[0] for h in parser.headings]
            self.assertEqual(levels.count(1), 1, path)
            self.assertEqual(levels[0], 1, path)
            for prev, nxt in zip(levels, levels[1:]):
                self.assertLessEqual(nxt, prev + 1, (path, levels))

@override_settings(INGEST_TOKEN=INGEST_TOKEN)
class IngestReplaceTests(TestCase):
    def post(self, payload):
        return self.client.post("/api/ingest/", data=json.dumps(payload),
                                content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {INGEST_TOKEN}")

    def zone(self, key):
        return {"key": key, "name": key.upper(), "state": "normal", "level_cm": 10,
                "measured_at": "2026-11-23T08:59:30+08:00"}

    def note(self, ident):
        return {"id": ident, "title": ident, "body": "Text",
                "published_at": "2026-11-23T08:30:00+08:00", "active": True}

    def test_replace_removes_missing_zones_and_hides_missing_announcements(self):
        self.post({"schema": 1, "zones": [self.zone("z1"), self.zone("z2")],
                   "announcements": [self.note("n1"), self.note("n2")]})
        response = self.post({"schema": 1, "replace": ["zones", "announcements"],
                              "zones": [self.zone("z1")], "announcements": [self.note("n1")]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(ZoneStatus.objects.values_list("key", flat=True)), ["z1"])
        self.assertTrue(PublicAnnouncement.objects.get(external_id="n1").is_active)
        self.assertFalse(PublicAnnouncement.objects.get(external_id="n2").is_active)

    def test_without_replace_nothing_is_removed(self):
        self.post({"schema": 1, "zones": [self.zone("z1"), self.zone("z2")]})
        self.post({"schema": 1, "zones": [self.zone("z1")]})
        self.assertEqual(ZoneStatus.objects.count(), 2)

    def test_replace_with_empty_lists_clears_everything(self):
        self.post({"schema": 1, "zones": [self.zone("z1")], "announcements": [self.note("n1")]})
        self.post({"schema": 1, "replace": ["zones", "announcements"], "zones": [], "announcements": []})
        self.assertEqual(ZoneStatus.objects.count(), 0)
        self.assertFalse(PublicAnnouncement.objects.get().is_active)

    def test_bad_replace_values_are_rejected_and_change_nothing(self):
        self.post({"schema": 1, "zones": [self.zone("z1")]})
        for bad in (["alerts"], "zones", [["zones"]], [{"a": 1}]):
            response = self.post({"schema": 1, "replace": bad, "zones": []})
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(ZoneStatus.objects.count(), 1)

class EvacuationDataTests(TestCase):
    def test_entries_are_complete(self):
        from pages.evacuation_data import EVACUATION_CENTERS
        for c in EVACUATION_CENTERS:
            for key in ("name", "address", "capacity", "zones", "verified"):
                self.assertTrue(c.get(key), (c.get("name"), key))

class ReportsDataTests(TestCase):
    def test_entries_are_complete(self):
        from pages.reports_data import REPORTS
        for r in REPORTS:
            for key in ("title", "date", "summary"):
                self.assertTrue(r.get(key), (r.get("title"), key))

