"""WordPress REST API client."""

from __future__ import annotations

import re
import time
from html import escape, unescape
from typing import Optional

import requests
from bs4 import BeautifulSoup

from rss_to_wp.editorial import canonical_url
from rss_to_wp.utils import get_logger
from rss_to_wp.wordpress.media import wp_upload_media

logger = get_logger("wordpress.client")


class WordPressClient:
    """Client for WordPress REST API operations."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        default_status: str = "publish",
    ):
        """Initialize WordPress client.

        Args:
            base_url: WordPress site URL (no trailing slash).
            username: WordPress username.
            password: WordPress application password.
            default_status: Default post status (publish/draft).
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.default_status = default_status

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        self._category_cache: dict[str, int] = {}
        self._tag_cache: dict[str, int] = {}
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Rate limit API calls."""
        min_interval = 1.0  # 1 second between requests
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _api_url(self, endpoint: str) -> str:
        """Build full API URL.

        Args:
            endpoint: API endpoint path.

        Returns:
            Full URL.
        """
        return f"{self.base_url}/wp-json/wp/v2/{endpoint}"

    def check_duplicate_by_slug(self, slug: str) -> bool:
        """Check if a post with this slug already exists.

        Args:
            slug: Post slug to check.

        Returns:
            True if exists, False otherwise.
        """
        self._rate_limit()

        try:
            response = self.session.get(
                self._api_url("posts"),
                params={"slug": slug, "status": "any"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            posts = response.json()

            if posts:
                logger.debug("duplicate_found_by_slug", slug=slug, post_id=posts[0].get("id"))
                return True

            return False

        except Exception as e:
            logger.warning("duplicate_check_error", slug=slug, error=str(e))
            raise RuntimeError("Cannot verify WordPress duplicates") from e

    def check_duplicate_by_source_url(self, source_url: str) -> bool:
        """Check if a post containing this source URL already exists.

        This is the most reliable duplicate check since the source URL never changes.

        Args:
            source_url: Original article source URL.

        Returns:
            True if exists, False otherwise.
        """
        return self.find_post_by_source(source_url) is not None

    def find_post_by_source(self, source_url: str) -> Optional[dict]:
        """Exact link comparison, paginated; request failures must stop publishing."""
        target = canonical_url(source_url)
        # Exclude tracking queries from search; identity queries remain intact.
        for page in range(1, 101):
            self._rate_limit()
            response = self.session.get(
                self._api_url("posts"),
                params={
                    "search": target,
                    "status": "any",
                    "per_page": 100,
                    "page": page,
                    "context": "edit",
                    "_fields": "id,link,title,content,status",
                },
                timeout=(10, 30),
            )
            response.raise_for_status()
            posts = response.json()
            for post in posts:
                content = post.get("content", {}).get("raw") or post.get("content", {}).get(
                    "rendered", ""
                )
                soup = BeautifulSoup(unescape(content), "html.parser")
                for anchor in soup.find_all("a", href=True):
                    try:
                        if canonical_url(anchor["href"]) == target:
                            return post
                    except ValueError:
                        continue
            if page >= int(response.headers.get("X-WP-TotalPages", 1)):
                return None
        raise RuntimeError("Duplicate search exceeded pagination limit")

    def get_or_create_category(self, name: str) -> Optional[int]:
        """Get category ID, creating it if it doesn't exist.

        Args:
            name: Category name.

        Returns:
            Category ID or None.
        """
        # Check cache first
        if name in self._category_cache:
            return self._category_cache[name]

        self._rate_limit()

        slug = self._slugify(name)

        # Try to find existing
        try:
            response = self.session.get(
                self._api_url("categories"),
                params={"slug": slug},
                timeout=(10, 30),
            )
            response.raise_for_status()
            categories = response.json()

            if categories:
                cat_id = categories[0]["id"]
                self._category_cache[name] = cat_id
                return cat_id

        except Exception as e:
            logger.warning("category_search_error", name=name, error=str(e))

        # Create new category
        self._rate_limit()
        try:
            response = self.session.post(
                self._api_url("categories"),
                json={"name": name, "slug": slug},
                timeout=(10, 30),
            )
            response.raise_for_status()
            cat_data = response.json()
            cat_id = cat_data["id"]
            self._category_cache[name] = cat_id
            logger.info("category_created", name=name, id=cat_id)
            return cat_id

        except requests.exceptions.HTTPError as e:
            # Category might exist with different slug
            if e.response.status_code == 400:
                logger.warning("category_create_conflict", name=name)
            else:
                logger.error("category_create_error", name=name, error=str(e))
            return None
        except Exception as e:
            logger.error("category_create_error", name=name, error=str(e))
            return None

    def get_or_create_tags(self, names: list[str]) -> list[int]:
        """Get or create multiple tags.

        Args:
            names: List of tag names.

        Returns:
            List of tag IDs.
        """
        tag_ids = []

        for name in names:
            if not name:
                continue

            # Check cache
            if name in self._tag_cache:
                tag_ids.append(self._tag_cache[name])
                continue

            self._rate_limit()
            slug = self._slugify(name)

            # Try to find existing
            try:
                response = self.session.get(
                    self._api_url("tags"),
                    params={"slug": slug},
                    timeout=(10, 30),
                )
                response.raise_for_status()
                tags = response.json()

                if tags:
                    tag_id = tags[0]["id"]
                    self._tag_cache[name] = tag_id
                    tag_ids.append(tag_id)
                    continue

            except Exception as e:
                logger.warning("tag_search_error", name=name, error=str(e))

            # Create new tag
            self._rate_limit()
            try:
                response = self.session.post(
                    self._api_url("tags"),
                    json={"name": name, "slug": slug},
                    timeout=(10, 30),
                )
                response.raise_for_status()
                tag_data = response.json()
                tag_id = tag_data["id"]
                self._tag_cache[name] = tag_id
                tag_ids.append(tag_id)
                logger.info("tag_created", name=name, id=tag_id)

            except Exception as e:
                logger.warning("tag_create_error", name=name, error=str(e))

        return tag_ids

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug.

        Args:
            text: Text to slugify.

        Returns:
            Slug string.
        """
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug.strip("-")

    def upload_media(
        self,
        image_bytes: bytes,
        filename: str,
        alt_text: str = "",
    ) -> Optional[int]:
        """Upload image to media library.

        Args:
            image_bytes: Image content.
            filename: Filename for upload.
            alt_text: Alt text for image.

        Returns:
            Media ID or None.
        """
        return wp_upload_media(
            image_bytes=image_bytes,
            filename=filename,
            alt_text=alt_text,
            base_url=self.base_url,
            username=self.username,
            password=self.password,
            session=self.session,
        )

    def create_post(
        self,
        title: str,
        content: str,
        excerpt: str = "",
        category_id: Optional[int] = None,
        tag_ids: Optional[list[int]] = None,
        featured_media_id: Optional[int] = None,
        source_url: Optional[str] = None,
        status: Optional[str] = None,
        sources: Optional[list[dict]] = None,
        slug: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a new WordPress post.

        Args:
            title: Post title.
            content: Post content (HTML).
            excerpt: Post excerpt.
            category_id: Category ID.
            tag_ids: List of tag IDs.
            featured_media_id: Featured image media ID.
            source_url: Original source URL for attribution.
            status: Post status (publish/draft).

        Returns:
            Created post data or None.
        """
        # PRIMARY CHECK: Check for duplicate by source URL (most reliable - URL never changes)
        sources = sources or (
            [{"url": source_url, "name": "Original source"}] if source_url else []
        )
        for source in sources:
            existing = self.find_post_by_source(source["url"])
            if existing:
                return {**existing, "already_exists": True}
        if slug and self.check_duplicate_by_slug(slug):
            raise RuntimeError("Story slug already exists; reconcile before retrying")

        self._rate_limit()

        # Add source attribution to content
        if sources:
            links = [
                f'<a href="{escape(canonical_url(s["url"]), quote=True)}" rel="noopener">{escape(s["name"])}</a>'
                for s in sources
            ]
            content += "<p><em>Sources: " + "; ".join(links) + "</em></p>"
        content += '<p><small>This report was prepared with AI assistance from the sources linked above. Send corrections or additional information through our <a href="/contact-us/">contact page</a>.</small></p>'

        post_data = {
            "title": title,
            "content": content,
            "status": status or self.default_status,
        }

        if excerpt:
            post_data["excerpt"] = excerpt
        if slug:
            post_data["slug"] = slug

        if category_id:
            post_data["categories"] = [category_id]

        if tag_ids:
            post_data["tags"] = tag_ids

        if featured_media_id:
            post_data["featured_media"] = featured_media_id

        logger.info("creating_post", title=title[:50], status=post_data["status"])

        try:
            response = self.session.post(
                self._api_url("posts"),
                json=post_data,
                timeout=(10, 60),
            )
            response.raise_for_status()
            post = response.json()

            logger.info(
                "post_created",
                post_id=post.get("id"),
                title=title[:50],
                url=post.get("link"),
            )

            return post

        except requests.exceptions.HTTPError as e:
            logger.error(
                "post_create_http_error",
                error=str(e),
                status=e.response.status_code,
                response=e.response.text[:500],
            )
            return None
        except requests.exceptions.RequestException as e:
            logger.error("post_create_error", error=str(e))
            return None


def wp_create_post(
    title: str,
    content: str,
    base_url: str,
    username: str,
    password: str,
    **kwargs,
) -> Optional[dict]:
    """Convenience function to create a WordPress post.

    Args:
        title: Post title.
        content: Post content.
        base_url: WordPress base URL.
        username: WordPress username.
        password: WordPress application password.
        **kwargs: Additional arguments for create_post.

    Returns:
        Created post data or None.
    """
    client = WordPressClient(base_url, username, password)
    return client.create_post(title, content, **kwargs)
