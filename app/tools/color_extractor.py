import base64
from io import BytesIO

from colorthief import ColorThief

from app.core.logging import logger


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def extract_colors_from_images(b64_images: list[str], max_colors: int = 5) -> list[str]:
    """Extract dominant hex colors from base64-encoded images using colorthief."""
    seen: set[str] = set()
    colors: list[str] = []

    for b64 in b64_images:
        if len(colors) >= max_colors:
            break
        try:
            image_bytes = base64.b64decode(b64)
            thief = ColorThief(BytesIO(image_bytes))
            palette = thief.get_palette(color_count=3, quality=5)
            for rgb in palette:
                hex_color = _rgb_to_hex(*rgb)
                if hex_color not in seen:
                    seen.add(hex_color)
                    colors.append(hex_color)
                    if len(colors) >= max_colors:
                        break
        except Exception as exc:
            logger.warning("color_extraction_failed", error=str(exc))

    return colors
