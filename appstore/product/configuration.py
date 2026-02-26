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
        from appstore.settings.base import GITEA_BASE_URL
        if GITEA_BASE_URL:
            if self.links is None: self.links = []
            self.links.append(ProductLink("Gitea", GITEA_BASE_URL))