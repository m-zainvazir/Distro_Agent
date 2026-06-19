"""Dynamic Context Router (Blueprint Layers 19 / 12 / 17).

Maps a frontend ``vertical_tag`` (industry) to a ``VerticalProfile`` that carries
hyper-specific, niche-aware guidance, which is injected into the LLM prompts at
runtime — keeping the backend 100% horizontal (no hardcoded vertical logic in the
agents) while delivering vertical personalisation:

- **Scouting** (scout agent): which store types to prioritise for this vertical.
- **Brand extraction** (brand analyzer): which niche-critical signals to surface
  (e.g. cruelty-free / Leaping Bunny / ingredient profiles for aesthetic beauty).

Add a new vertical by adding one ``VerticalProfile`` to ``_PROFILES`` — no agent
code changes required. Unknown / missing tags resolve to a safe general default.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerticalProfile:
    """Runtime context-injection profile for one industry vertical."""

    tag: str
    display_name: str
    aliases: tuple[str, ...] = ()
    store_types: tuple[str, ...] = ()     # store types to prioritise when scouting
    niche_signals: tuple[str, ...] = ()   # niche-critical cues to extract from a brand

    def scouting_prompt_addendum(self) -> str:
        """Extra instruction injected into the scout's query-generation prompt."""
        if not self.store_types:
            return ""
        return (
            f"\n\nThis is a {self.display_name} brand. Prioritise these store types: "
            f"{', '.join(self.store_types)}."
        )

    def extraction_prompt_addendum(self) -> str:
        """Extra instruction injected into the brand-analyzer prompt."""
        if not self.niche_signals:
            return ""
        return (
            f"\n\nThis is a {self.display_name} brand. Pay special attention to these "
            f"niche signals and reflect any that apply in aesthetic_keywords and "
            f"brand_voice_description: {', '.join(self.niche_signals)}."
        )


_DEFAULT = VerticalProfile(tag="default", display_name="general retail")

_PROFILES: tuple[VerticalProfile, ...] = (
    VerticalProfile(
        tag="aesthetic_beauty",
        display_name="aesthetic beauty",
        aliases=("beauty", "skincare", "cosmetics", "clean_beauty", "makeup"),
        store_types=(
            "clean-beauty boutiques",
            "medical spas",
            "skincare salons",
            "apothecaries",
            "wellness concept stores",
        ),
        niche_signals=(
            "clean beauty positioning",
            "cruelty-free / Leaping Bunny certification",
            "vegan formulation",
            "key active ingredients (e.g. hyaluronic acid, retinol, niacinamide)",
            "dermatologist-tested claims",
            "sustainable / refillable packaging",
        ),
    ),
    VerticalProfile(
        tag="fashion",
        display_name="fashion & apparel",
        aliases=("apparel", "clothing", "accessories", "jewelry"),
        store_types=(
            "indie fashion boutiques",
            "curated apparel shops",
            "concept stores",
            "accessory boutiques",
        ),
        niche_signals=(
            "sustainable / ethical sourcing",
            "material composition",
            "size inclusivity",
            "capsule / seasonal positioning",
            "made-to-order or small-batch production",
        ),
    ),
    VerticalProfile(
        tag="wellness",
        display_name="health & wellness",
        aliases=("health", "supplements", "fitness", "nutrition"),
        store_types=(
            "wellness studios",
            "yoga & pilates studios",
            "health food stores",
            "spa retail counters",
        ),
        niche_signals=(
            "certifications (USDA Organic, NSF, GMP)",
            "adaptogens / functional actives",
            "clean label / no artificial additives",
            "third-party lab testing",
            "dosage and serving guidance",
        ),
    ),
    VerticalProfile(
        tag="home_goods",
        display_name="home & lifestyle",
        aliases=("home", "decor", "homeware", "lifestyle", "candles"),
        store_types=(
            "home decor boutiques",
            "design studios",
            "gift shops",
            "lifestyle concept stores",
        ),
        niche_signals=(
            "artisan / handmade craftsmanship",
            "sustainable materials",
            "small-batch production",
            "design provenance / origin story",
        ),
    ),
    VerticalProfile(
        tag="food_beverage",
        display_name="food & beverage",
        aliases=("food", "beverage", "cpg", "grocery", "fnb", "snacks"),
        store_types=(
            "specialty grocers",
            "gourmet food shops",
            "cafes & roasteries",
            "natural food stores",
        ),
        niche_signals=(
            "organic / non-GMO certification",
            "allergen and dietary info (gluten-free, vegan, keto)",
            "shelf life and storage",
            "local / regional sourcing",
        ),
    ),
)


def _norm(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


# Precomputed lookup: every normalised tag + alias → profile.
_LOOKUP: dict[str, VerticalProfile] = {}
for _p in _PROFILES:
    _LOOKUP[_norm(_p.tag)] = _p
    for _alias in _p.aliases:
        _LOOKUP[_norm(_alias)] = _p


def resolve_vertical(tag: str | None) -> VerticalProfile:
    """Resolve a vertical_tag (or alias) to its profile; unknown/empty → default."""
    if not tag:
        return _DEFAULT
    return _LOOKUP.get(_norm(tag), _DEFAULT)


def list_verticals() -> list[str]:
    """Return the canonical tags of all configured verticals."""
    return [p.tag for p in _PROFILES]
