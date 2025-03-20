# src/shinylims/data/brand_utils.py
import yaml
from pathlib import Path

def load_brand_config():
    """Load brand configuration from YAML file."""
    brand_path = Path(__file__).parent.parent / "assets" / "brand.yml"
    
    try:
        with open(brand_path, "r") as file:
            brand = yaml.safe_load(file)
            # Process color palette to expand references
            processed_brand = process_brand_colors(brand)
            return processed_brand
    except Exception as e:
        print(f"Error loading brand config: {e}")
        return DEFAULT_BRAND


def process_brand_colors(brand):
    """Process color references in the brand configuration."""
    # Create a copy to avoid modifying the original
    processed = brand.copy()
    
    # Get the color palette
    palette = brand.get('color', {}).get('palette', {})
    
    # Replace color references with actual hex values
    for key, value in brand.get('color', {}).items():
        if key != 'palette' and isinstance(value, str) and value in palette:
            processed['color'][key] = palette[value]
    
    return processed


def generate_comprehensive_brand_css(brand):
    """Generate comprehensive CSS overrides based on brand configuration."""
    return f"""
    /* Base styles */
    body {{
        font-family: '{brand['typography']['base']['family']}';
        font-weight: {brand['typography']['base']['weight']};
        font-size: {brand['typography']['base']['size']};
        line-height: {brand['typography']['base']['line-height']};
        color: {brand['color']['foreground']};
        background-color: {brand['color']['background']};
    }}
    
    /* Typography */
    h1, h2, h3, h4, h5, h6 {{
        font-family: '{brand['typography']['headings']['family']}';
        font-weight: {brand['typography']['headings']['weight']};
        color: {brand['color']['primary']};
        margin-bottom: 1.5rem;
    }}
    
    a {{
        color: {brand['color']['primary']};
        font-weight: {brand['typography']['link']['weight']};
        text-decoration: {brand['typography']['link']['decoration']};
    }}
    
    /* App title */
    .navbar-brand {{
        font-size: 1.15rem !important;
        font-weight: 600 !important;
    }}
    
    /* Navigation tabs */
    .nav-link {{
        font-size: 1.6rem !important;
        font-weight: 500 !important;
        display: flex;
        align-items: center;
        height: 100%;
    }}
    
    /* Active tab */
    .nav-link.active {{
        font-size: 2.2rem !important;
        font-weight: 600 !important;
        color: {brand['color']['primary']} !important;
        border-bottom: 3px solid {brand['color']['primary']} !important;
    }}
    
    /* Bootstrap overrides */
    .navbar.navbar-default {{
        background-color: {brand['color']['palette']['dark_air']} !important;
        background: {brand['color']['palette']['dark_air']} !important;
    }}
    
    .navbar-light .navbar-nav .nav-link {{
        color: {brand['color']['foreground']};
    }}
    
    .navbar-light .navbar-nav .nav-link:hover {{
        color: {brand['color']['primary']};
    }}
    
    /* Button styling - using brand colors */
    .btn-primary {{
        background-color: {brand['color']['primary']};
        border-color: {brand['color']['primary']};
    }}
    
    .btn-primary:hover {{
        background-color: {brand['color']['primary']};
        filter: brightness(1.1);
    }}
    
    /* Change refresh button to use primary color instead of success */
    .btn-success {{
        background-color: {brand['color']['primary']};
        border-color: {brand['color']['primary']};
    }}
    
    .btn-success:hover {{
        background-color: {brand['color']['primary']};
        filter: brightness(1.1);
    }}
    
    /* Table styles */
    .dataTable thead th, .reactable-header {{
        background-color: {brand['color']['palette']['air']};
        color: {brand['color']['foreground']};
        border-bottom-color: {brand['color']['primary']};
        font-weight: 600;
        font-size: 1.05rem;
    }}
    
    .dataTable tbody tr:nth-child(even), .reactable-data tr:nth-child(even) {{
        background-color: rgba({', '.join(str(int(h[1:3], 16)) for h in [brand['color']['palette']['air'][:7]])}, 0.3);
    }}
    
    .dataTable tbody tr:hover, .reactable-data tr:hover {{
        background-color: {brand['color']['palette']['light_water']};
    }}
    
    /* Card styles */
    .card {{
        border-color: {brand['color']['palette']['light_water']};
    }}
    
    .card-header {{
        background-color: {brand['color']['palette']['air']};
        color: {brand['color']['foreground']};
        font-weight: 600;
    }}
    
    /* Accordion styles */
    .accordion-button:not(.collapsed) {{
        background-color: {brand['color']['palette']['air']};
        color: {brand['color']['foreground']};
    }}
    
    /* Any custom Bootstrap rules from brand.yml */
    {brand['defaults']['bootstrap'].get('rules', '')}
    """

def get_logo_path(brand, logo_name="english"):
    """Get the path to a specific logo file from the brand config."""
    try:
        # Get the logo filename from the images dictionary
        logo_filename = brand["logo"]["images"][logo_name]
        
        # Replace 'logos/' with 'assets/' in the path
        logo_filename = logo_filename.replace("logos/", "assets/")
        
        # Return the modified path
        return f"/{logo_filename}"
    except KeyError:
        # Fallback to a default
        return "/assets/vetinst-logo.png"


# Default brand configuration in case loading fails
DEFAULT_BRAND = {
    "color": {
        "palette": {
            "black": "#091A3E",
            "white": "#F7FDFF",
            "air": "#D7F4FF",
            "water": "#1C4FB9",
            "earth": "#59CD88",
            "light_water": "#C7D9FF",
            "dark_food": "#FF5447"
        },
        "primary": "#1C4FB9",
        "background": "#F7FDFF",
        "foreground": "#091A3E"
    },
    "typography": {
        "base": {
            "family": "Hanken Grotesk, sans-serif",
            "weight": 400,
            "size": "16px",
            "line-height": 1.5
        },
        "headings": {
            "family": "Hanken Grotesk, sans-serif",
            "weight": 600,
            "style": "normal"
        },
        "link": {
            "weight": 600,
            "decoration": "underline"
        }
    },
    "defaults": {
        "bootstrap": {
            "rules": ""
        }
    }
}