"""درخت دسته‌ها. عنوان‌هایی که مدیر بعداً اضافه کند پاک نمی‌شوند."""


def node(name, slug, children=(), roles=()):
    return {"name": name, "slug": slug, "children": children, "roles": roles}


TREE = [
    node(
        "تعمیرات آی‌تی",
        "it",
        children=[
            node(
                "تعمیر لپ‌تاپ",
                "laptop",
                roles=[
                    ("تعمیر لپ‌تاپ", "laptop-repair"),
                    ("تعویض ال‌سی‌دی لپ‌تاپ", "laptop-lcd"),
                    ("تعمیر مادربرد لپ‌تاپ", "laptop-board"),
                    ("ارتقای لپ‌تاپ", "laptop-upgrade"),
                ],
            ),
            node(
                "تعمیر آل‌این‌وان",
                "aio",
                roles=[
                    ("تعمیر آل‌این‌وان", "aio-repair"),
                    ("تعویض پنل آل‌این‌وان", "aio-panel"),
                    ("ارتقای آل‌این‌وان", "aio-upgrade"),
                ],
            ),
            node(
                "تعمیر مانیتور",
                "monitor",
                roles=[
                    ("تعمیر مانیتور", "monitor-repair"),
                    ("تعمیر بک‌لایت", "monitor-backlight"),
                    ("تعمیر برد مانیتور", "monitor-board"),
                ],
            ),
            node(
                "تعمیر کامپیوتر",
                "pc",
                roles=[
                    ("تعمیر کامپیوتر", "pc-repair"),
                    ("اسمبل و ارتقا", "pc-build"),
                    ("نصب ویندوز و نرم‌افزار", "pc-software"),
                    ("شبکه و اینترنت", "pc-network"),
                ],
            ),
        ],
    ),
    node(
        "آموزش",
        "training",
        roles=[
            ("آموزش سخت‌افزار", "train-hardware"),
            ("آموزش تعمیرات", "train-repair"),
            ("آموزش شبکه", "train-network"),
            ("آموزش نرم‌افزار", "train-software"),
        ],
    ),
    node(
        "ماشین‌های اداری",
        "office",
        roles=[
            ("تعمیر پرینتر", "printer"),
            ("تعمیر اسکنر", "scanner"),
            ("تعمیر دستگاه کپی", "copier"),
            ("تعمیر فکس", "fax"),
            ("شارژ کارتریج", "cartridge"),
        ],
    ),
]


def seed_catalog():
    from talent.models import Category, Role

    def walk(nodes, parent):
        for order, item in enumerate(nodes):
            category, _ = Category.objects.update_or_create(
                slug=item["slug"],
                defaults={"name": item["name"], "order": order, "parent": parent},
            )
            for role_name, role_slug in item["roles"]:
                Role.objects.update_or_create(
                    slug=role_slug,
                    defaults={"name": role_name, "category": category},
                )
            walk(item["children"], category)

    walk(TREE, None)
