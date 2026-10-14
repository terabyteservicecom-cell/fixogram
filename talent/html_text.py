from html import escape
from html.parser import HTMLParser
import re

ALLOWED = {
    "p",
    "br",
    "hr",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "a",
    "img",
    "figure",
    "figcaption",
    "picture",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "div",
    "span",
    "section",
    "article",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
    "details",
    "summary",
    "mark",
    "small",
    "time",
    "abbr",
    "address",
    "dl",
    "dt",
    "dd",
    "video",
    "audio",
    "source",
    "track",
    "sub",
    "sup",
    "style",
    "template",
    "link",
}
VOID = {"br", "hr", "img", "source", "track", "col", "link"}
SKIP = {"script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "base", "meta"}
RAW = {"style", "template"}
GLOBAL_ATTRS = {
    "class",
    "id",
    "title",
    "dir",
    "lang",
    "role",
    "style",
    "hidden",
}
ATTRS = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "video": {"src", "poster", "width", "height", "controls", "autoplay", "muted", "loop", "playsinline"},
    "audio": {"src", "controls", "autoplay", "muted", "loop"},
    "source": {"src", "type", "media"},
    "track": {"src", "kind", "srclang", "label", "default"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "time": {"datetime"},
    "link": {"href", "rel", "type", "media"},
    "style": {"type", "media"},
}
BOOL_ATTRS = {
    "controls",
    "autoplay",
    "muted",
    "loop",
    "playsinline",
    "hidden",
    "default",
}
SAFE_STYLE = re.compile(r"(expression\s*\(|url\s*\(\s*['\"]?\s*javascript:|@import)", re.I)


def safe_url(value):
    text = (value or "").strip().replace("\x00", "")
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "/", "#", "data:image/")):
        return text
    return ""


def safe_style(value):
    text = (value or "").strip().replace("\x00", "")
    if not text or SAFE_STYLE.search(text):
        return ""
    return text


def allowed_attr(tag, key):
    if key in GLOBAL_ATTRS or key.startswith("data-") or key.startswith("aria-"):
        return True
    return key in ATTRS.get(tag, set())


class Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.skip = 0
        self.raw_stack = []

    def handle_starttag(self, tag, attrs):
        self._start(tag.lower(), attrs, void=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag.lower(), attrs, void=True)

    def _start(self, tag, attrs, void):
        if tag in SKIP:
            if not void:
                self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        if tag == "link":
            rel = ""
            href = ""
            for key, value in attrs:
                key = (key or "").lower()
                if key == "rel":
                    rel = (value or "").lower()
                elif key == "href":
                    href = safe_url(value)
            if "stylesheet" not in rel.split() or not href:
                return
        clean = []
        for key, value in attrs:
            key = (key or "").lower()
            if key.startswith("on") or not allowed_attr(tag, key):
                continue
            if key in BOOL_ATTRS:
                clean.append(key)
                continue
            if key in {"href", "src", "poster"}:
                value = safe_url(value)
                if not value:
                    continue
            if key == "style":
                value = safe_style(value)
                if not value:
                    continue
            if key == "target" and (value or "") not in {"_blank", "_self"}:
                continue
            if key in {"width", "height", "colspan", "rowspan", "span"} and not str(value).isdigit():
                continue
            if key == "type" and tag == "source":
                if not (value or "").lower().startswith(("video/", "audio/")):
                    continue
            if key == "rel" and tag == "a":
                continue
            clean.append(f'{key}="{escape(value or "", quote=True)}"')
        if tag == "a":
            clean.append('rel="noopener noreferrer"')
        attr = (" " + " ".join(clean)) if clean else ""
        if tag in VOID or void:
            self.parts.append(f"<{tag}{attr}>")
            return
        self.parts.append(f"<{tag}{attr}>")
        self.stack.append(tag)
        if tag in RAW:
            self.raw_stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            if self.raw_stack and self.raw_stack[-1] == open_tag:
                self.raw_stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.skip or not data:
            return
        if self.raw_stack:
            kind = self.raw_stack[-1]
            if kind == "style":
                text = re.sub(r"</style", "<\\/style", data, flags=re.I)
                self.parts.append(text)
                return
            self.parts.append(data)
            return
        if self.stack and self.stack[-1] in {"pre", "code"}:
            self.parts.append(escape(data))
            return
        if not data.strip():
            return
        text = escape(data)
        if "\n" in data and self.stack and self.stack[-1] in {"p", "li", "td", "th", "span", "a", "strong", "b", "em", "i", "u", "s", "label"}:
            text = text.replace("\n", "<br>\n")
        self.parts.append(text)

    def close(self):
        super().close()
        while self.stack:
            open_tag = self.stack.pop()
            if self.raw_stack and self.raw_stack[-1] == open_tag:
                self.raw_stack.pop()
            self.parts.append(f"</{open_tag}>")


def sanitize_html(value):
    cleaner = Cleaner()
    cleaner.feed(value or "")
    cleaner.close()
    return "".join(cleaner.parts).strip()
