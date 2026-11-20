"""The "Seleccioná la línea" list on the lines page."""

from sqlalchemy import text

from notibondi.routes import line_groups

# The mini GTFS has 15A, 152A, 152B and 505R3


def test_groups_the_line_numbers_by_hundreds(conn):
    assert line_groups(conn) == [
        ("1 a 99", ["15"]),
        # 152A and 152B are one number: picking it lists both branches
        ("100 a 199", ["152"]),
        ("500 a 599", ["505"]),
    ]


def test_numbers_are_sorted_as_numbers_not_as_text(conn):
    add_routes(conn, "9", "100", "99B")

    groups = dict(line_groups(conn))

    # As text, "15" would come before "9"
    assert groups["1 a 99"] == ["9", "15", "99"]
    assert groups["100 a 199"] == ["100", "152"]


def test_lines_without_a_number_go_last_in_otras(conn):
    add_routes(conn, "VERDE", "AZUL1", "AZUL1")

    assert line_groups(conn)[-1] == ("Otras", ["AZUL1", "VERDE"])


def test_a_name_the_search_cant_take_is_left_out(conn):
    # The search only takes letters and digits, so R333/9 would list nothing
    add_routes(conn, "R333/9")

    assert "Otras" not in dict(line_groups(conn))


def add_routes(conn, *names):
    """Only inside this test's transaction: the conn fixture never commits."""
    for i, name in enumerate(names):
        conn.execute(
            text(
                "INSERT INTO routes (route_id, route_short_name, route_desc) "
                "VALUES (:id, :name, '')"
            ),
            {"id": f"test-{i}", "name": name},
        )


# The page


def test_the_lines_page_has_the_select_grouped_by_hundreds(client):
    html = client.get("/routes").text

    assert '<label for="line-select">Seleccioná la línea</label>' in html
    assert 'hx-get="/partials/routes/search"' in html
    # Picking a range ("range:1") or going back ("back:") loads nothing
    assert "hx-trigger=\"change[this.value && !this.value.includes(':')]\"" in html
    assert "/static/line_select.js" in html
    assert '<optgroup label="100 a 199">' in html
    assert "<option>152</option>" in html


def test_the_lines_page_has_only_the_select(client):
    # The two-step select is enough: no text box next to it
    html = client.get("/routes").text

    assert "O escribí el número" not in html
    assert 'id="search"' not in html


def test_picking_a_number_lists_all_its_branches(client):
    # What the select sends: just the number
    html = client.get("/partials/routes/search", params={"q": "152"}).text

    assert "152A" in html
    assert "152B" in html


# Picking a branch draws it on the map of the same page


def test_each_branch_says_its_route_id_for_the_map(client):
    html = client.get("/partials/routes/search", params={"q": "152"}).text

    # The href stays: a middle click still opens the line's own page
    assert '<a data-route-id="1001" href="/routes/1001">152A</a>' in html


def test_the_lines_page_can_draw_a_branch(client):
    html = client.get("/routes").text

    # Deferred scripts run in order: lines_map.js uses RouteLayers
    assert html.index("/static/route_layers.js") < html.index("/static/lines_map.js")
    assert '<p id="no-live" hidden>' in html
    assert '<p id="unknown-branch" hidden>' in html
