"""Curated map from Google Places types to consumer-facing search terms.

Used as the fallback scorer when embeddings are unavailable, bridging
Google's technical taxonomy ("cosmetics_store") to brand vocabulary ("makeup").
"""

GOOGLE_TYPE_TO_CONSUMER_TERMS: dict[str, list[str]] = {
    # Beauty & personal care
    "cosmetics_store":        ["makeup", "beauty", "skincare", "fragrance", "cosmetics"],
    "beauty_salon":           ["beauty", "skincare", "spa", "salon", "wellness"],
    "hair_care":              ["hair", "salon", "beauty", "grooming", "style"],
    "spa":                    ["wellness", "beauty", "relaxation", "skincare", "self-care"],
    "nail_salon":             ["nails", "beauty", "manicure", "pedicure", "salon"],
    "massage_therapist":      ["wellness", "massage", "relaxation", "health", "spa"],
    # Fashion & accessories
    "shoe_store":             ["footwear", "shoes", "sneakers", "boots", "sandals"],
    "clothing_store":         ["apparel", "clothing", "fashion", "style", "wear"],
    "jewelry_store":          ["jewelry", "accessories", "luxury", "gems", "fashion"],
    "optical_store":          ["eyewear", "accessories", "fashion", "health", "vision"],
    "hat_store":              ["hats", "accessories", "fashion", "headwear", "style"],
    "lingerie_store":         ["lingerie", "intimates", "fashion", "accessories", "women"],
    # Home & lifestyle
    "home_goods_store":       ["home", "decor", "lifestyle", "interior", "living"],
    "furniture_store":        ["furniture", "home", "interior", "decor", "design"],
    "florist":                ["flowers", "plants", "gifts", "home", "decor"],
    "candle_store":           ["candles", "home", "fragrance", "wellness", "decor"],
    "interior_design":        ["interior", "home", "decor", "design", "lifestyle"],
    "art_gallery":            ["art", "culture", "design", "home", "decor"],
    # Food & wellness
    "health_food_store":      ["wellness", "organic", "nutrition", "supplements", "health"],
    "pharmacy":               ["health", "wellness", "beauty", "personal care", "medicine"],
    "grocery_or_supermarket": ["food", "organic", "wellness", "nutrition", "grocery"],
    "bakery":                 ["food", "artisan", "desserts", "pastry", "gourmet"],
    "cafe":                   ["coffee", "food", "lifestyle", "culture", "community"],
    "tea_shop":               ["tea", "wellness", "organic", "lifestyle", "health"],
    # Gifts & novelty
    "gift_shop":              ["gifts", "home", "accessories", "lifestyle", "novelty"],
    "book_store":             ["books", "stationery", "education", "gifts", "culture"],
    "stationery_store":       ["stationery", "paper", "office", "gifts", "writing"],
    "toy_store":              ["toys", "games", "kids", "children", "play"],
    "craft_store":            ["crafts", "art", "diy", "supplies", "creative"],
    # Sports & outdoor
    "sporting_goods_store":   ["sports", "fitness", "outdoor", "activewear", "gear"],
    "bicycle_store":          ["cycling", "bikes", "outdoor", "fitness", "sports"],
    "yoga_studio":            ["yoga", "wellness", "fitness", "mindfulness", "health"],
    # General retail
    "department_store":       ["fashion", "home", "beauty", "accessories", "lifestyle"],
    "market":                 ["artisan", "local", "organic", "gifts", "food"],
    "pet_store":              ["pets", "animals", "accessories", "care", "supplies"],
    "music_store":            ["music", "instruments", "culture", "gifts", "entertainment"],
}
