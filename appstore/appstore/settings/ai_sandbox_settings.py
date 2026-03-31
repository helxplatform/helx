from .base import *
from product.configuration import ProductSettings, ProductColorScheme

APPLICATION_BRAND = "ai_sandbox"

PRODUCT_SETTINGS = ProductSettings(
    brand="ai_sandbox",
    title="RENCI AI Sandbox",
    logo_url="/static/images/helx/logo.png",
    color_scheme=ProductColorScheme("#192d3f", "#06667d"),
    links=[],
)
