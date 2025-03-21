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
    # Helper function to convert hex to RGB components
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return f"{int(hex_color[0:2], 16)}, {int(hex_color[2:4], 16)}, {int(hex_color[4:6], 16)}"
    
    # Get RGB values for the air color
    air_color = brand['color']['palette']['air'][:7]  # Get the hex part
    air_rgb = hex_to_rgb(air_color)
    
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
    
    /* Card title additional spacing */
    h2.card-title {{
        margin-bottom: 3rem;
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
        font-size: 2rem !important;
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
    
    /* Table cell padding */
    .reactable-data td, .dataTable td {{
        padding: 8px 10px;
    }}
    
    /* Alternating row colors for all table types */
    .dataTable tbody tr:nth-child(even), 
    .reactable-data tr:nth-child(even),
    .rt-tr:nth-child(even) {{
        background-color: rgba({air_rgb}, 0.3);
    }}
    
    /* Hover effects for all table types with transition */
    .dataTable tbody tr:hover, 
    .reactable-data tr:hover,
    .rt-tr:hover,
    .datatable tbody tr:hover {{
        background-color: {brand['color']['palette']['light_water']};
        transition: background-color 0.2s ease;
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
    
    /* Responsive scaling rules */
    @media (min-width: 992px) {{
        body {{
            transform: scale(0.8);
            transform-origin: top left;
            width: 125%;
            height: 125%;
            position: absolute;
        }}
    }}
    
    @media (max-width: 991px) {{
        body {{
            transform: scale(0.7);
            transform-origin: top left;
            width: 142.85%;
            height: 142.85%;
            position: absolute;
        }}
        
        html {{
            font-size: 18px;
        }}
        
        .nav-link {{
            font-size: 1.3rem !important;
        }}
        
        .nav-link.active {{
            font-size: 1.6rem !important;
        }}
        
        .shiny-input-container {{
            width: 100% !important;
        }}
        
        .dataTables_wrapper, .reactable {{
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            width: 100% !important;
        }}
        
        .dataTables_wrapper td, .reactable-data td {{
            padding: 10px 6px;
            word-break: break-word;
        }}
        
        .btn {{
            padding: 12px 16px;
            margin: 6px;
            min-height: 44px;
            min-width: 44px;
        }}
        
        /* Fix for table filters on mobile */
        .dataTables_filter {{
            width: 100%;
            text-align: left;
            margin-bottom: 10px;
        }}
        
        .dataTables_filter input {{
            width: calc(100% - 70px);
        }}
    }}
    
    @media (max-width: 400px) {{
        body {{
            transform: scale(0.6);
            width: 166.67%;
            height: 166.67%;
        }}
        
        html {{
            font-size: 20px;
        }}
        
        .nav-link {{
            font-size: 1.2rem !important;
        }}
        
        .nav-link.active {{
            font-size: 1.4rem !important;
        }}
    }}
    """


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