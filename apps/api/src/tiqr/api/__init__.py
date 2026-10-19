"""HTTP API over the core service, serving the bundled web app."""

from importlib.metadata import version

# The installed distribution's version, which the packaging tests tie to the product version.
__version__ = version("tiqr-api")
