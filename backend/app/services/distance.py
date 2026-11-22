import math

from sqlalchemy import case, func

EARTH_RADIUS_KM = 6371.0088


def haversine_distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(haversine))


def database_distance_km(latitude_column, longitude_column, latitude, longitude):
    latitude_delta = func.radians(latitude_column - latitude)
    longitude_delta = func.radians(longitude_column - longitude)
    haversine = (
        func.pow(func.sin(latitude_delta / 2), 2)
        + func.cos(func.radians(latitude_column))
        * func.cos(func.radians(latitude))
        * func.pow(func.sin(longitude_delta / 2), 2)
    )
    bounded_haversine = case(
        (haversine <= 0, 0.0),
        (haversine >= 1, 1.0),
        else_=haversine,
    )
    return (
        2
        * EARTH_RADIUS_KM
        * func.asin(func.sqrt(bounded_haversine))
    )
