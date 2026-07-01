"""Parse ThoughtSpot Model + Table TML into the ERD MODEL schema."""
import yaml


def load_tml(path):
    """Load a TML (YAML) file into a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
