# src/shinylims/data/brand_utils.py
import yaml
from pathlib import Path

def load_brand_config():
    """Load brand configuration from YAML file."""
    brand_path = Path(__file__).parent.parent / "assets" / "brand.yml"
    
    try:
        with open(brand_path, "r") as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Error loading brand config: {e}")
        # Return default values if the file can't be loaded
        return {
            "colors": {
                "primary": "#0056b3",
                "secondary": "#6c757d",
                # Add other default values
            }
        }