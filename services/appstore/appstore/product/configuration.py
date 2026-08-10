from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProductColorScheme:
    """
    Per product hex colors
    """

    primary: str = "#00a8c1"
    secondary: str = "#d2cbcb"


@dataclass
class ProductLink:
    """
    Per product links
    """

    title: str
    link: str


@dataclass
class ProductSettings:
    """
    Per product application settings.

    Defaults to Common Share product settings.
    """

    links: Optional[List[ProductLink]]
    brand: str = "CommonsShare"
    title: str = "CommonsShare"
    logo_url: str = "/static/images/commonsshare/logo-lg.png"
    color_scheme: ProductColorScheme = field(default_factory=lambda: ProductColorScheme())
    capabilities: List[str] = field(default_factory=lambda: ['app', 'search'])

    def __post_init__(self):
        from appstore.settings.base import PRODUCT_LINKS
        if PRODUCT_LINKS:
            if self.links is None: self.links = []
            for link in PRODUCT_LINKS:
                self.links.append(ProductLink(link["name"], link["url"]))