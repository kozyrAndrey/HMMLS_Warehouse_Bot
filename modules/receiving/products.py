# ============================================================
# СПИСОК ТОВАРОВ
# ============================================================
# Теперь каталог устроен так:
# группа → модель → цвет / вариант.
#
# Бот будет выбирать:
# группа → модель → цвет / вариант → размер.
#
# Поле CATEGORIES дополнительно создаёт плоский список products,
# чтобы старые модули database.py и google_sheets.py могли продолжать
# получать название товара по product_id.

PRODUCT_CATALOG = {
    "hoodies": {
        "name": "Худи / Зипы",
        "models": {
            "culture_hoodie": {
                "name": "CULTURE HOODIE",
                "variants": {
                    "grey": {
                        "id": "h001",
                        "color": "GREY",
                        "name": "CULTURE HOODIE GREY",
                    },
                    "blue": {
                        "id": "h002",
                        "color": "BLUE",
                        "name": "CULTURE HOODIE BLUE",
                    },
                    "black": {
                        "id": "h003",
                        "color": "BLACK",
                        "name": "CULTURE HOODIE BLACK",
                    },
                },
            },
            "diamond_hoodie": {
                "name": "DIAMOND HOODIE",
                "variants": {
                    "black": {
                        "id": "h004",
                        "color": "BLACK",
                        "name": "DIAMOND HOODIE BLACK",
                    },
                    "melange": {
                        "id": "h005",
                        "color": "MELANGE",
                        "name": "DIAMOND HOODIE MELANGE",
                    },
                    "pink": {
                        "id": "h006",
                        "color": "PINK",
                        "name": "DIAMOND HOODIE PINK",
                    },
                },
            },
            "diamond_v2_zip_hoodie": {
                "name": "DIAMOND V2 ZIP HOODIE",
                "variants": {
                    "dark_blue": {
                        "id": "h010",
                        "color": "DARK BLUE",
                        "name": "DIAMOND V2 ZIP HOODIE DARK BLUE",
                    },
                    "pink": {
                        "id": "h011",
                        "color": "PINK",
                        "name": "DIAMOND V2 ZIP HOODIE PINK",
                    },
                    "black": {
                        "id": "h012",
                        "color": "BLACK",
                        "name": "DIAMOND V2 ZIP HOODIE BLACK",
                    },
                },
            },
            "diamond_zip_hoodie": {
                "name": "DIAMOND ZIP HOODIE",
                "variants": {
                    "one": {
                        "id": "h007",
                        "color": "ONE COLOR",
                        "name": "DIAMOND ZIP HOODIE",
                    },
                },
            },
            "not_paris_zip_hoodie": {
                "name": "NOT PARIS ZIP HOODIE",
                "variants": {
                    "black": {
                        "id": "h008",
                        "color": "BLACK",
                        "name": "NOT PARIS ZIP HOODIE BLACK",
                    },
                },
            },
            "sweetheart_zip_hoodie_crop": {
                "name": "SWEETHEART ZIP HOODIE CROP",
                "variants": {
                    "one": {
                        "id": "h009",
                        "color": "ONE COLOR",
                        "name": "SWEETHEART ZIP HOODIE CROP",
                    },
                },
            },
        },
    },

    "tshirts": {
        "name": "Футболки",
        "models": {
            "not_paris_tshirt": {
                "name": "NOT PARIS T-SHIRT",
                "variants": {
                    "black": {
                        "id": "t001",
                        "color": "BLACK",
                        "name": "NOT PARIS T-SHIRT BLACK",
                    },
                    "white": {
                        "id": "t002",
                        "color": "WHITE",
                        "name": "NOT PARIS T-SHIRT WHITE",
                    },
                },
            },
            "paramount_tshirt": {
                "name": "PARAMOUNT TSHIRT",
                "variants": {
                    "black": {
                        "id": "t003",
                        "color": "BLACK",
                        "name": "PARAMOUNT TSHIRT BLACK",
                    },
                    "ecru": {
                        "id": "t004",
                        "color": "ECRU",
                        "name": "PARAMOUNT TSHIRT ECRU",
                    },
                },
            },
            "stamp_tshirt": {
                "name": "STAMP TSHIRT",
                "variants": {
                    "black": {
                        "id": "t005",
                        "color": "BLACK",
                        "name": "STAMP TSHIRT BLACK",
                    },
                    "grey": {
                        "id": "t006",
                        "color": "GREY",
                        "name": "STAMP TSHIRT GREY",
                    },
                    "ecru": {
                        "id": "t007",
                        "color": "ECRU",
                        "name": "STAMP TSHIRT ECRU",
                    },
                },
            },
            "stickers_tshirt": {
                "name": "STICKERS TSHIRT",
                "variants": {
                    "black": {
                        "id": "t008",
                        "color": "BLACK",
                        "name": "STICKERS TSHIRT BLACK",
                    },
                    "ecru": {
                        "id": "t009",
                        "color": "ECRU",
                        "name": "STICKERS TSHIRT ECRU",
                    },
                },
            },
            "humble_tshirt": {
                "name": "HUMBLE TSHIRT",
                "variants": {
                    "black": {
                        "id": "t010",
                        "color": "BLACK",
                        "name": "HUMBLE TSHIRT BLACK",
                    },
                },
            },
            "network_tshirt": {
                "name": "NETWORK TSHIRT",
                "variants": {
                    "black": {
                        "id": "t011",
                        "color": "BLACK",
                        "name": "NETWORK TSHIRT BLACK",
                    },
                    "ecru": {
                        "id": "t012",
                        "color": "ECRU",
                        "name": "NETWORK TSHIRT ECRU",
                    },
                },
            },
            "hommeless_tshirt": {
                "name": "HOMMELESS TSHIRT",
                "variants": {
                    "black": {
                        "id": "t013",
                        "color": "BLACK",
                        "name": "HOMMELESS TSHIRT BLACK",
                    },
                    "grey": {
                        "id": "t014",
                        "color": "GREY",
                        "name": "HOMMELESS TSHIRT GREY",
                    },
                    "ecru": {
                        "id": "t015",
                        "color": "ECRU",
                        "name": "HOMMELESS TSHIRT ECRU",
                    },
                },
            },
        },
    },
    
    "shirts": {
    "name": "Рубашки",
        "models": {
            "diamond_shirt": {
                "name": "DIAMOND SHIRT",
                "variants": {
                    "one": {
                        "id": "sh001",
                        "color": "ONE COLOR",
                        "name": "DIAMOND SHIRT",
                    },
                },
            },
        },
    },
    
    "pants": {
        "name": "Штаны / Джинсы",
        "models": {
            "culture_pants": {
                "name": "CULTURE PANTS",
                "variants": {
                    "grey": {
                        "id": "p001",
                        "color": "GREY",
                        "name": "CULTURE PANTS GREY",
                    },
                    "blue": {
                        "id": "p002",
                        "color": "BLUE",
                        "name": "CULTURE PANTS BLUE",
                    },
                    "black": {
                        "id": "p003",
                        "color": "BLACK",
                        "name": "CULTURE PANTS BLACK",
                    },
                },
            },
            "diamond_pants": {
                "name": "DIAMOND PANTS",
                "variants": {
                    "black": {
                        "id": "p004",
                        "color": "BLACK",
                        "name": "DIAMOND PANTS BLACK",
                    },
                    "melange": {
                        "id": "p005",
                        "color": "MELANGE",
                        "name": "DIAMOND PANTS MELANGE",
                    },
                    "pink": {
                        "id": "p006",
                        "color": "PINK",
                        "name": "DIAMOND PANTS PINK",
                    },
                },
            },
            "diamond_jeans": {
                "name": "DIAMOND JEANS",
                "variants": {
                    "one": {
                        "id": "p007",
                        "color": "ONE COLOR",
                        "name": "DIAMOND JEANS",
                    },
                },
            },
            "monogram_jeans": {
                "name": "MONOGRAM JEANS",
                "variants": {
                    "stone_black": {
                        "id": "p008",
                        "color": "STONE BLACK",
                        "name": "MONOGRAM JEANS STONE BLACK",
                    },
                    "washed_blue": {
                        "id": "p009",
                        "color": "WASHED BLUE",
                        "name": "MONOGRAM JEANS WASHED BLUE",
                    },
                    "sky_blue": {
                        "id": "p010",
                        "color": "SKY BLUE",
                        "name": "MONOGRAM JEANS SKY BLUE",
                    },
                },
            },
        },
    },

    "shorts": {
        "name": "Шорты",
        "models": {
            "apparel_shorts": {
                "name": "APPAREL SHORTS",
                "variants": {
                    "black": {
                        "id": "s001",
                        "color": "BLACK",
                        "name": "APPAREL SHORTS BLACK",
                    },
                    "melange": {
                        "id": "s002",
                        "color": "MELANGE",
                        "name": "APPAREL SHORTS MELANGE",
                    },
                },
            },
            "hm_shorts": {
                "name": "HM SHORTS",
                "variants": {
                    "black": {
                        "id": "s003",
                        "color": "BLACK",
                        "name": "HM SHORTS BLACK",
                    },
                    "melange": {
                        "id": "s004",
                        "color": "MELANGE",
                        "name": "HM SHORTS MELANGE",
                    },
                    "blue": {
                        "id": "s005",
                        "color": "BLUE",
                        "name": "HM SHORTS BLUE",
                    },
                },
            },
            "homme_shorts": {
                "name": "HOMME SHORTS",
                "variants": {
                    "black": {
                        "id": "s006",
                        "color": "BLACK",
                        "name": "HOMME SHORTS BLACK",
                    },
                    "melange": {
                        "id": "s007",
                        "color": "MELANGE",
                        "name": "HOMME SHORTS MELANGE",
                    },
                },
            },
        },
    },

    "bombers": {
        "name": "Бомберы",
        "models": {
            "base_bomber": {
                "name": "BASE BOMBER",
                "variants": {
                    "black": {
                        "id": "b001",
                        "color": "BLACK",
                        "name": "BASE BOMBER BLACK",
                    },
                    "grey": {
                        "id": "b002",
                        "color": "GREY",
                        "name": "BASE BOMBER GREY",
                    },
                },
            },
            "diamond_bomber": {
                "name": "DIAMOND BOMBER",
                "variants": {
                    "one": {
                        "id": "b003",
                        "color": "ONE COLOR",
                        "name": "DIAMOND BOMBER",
                    },
                },
            },
            "corset_bomber": {
                "name": "CORSET BOMBER",
                "variants": {
                    "one": {
                        "id": "b004",
                        "color": "ONE COLOR",
                        "name": "CORSET BOMBER",
                    },
                },
            },
        },
    },
    
    "belts": {
        "name": "Ремни",
        "models": {
            "og_belt": {
                "name": "OG BELT",
                "variants": {
                    "diamond": {
                        "id": "belt001",
                        "color": "DIAMOND",
                        "name": "DIAMOND OG BELT",
                    },
                    "base": {
                        "id": "belt002",
                        "color": "BASE",
                        "name": "BASE OG BELT",
                    },
                    "black": {
                        "id": "belt003",
                        "color": "BLACK",
                        "name": "BLACK OG BELT",
                    },
                    "pink": {
                        "id": "belt004",
                        "color": "PINK",
                        "name": "PINK OG BELT",
                    },
                    "white": {
                        "id": "belt005",
                        "color": "WHITE",
                        "name": "WHITE OG BELT",
                    },
                    "leo": {
                        "id": "belt005",
                        "color": "LEO",
                        "name": "LEO OG BELT",
                    },
                },
            },
        },
    },

    "vests": {
        "name": "Жилетки",
        "models": {
            "base_puffer_vest": {
                "name": "BASE PUFFER VEST",
                "variants": {
                    "black": {
                        "id": "v001",
                        "color": "BLACK",
                        "name": "BASE PUFFER VEST BLACK",
                    },
                },
            },
            "reversible_puffer_vest": {
                "name": "REVERSIBLE PUFFER VEST",
                "variants": {
                    "white": {
                        "id": "v002",
                        "color": "WHITE",
                        "name": "REVERSIBLE PUFFER VEST WHITE",
                    },
                    "red": {
                        "id": "v003",
                        "color": "RED",
                        "name": "REVERSIBLE PUFFER VEST RED",
                    },
                },
            },
            "carbon_puffer_vest": {
                "name": "CARBON PUFFER VEST",
                "variants": {
                    "black": {
                        "id": "v004",
                        "color": "BLACK",
                        "name": "CARBON BLACK PUFFER VEST",
                    },
                },
            },
            "diamond_puffer_vest": {
                "name": "DIAMOND PUFFER VEST",
                "variants": {
                    "one": {
                        "id": "v005",
                        "color": "ONE COLOR",
                        "name": "DIAMOND PUFFER VEST",
                    },
                },
            },
        },
    },

    "leather": {
        "name": "Кожанки",
        "models": {
            "homme_leather_jacket": {
                "name": "HOMME LEATHER JACKET",
                "variants": {
                    "black": {
                        "id": "l001",
                        "color": "BLACK",
                        "name": "HOMME LEATHER JACKET BLACK",
                    },
                    "grey": {
                        "id": "l002",
                        "color": "GREY",
                        "name": "HOMME LEATHER JACKET GREY",
                    },
                    "green": {
                        "id": "l003",
                        "color": "GREEN",
                        "name": "HOMME LEATHER JACKET GREEN",
                    },
                },
            },
        },
    },

    "bags": {
        "name": "Сумки",
        "models": {
            "million_dollar_birkin_bag": {
                "name": "MILLION DOLLAR BIRKIN BAG",
                "variants": {
                    "one": {
                        "id": "bag001",
                        "color": "ONE COLOR",
                        "name": "MILLION DOLLAR BIRKIN BAG",
                    },
                },
            },
            "homme_birkin_messenger_bag": {
                "name": "HOMME BIRKIN MESSENGER BAG",
                "variants": {
                    "one": {
                        "id": "bag002",
                        "color": "ONE COLOR",
                        "name": "HOMME BIRKIN MESSENGER BAG",
                    },
                },
            },
            "homme_birkin_shoulder_bag": {
                "name": "HOMME BIRKIN SHOULDER BAG",
                "variants": {
                    "one": {
                        "id": "bag003",
                        "color": "ONE COLOR",
                        "name": "HOMME BIRKIN SHOULDER BAG",
                    },
                },
            },
            "hm_messenger_bag": {
                "name": "HM MESSENGER BAG",
                "variants": {
                    "one": {
                        "id": "bag004",
                        "color": "ONE COLOR",
                        "name": "HM MESSENGER BAG",
                    },
                },
            },
        },
    },

    "accessories": {
        "name": "Аксессуары",
        "models": {
            "gift_card": {
                "name": "Подарочный сертификат",
                "variants": {
                    "5000": {
                        "id": "a001",
                        "color": "5000",
                        "name": "Подарочный сертификат 5000",
                    },
                },
            },
        },
    },
}


def _build_flat_products(category_data):
    products = {}

    for model_data in category_data["models"].values():
        for variant_data in model_data["variants"].values():
            products[variant_data["id"]] = variant_data["name"]

    return products


CATEGORIES = {}

for category_id, category_data in PRODUCT_CATALOG.items():
    CATEGORIES[category_id] = {
        "name": category_data["name"],
        "models": category_data["models"],
        "products": _build_flat_products(category_data),
    }


SIZES = ["2XS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "ONE SIZE"]


def get_product_name(category_id, product_id):
    return CATEGORIES[category_id]["products"][product_id]


def get_model_name(category_id, model_id):
    return CATEGORIES[category_id]["models"][model_id]["name"]


def get_variant_by_product_id(category_id, product_id):
    models = CATEGORIES[category_id]["models"]

    for model_id, model_data in models.items():
        for variant_key, variant_data in model_data["variants"].items():
            if variant_data["id"] == product_id:
                return model_id, variant_key, variant_data

    return None, None, None