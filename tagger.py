"""Auto-tag items on a Nextcloud Tasks shopping list using OpenAI.

Polls a Nextcloud Tasks list over CalDAV. Any open item that doesn't yet carry
one of the allowed tags is sent to OpenAI, which must answer with exactly one
of those tags. The tag is written back as a CATEGORIES value, which the
Nextcloud Tasks app shows as a tag.
"""

import json
import logging
import os
import sys
import time

import caldav
from openai import OpenAI

log = logging.getLogger("tagger")

BATCH_SIZE = 50


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def env_bool(name, default="false"):
    return env(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self):
        base = env("NEXTCLOUD_URL", required=True).rstrip("/")
        # Accept either the server root or a full DAV URL.
        self.dav_url = base if "/remote.php/dav" in base else f"{base}/remote.php/dav"
        self.user = env("NEXTCLOUD_USER", required=True)
        self.password = env("NEXTCLOUD_APP_PASSWORD", required=True)
        self.list_name = env("LIST_NAME", "Shopping")
        # Use a different separator (e.g. "|") if any tag contains a comma.
        sep = env("TAGS_SEPARATOR", ",")
        self.tags = [t.strip() for t in env("TAGS", required=True).split(sep) if t.strip()]
        self.openai_key = env("OPENAI_API_KEY", required=True)
        self.model = env("OPENAI_MODEL", "gpt-5-mini")
        self.hints = env("PROMPT_HINTS", "")
        self.poll_interval = int(env("POLL_INTERVAL", "60"))
        self.run_once = env_bool("RUN_ONCE")
        self.dry_run = env_bool("DRY_RUN")
        if len(self.tags) < 2:
            sys.exit("TAGS must list at least two comma-separated tags")


def get_categories(component):
    """Return the CATEGORIES on an icalendar component as a flat list of strings."""
    raw = component.get("categories")
    if raw is None:
        return []
    props = raw if isinstance(raw, list) else [raw]
    cats = []
    for prop in props:
        cats.extend(str(c) for c in getattr(prop, "cats", [prop]))
    return cats


def set_categories(component, cats):
    component.pop("categories", None)
    if cats:
        component.add("categories", cats)


def find_list(client, name):
    calendars = client.principal().calendars()
    for cal in calendars:
        if (cal.name or "").strip().lower() == name.strip().lower():
            return cal
    available = ", ".join(repr(c.name) for c in calendars)
    raise LookupError(f"No task list named {name!r}. Available: {available}")


class Classifier:
    def __init__(self, cfg):
        self.client = OpenAI(api_key=cfg.openai_key)
        self.model = cfg.model
        self.tags = cfg.tags
        prompt = (
            "You sort items on a family shopping list into categories. "
            "Give every item exactly one tag from the allowed list: the one that "
            "best matches where you would find it, or what it is. Items may contain "
            "quantities, brands, typos, or be written in any language."
        )
        if cfg.hints:
            prompt += f"\n\nHousehold-specific rules:\n{cfg.hints}"
        self.system_prompt = prompt
        self.schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "tag": {"type": "string", "enum": self.tags},
                        },
                        "required": ["id", "tag"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        }

    def classify(self, summaries):
        """Map each summary to a tag. Returns {index: tag}."""
        listing = "\n".join(f"{i}: {s}" for i, s in enumerate(summaries))
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": f"Allowed tags: {json.dumps(self.tags)}\n\nItems:\n{listing}",
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "shopping_tags", "strict": True, "schema": self.schema},
            },
        )
        data = json.loads(resp.choices[0].message.content)
        return {
            row["id"]: row["tag"]
            for row in data["items"]
            if 0 <= row["id"] < len(summaries) and row["tag"] in self.tags
        }


def run_pass(cfg, client, classifier):
    task_list = find_list(client, cfg.list_name)
    allowed = {t.lower() for t in cfg.tags}

    pending = []
    for todo in task_list.todos(include_completed=False):
        comp = todo.icalendar_component
        summary = str(comp.get("summary", "")).strip()
        if not summary:
            continue
        if any(c.lower() in allowed for c in get_categories(comp)):
            continue
        pending.append((todo, summary))

    if not pending:
        log.debug("Nothing to tag")
        return 0

    log.info("Tagging %d item(s)", len(pending))
    tagged = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        result = classifier.classify([summary for _, summary in batch])
        for i, (todo, summary) in enumerate(batch):
            tag = result.get(i)
            if not tag:
                log.warning("No tag returned for %r", summary)
                continue
            log.info("%-30s -> %s", summary, tag)
            if cfg.dry_run:
                continue
            comp = todo.icalendar_component
            # Keep any unrelated categories the family added by hand.
            set_categories(comp, get_categories(comp) + [tag])
            todo.save()
            tagged += 1
    return tagged


def main():
    logging.basicConfig(
        level=env("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = Config()
    client = caldav.DAVClient(url=cfg.dav_url, username=cfg.user, password=cfg.password)
    classifier = Classifier(cfg)
    log.info(
        "Watching list %r with tags %s (model %s, every %ss%s)",
        cfg.list_name, cfg.tags, cfg.model, cfg.poll_interval,
        ", DRY RUN" if cfg.dry_run else "",
    )

    while True:
        try:
            run_pass(cfg, client, classifier)
        except Exception:
            log.exception("Pass failed; will retry")
            if cfg.run_once:
                sys.exit(1)
        if cfg.run_once:
            return
        time.sleep(cfg.poll_interval)


if __name__ == "__main__":
    main()
