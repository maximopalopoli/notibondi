"""The richer line map: text checks on route_layers.js, basemap.js and the CSS.

There's no JS test runner, so like the other map tests these check that the
pieces are there; the browser check is by hand (screenshots in the PR).
"""

import re

from notibondi.main import BASE_DIR

STATIC = BASE_DIR / "static"
ROUTE_LAYERS = (STATIC / "route_layers.js").read_text()
BASEMAP = (STATIC / "basemap.js").read_text()
CSS = (STATIC / "style.css").read_text()

# Every layer the direction filter touches
FILTERED = [
    "lines-casing",
    "lines",
    "arrows",
    "route-stops",
    "vehicles-unknown-branch",
    "vehicles",
]


def layer_ids(js):
    return re.findall(r'id: "([\w-]+)"', js)


# The white border and the side of the street


def test_the_white_border_is_drawn_under_the_lines():
    ids = layer_ids(ROUTE_LAYERS)

    assert ids.index("lines-casing") < ids.index("lines")
    assert '"line-color": "#ffffff"' in ROUTE_LAYERS


def test_border_and_line_move_to_the_same_side():
    # If only the line moved, its border would stay in the middle of the street
    assert ROUTE_LAYERS.count('"line-offset": OFFSET') == 2


def test_the_arrows_follow_their_line():
    assert '"icon-offset": ARROW_OFFSET' in ROUTE_LAYERS


# The direction filter and its legend


def test_every_layer_has_a_base_filter_to_go_back_to():
    block = ROUTE_LAYERS[ROUTE_LAYERS.index("const BASE_FILTERS") :]
    block = block[: block.index("};")]

    for layer in FILTERED:
        assert f'"{layer}":' in block or f"  {layer}:" in block


def test_the_layers_take_their_filter_from_base_filters():
    # Not a second copy that could drift from the one showDirection() uses
    for layer in FILTERED:
        key = f'BASE_FILTERS["{layer}"]' if "-" in layer else f"BASE_FILTERS.{layer}"
        assert f"filter: {key}" in ROUTE_LAYERS


def test_a_new_branch_resets_the_legend():
    show = ROUTE_LAYERS[ROUTE_LAYERS.index("function showLegend") :]

    assert "showDirection(map, null)" in show
    assert 'button("Ambos", "all", true)' in show


def test_the_legend_never_puts_the_headsign_in_html():
    # The headsign comes from the GTFS: text, not markup
    assert "innerHTML" not in ROUTE_LAYERS
    assert "createTextNode(label)" in ROUTE_LAYERS


def test_the_legend_buttons_say_which_one_is_on():
    assert 'setAttribute("aria-pressed"' in ROUTE_LAYERS
    assert '.directions button[aria-pressed="true"]' in CSS


def test_the_legend_buttons_are_big_enough_for_a_finger():
    rule = CSS[CSS.index(".directions button {") :]

    assert "min-height: 2.75rem" in rule[: rule.index("}")]


# The quieter base map


def test_the_base_map_is_quieter_than_light():
    assert "...QUIET" in BASEMAP
    assert re.search(r'water: "#[0-9a-f]{6}"', BASEMAP)


def test_shops_and_cafes_wait_for_street_zoom_but_stations_dont():
    assert '["==", ["get", "kind"], "station"]' in BASEMAP
    assert '[">=", ["zoom"], 16]' in BASEMAP
