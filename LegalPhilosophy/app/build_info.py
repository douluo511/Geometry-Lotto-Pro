VERSION = "0.1.0"
PRODUCT = "LegalPhilosophy"

try:
    from ._generated_build import SOURCE_SHA
except ImportError:
    SOURCE_SHA = "DEVELOPMENT"
