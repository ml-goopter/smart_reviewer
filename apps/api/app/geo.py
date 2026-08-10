"""Distance on a sphere.

Google returns coordinates, never distances, so the result list's distance
column is computed here from the resolved search centre.
"""

from math import asin, cos, degrees, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000


def bounding_box(
    lat: float, lng: float, radius_m: int
) -> tuple[float, float, float, float]:
    """The smallest lat/lng rectangle containing a circle: (low_lat, low_lng,
    high_lat, high_lng).

    Places `searchText` takes a *rectangle* for locationRestriction and rejects
    a circle outright — circles belong to searchNearby and to locationBias. A
    bias would only nudge the ranking, so a hard rectangle is the closest thing
    to a radius the API offers; its corners reach about 1.41x the radius, and
    the exact circle is enforced afterwards with haversine.
    """
    d_lat = degrees(radius_m / EARTH_RADIUS_M)

    # Longitude degrees shrink towards the poles. cos() is floored so a search
    # near a pole widens the box instead of dividing by zero.
    shrink = max(cos(radians(lat)), 1e-6)
    d_lng = degrees(radius_m / (EARTH_RADIUS_M * shrink))

    # Longitude is clamped, never wrapped: a box straddling the antimeridian is
    # truncated rather than split. Places expresses that case as
    # low.longitude > high.longitude, which this deliberately does not build.
    return (
        max(lat - d_lat, -90.0),
        max(lng - d_lng, -180.0),
        min(lat + d_lat, 90.0),
        min(lng + d_lng, 180.0),
    )


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Great-circle distance in whole metres.

    Whole metres because the figure is rendered as "1.2 km" — sub-metre
    precision on a point Google itself rounds would be false confidence.
    """
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    d_lat = lat2_r - lat1_r
    d_lng = radians(lng2) - radians(lng1)

    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lng / 2) ** 2
    return round(2 * EARTH_RADIUS_M * asin(sqrt(a)))
