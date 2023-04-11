"""
Data from database and OpenStreetMap collection logic is defined here.
"""
from typing import TextIO

import geopandas as gpd
import osm2geojson
import pandas as pd
import requests
from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import Connection


def collect_plants(connection: Connection) -> pd.DataFrame:
    """Get plants dataframe from database."""

    plants = pd.read_sql(
        text(
            """
        SELECT plants.id, plant_types.name AS plant_type, name_ru, name_latin,
            spread_aggressiveness_level AS aggressiveness, survivability_level AS survivability,
            is_invasive, genus_id
        FROM plants
            JOIN plant_types ON plants.type_id = plant_types.id
        WHERE genus_id IS NOT NULL
        """
        ),
        con=connection,
    )

    return plants


def collect_plants_with_limitation_resistance(connection: Connection) -> pd.DataFrame:
    """Get plants with limitation factors dataframe from database."""

    plants_with_limitations_resistance = pd.read_sql(
        text(
            """
        SELECT p.id, pt.name AS plant_type, p.name_ru, p.name_latin,
            p.spread_aggressiveness_level AS aggressiveness, p.survivability_level AS survivability,
            p.is_invasive, p.genus_id, plf.limitation_factor_id, lf.name
        FROM plants p
            JOIN plant_types pt ON p.type_id = pt.id
            JOIN plants_limitation_factors plf ON plf.plant_id = p.id
            JOIN limitation_factors lf ON lf.id = plf.limitation_factor_id
        WHERE plf.is_stable = true
        """
        ),
        con=connection,
    )

    return plants_with_limitations_resistance


def collect_plants_suitable_for_light(connection: Connection) -> pd.DataFrame:
    """Get plants with suitable light types dataframe from database."""

    plants_suitable_for_light = pd.read_sql(
        text(
            """
        SELECT p.id, pt.name AS plant_type, p.name_ru, p.name_latin,
            p.spread_aggressiveness_level AS aggressiveness, p.survivability_level AS survivability,
            p.is_invasive, p.genus_id, plt.light_type_id, lt.name
        FROM plants p
            JOIN plant_types pt ON p.type_id = pt.id
            JOIN plants_light_types plt ON plt.plant_id = p.id
            JOIN light_types lt ON lt.id = plt.light_type_id
        WHERE plt.is_stable = true
        """
        ),
        con=connection,
    )

    return plants_suitable_for_light


def collect_cohabitations(connection: Connection) -> pd.DataFrame:
    """Get genera cohabitation dataframe from database."""

    cohabitation_attributes = pd.read_sql(text("SELECT * FROM cohabitation"), con=connection)

    return cohabitation_attributes


def collect_limitation_polygons(connection: Connection) -> gpd.GeoDataFrame:
    """Get GeoDataFrame with limitation polygons from database."""

    limitations = pd.read_sql(
        text(
            """
        SELECT id, limitation_factor_id, ST_AsText(geometry) as geometry
        FROM limitation_factor_parts
        """
        ),
        con=connection,
    )
    limitations["geometry"] = gpd.GeoSeries.from_wkt(limitations["geometry"])
    limitations = gpd.GeoDataFrame(limitations, geometry="geometry").set_crs(4326)

    return limitations


def collect_light_polygons(connection: Connection) -> gpd.GeoDataFrame:
    """Get GeoDataFrame with light polygons from database."""

    light = pd.read_sql(
        text(
            """
        SELECT id, light_type_id, ST_AsText(geometry) as geometry
        FROM light_type_parts
        """
        ),
        con=connection,
    )
    light["geometry"] = gpd.GeoSeries.from_wkt(light["geometry"])
    light = gpd.GeoDataFrame(light, geometry="geometry").set_crs(4326)

    return light


def collect_parks(path_to_green_areas_geojson: str | TextIO, target_parks: list[str] | None = None) -> gpd.GeoDataFrame:
    """
    Get dataframe of parks (green areas) read from file by name or a file-like object.

    Will be replaced with citygeotools integration in future verions.
    """
    parks = gpd.read_file(path_to_green_areas_geojson)
    if target_parks is not None:
        parks = parks[parks["service_name"].isin(target_parks)]
    return parks


def collect_species_in_parks(connection: Connection) -> pd.DataFrame:
    """Get plants in parks dataframe from database."""

    species_in_parks = pd.read_sql(
        text(
            """
        SELECT plants.id, name_ru, name as park_name
        FROM plants
            JOIN plants_parks ON plants.id = plants_parks.plant_id
            JOIN parks ON plants_parks.park_id = parks.id
        """
        ),
        con=connection,
    )
    return species_in_parks


def collect_smoke_area_from_osm(
    city: str,
    city_crs: int,
    overpass_url: str = "http://overpass-api.de/api/interpreter",
    upper_limit=40,
    lower_limit=10,
) -> gpd.GeoDataFrame:
    """_summary_

    Args:
        city (str): City name
        city_crs (int): City local coordinate system for correct buffer results in meters
        overpass_url (_type_, optional): URL to overpass-API whichsuits user the best.
        Defaults to "http://overpass-api.de/api/interpreter".
        upper_limit (int, optional): Number to multiply chimney height to create an outer buffer. Defaults to 40.
        lower_limit (int, optional): Number to multiply chinmey height to create an inner buffer. Defaults to 10.

    Returns:
        gpd.GeoDataFrame: _description_
    """

    overpass_query = f"""
    [out:json];
            area['name'='{city}']->.searchArea;
            (
                node["man_made"="chimney"](area.searchArea);
                way["man_made"="chimney"](area.searchArea);
                relation["man_made"="chimney"](area.searchArea);
            );
    out geom;
    """
    logger.debug("Performing overpass request for chimneys data")
    result = requests.get(overpass_url, params={"data": overpass_query}).json()  # pylint: disable=missing-timeout
    gdf = osm2geojson.json2geojson(result)
    gdf = gpd.GeoDataFrame.from_features(gdf["features"]).set_crs(4326).to_crs(city_crs)
    gdf = gdf[["geometry", "id", "tags"]]
    gdf.loc[gdf["geometry"].geom_type != "Point", "geometry"] = gdf["geometry"].centroid
    gdf = gdf.join(pd.json_normalize(gdf.tags)["height"]).drop(columns=["tags"])
    gdf["height"] = (
        gdf.height.fillna("10").map(lambda x: [char for char in x.split(" ") if char.isdigit()][0]).astype(int)
    )

    max_area = gdf.buffer(gdf.height * upper_limit)
    min_area = gdf.buffer(gdf.height * lower_limit)
    gdf["geometry"] = max_area.difference(min_area).to_crs(4326)
    logger.debug("Got {} chimneys polygons", gdf.shape[0])

    return gdf
