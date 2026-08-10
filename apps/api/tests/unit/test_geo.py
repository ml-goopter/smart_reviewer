"""Distance and bounding boxes.

The box exists because Places `searchText` restricts to a rectangle and
rejects a circle, so the radius the operator asked for is only real if the
box encloses it and the haversine filter trims it back afterwards.
"""

from app.geo import bounding_box, haversine_m

def test_the_box_contains_the_circle_it_was_built_from():
    low_lat, low_lng, high_lat, high_lng = bounding_box(49.1745, -123.137, 5000)

    assert haversine_m(49.1745, -123.137, high_lat, -123.137) >= 5000
    assert haversine_m(49.1745, -123.137, low_lat, -123.137) >= 5000
    assert haversine_m(49.1745, -123.137, 49.1745, high_lng) >= 5000
    assert haversine_m(49.1745, -123.137, 49.1745, low_lng) >= 5000


def test_longitude_widens_towards_the_poles():
    """A degree of longitude is shorter near the pole, so the same radius needs
    a wider box."""
    _, equator_lng, _, _ = bounding_box(0.0, 0.0, 5000)
    _, arctic_lng, _, _ = bounding_box(80.0, 0.0, 5000)

    assert abs(arctic_lng) > abs(equator_lng)


def test_a_pole_does_not_divide_by_zero():
    low_lat, low_lng, high_lat, high_lng = bounding_box(90.0, 0.0, 5000)

    assert high_lat <= 90.0
    assert -180.0 <= low_lng <= high_lng <= 180.0
