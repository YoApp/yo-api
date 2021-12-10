from collections import namedtuple
from haversine import haversine


# While we automatically add a visitor's country code to the store query, we
# do not trust any geo lookup package to correctly/predictably labeling
# cities. The next best thing is to define a city by its coordinates and
# compare distances. TODO: The data source for this should be MongoDB.
from yoapi.core import cache
from yoapi.models.region import Region

LocalizedCity = namedtuple('LocalizedCity', ['point', 'radius'])

AUSTIN_COORDINATES = (30.2500, -97.7500)
AUSTIN_RADIUS = 20

PENSTATE_COORDINATES = (40.7982133, -77.8599084)
PENSTATE_RADIUS = 50

TEL_AVIV_COORDINATES = (32.0878802, 34.797246)
TELAVIV_RADIUS = 50

SF_COORDINATES = (37.7833, -122.4167)
SF_RADIUS = 50

UF_COOR = (29.6436325, -82.3549302)
RADIUS = 50

UW_COOR = (43.076592, -89.4124875)

LOCALIZED_CITIES = {
    'Austin': LocalizedCity(AUSTIN_COORDINATES, AUSTIN_RADIUS),
    'State College': LocalizedCity(PENSTATE_COORDINATES, PENSTATE_RADIUS),
    'Tel Aviv': LocalizedCity(TEL_AVIV_COORDINATES, TELAVIV_RADIUS),
    'San Francisco': LocalizedCity(SF_COORDINATES, RADIUS),
    'UF': LocalizedCity(UF_COOR, RADIUS),
    'UW': LocalizedCity(UW_COOR, RADIUS)
    }


@cache.memoize()
def get_regions():
    return Region.objects.all()


@cache.memoize()
def get_region_by_name(name):
    return Region.objects.get(name=name)


def get_region(coordinates):
    """Looks up localized city by request IP"""

    # If we can't determine the coordinates associated with the request then
    # we simply return nothing.
    if not coordinates:
        return None

    # In the future, this should probably use the result of a geopoint query
    # to mongodb.
    regions = get_regions()
    for region in regions:
        point = (region.latitude, region.longitude)
        distance = haversine(coordinates,
                             point,
                             miles=True)
        if distance <= region.radius:
            return region.name
