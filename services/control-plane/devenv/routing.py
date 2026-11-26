"""Which kind of agent may run a task, beyond the planner's own choice.

Claude agents cannot generate images, so a task that needs new images (a logo, icons, an illustration,
artwork) runs only on an OpenAI Codex agent. Planners say so with `needs_images`; titles and descriptions
that plainly ask for generated images are caught too, so nobody has to remember the flag."""

import re

_MAKE = r"(?:generate|create|make(?!\s+sure)|draw|design|render|produce|paint|illustrate|redraw|regenerate)"
_IMAGE = (
    r"(?:images?|pictures?|logos?|icons?|icon set|illustrations?|artwork|art|sprites?|favicons?|banners?|"
    r"thumbnails?|graphics?|hero image|cover image|avatars?|portraits?|textures?|map art)"
)
# A making verb with an image noun at most three words later ("generate a new logo"), or the noun then the
# verb ("hero image to be generated"). Kept tight so "create an endpoint for avatars" does not match.
_NEEDS_IMAGES = re.compile(
    rf"\b{_MAKE}\b(?:\s+[\w'-]+){{0,3}}?\s+{_IMAGE}\b"
    rf"|\b{_IMAGE}\s+(?:needs? to|should|must|to) be\s+(?:generated|created|made|drawn|designed|rendered|painted)\b",
    re.IGNORECASE,
)


def detect_images(title: str, description: str = "") -> bool:
    return bool(_NEEDS_IMAGES.search(f"{title}\n{description}"))


def route(item: dict, detect: bool = True) -> str:
    """Set `needs_images` and, when it is set, `provider` = codex. Returns a note for the task log, or "".

    `detect` False trusts the item's own `needs_images` (someone set it to false on purpose)."""
    flagged = bool(item.get("needs_images"))
    if not flagged and detect and detect_images(item.get("title", ""), item.get("description", "")):
        flagged = True
        why = "it asks for generated images"
    else:
        why = "it needs images"
    item["needs_images"] = flagged
    if not flagged:
        return ""
    before = item.get("provider") or "any"
    item["provider"] = "codex"
    if before == "codex":
        return ""
    return f"routed to an OpenAI Codex agent because {why} (Claude agents cannot generate images)"
