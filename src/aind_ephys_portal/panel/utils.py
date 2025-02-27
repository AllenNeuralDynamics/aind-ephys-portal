import panel as pn


EPHYSGUI_LINK_PREFIX = "/ephys_gui_app?analyzer_path={}&recording_path={}"


AIND_COLORS = colors = {
    "dark_blue": "#003057",
    "light_blue": "#2A7DE1",
    "green": "#1D8649",
    "yellow": "#FFB71B",
    "grey": "#7C7C7F",
    "red": "#FF5733",
}

OUTER_STYLE = {
    "background": "#ffffff",
    "border-radius": "5px",
    "border": "2px solid black",
    "padding": "10px",
    "box-shadow": "5px 5px 5px #bcbcbc",
    "margin": "5px",
}


def format_link(link: str, text: str = "link"):
    """Format link as an HTML anchor tag

    Parameters
    ----------
    link : str
    text : str, optional
        by default "link"
    """
    return f'<a href="{link}" target="_blank">{text}</a>'


def format_css_background():
    """Add the custom CSS for the background to the panel configuration"""
    # Add the custom CSS
    background_color = AIND_COLORS[
        (
            pn.state.location.query_params["background"]
            if "background" in pn.state.location.query_params
            else "dark_blue"
        )
    ]
    BACKGROUND_CSS = f"""
    body {{
        background-color: {background_color} !important;
        background-image: url('/images/aind-pattern.svg') !important;
        background-size: 1200px;
    }}
    """
    pn.config.raw_css.append(BACKGROUND_CSS)  # type: ignore