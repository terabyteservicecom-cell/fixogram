from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1, lon1, lat2, lon2):
    earth_km = 6371.0
    lat1, lon1, lat2, lon2 = (radians(float(value)) for value in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    arc = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * earth_km * asin(sqrt(arc))
