import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import requests
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon

from app.core.config import settings

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

_cache: Dict[str, Any] = {
    "streets_gdf": None,
    "points_gdf": None,
    "streets_ix": None,
    "last_updated": None,
}

def meters_to_degrees_lat(m: float) -> float:
    return m / 111_320.0

def meters_to_degrees_lon(m: float, lat_deg: float) -> float:
    return m / (111_320.0 * math.cos(math.radians(lat_deg)))

def build_grid(bbox, spacing_m=250) -> gpd.GeoDataFrame:
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_center = (min_lat + max_lat) / 2
    dlat = meters_to_degrees_lat(spacing_m)
    dlon = meters_to_degrees_lon(spacing_m, lat_center)
    pts = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            pts.append(Point(lon, lat))
            lon += dlon
        lat += dlat
    return gpd.GeoDataFrame({"id": list(range(len(pts)))}, geometry=pts, crs="EPSG:4326")

def fetch_osm(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    query = f"""
    [out:json][timeout:120];
    (
      way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
      way["amenity"="parking"]({min_lat},{min_lon},{max_lat},{max_lon});
      relation["amenity"="parking"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    (._;>;);
    out body;
    """
    r = requests.post(OVERPASS_URL, data=query, timeout=60)
    r.raise_for_status()
    data = r.json()
    nodes = {el["id"]: (el["lon"], el["lat"]) for el in data["elements"] if el["type"] == "node"}

    ways = [el for el in data["elements"] if el["type"] == "way"]
    lines, parks = [], []
    for w in ways:
        coords = [nodes[nid] for nid in w.get("nodes", []) if nid in nodes]
        if not coords:
            continue
        tags = w.get("tags", {})
        if "highway" in tags and len(coords) >= 2:
            lines.append({"osm_id": w["id"], "name": tags.get("name"), "highway": tags.get("highway"),
                          "geometry": LineString(coords)})
        if tags.get("amenity") == "parking":
            geom = Polygon(coords) if (len(coords) >= 4 and coords[0] == coords[-1]) else LineString(coords)
            parks.append({"osm_id": w["id"], "name": tags.get("name"), "geometry": geom})

    streets_gdf = gpd.GeoDataFrame(lines, crs="EPSG:4326")
    parking_gdf = gpd.GeoDataFrame(parks, crs="EPSG:4326")
    return streets_gdf, parking_gdf

def tomtom_ratio(lat: float, lon: float, api_key: str) -> Optional[float]:
    params = {"key": api_key, "point": f"{lat},{lon}"}
    r = requests.get(TOMTOM_FLOW_URL, params=params, timeout=10)
    if r.status_code != 200:
        return None
    try:
        js = r.json()
        flow = js["flowSegmentData"]
        return max(0.0, min(1.5, flow["currentSpeed"] / max(1.0, flow["freeFlowSpeed"])))
    except Exception:
        return None

def sample_ratios(grid_gdf: gpd.GeoDataFrame, api_key: str, max_calls=300, sleep_between=0.15):
    ratios = []
    calls = 0
    for _, row in grid_gdf.iterrows():
        if calls >= max_calls:
            ratios.append(None)
            continue
        lat, lon = row.geometry.y, row.geometry.x
        ratios.append(tomtom_ratio(lat, lon, api_key))
        calls += 1
        time.sleep(sleep_between)
    out = grid_gdf.copy()
    out["traffic_ratio"] = ratios
    return out

def compute_parking_index(streets_gdf: gpd.GeoDataFrame, pts_gdf: gpd.GeoDataFrame):
    if streets_gdf.empty or pts_gdf.empty:
        s = streets_gdf.copy()
        s["parking_index"] = None
        return s
    streets = streets_gdf.to_crs(3857)
    pts = pts_gdf.to_crs(3857)
    streets["buf"] = streets.geometry.buffer(20)
    joined = gpd.sjoin(pts, streets.set_geometry("buf"), predicate="within", how="left")
    stats = joined.groupby("index_right")["traffic_ratio"].mean().rename("mean_ratio")
    streets["mean_ratio"] = streets.index.map(stats)

    def to_index(r):
        if r is None or (isinstance(r, float) and math.isnan(r)):
            return None
        r = max(0.2, min(1.3, r))
        return round((1.3 - r) / 1.1, 3)  # 0..1 (1=better availability)

    streets["parking_index"] = streets["mean_ratio"].apply(to_index)
    streets = streets.drop(columns=["buf", "mean_ratio"])
    return streets.to_crs(4326)

def save_outputs(streets_ix, points):
    streets_ix.to_file(DATA_DIR / "corfu_parking_live.geojson", driver="GeoJSON")
    points.to_file(DATA_DIR / "corfu_sample_points.geojson", driver="GeoJSON")

def refresh_now() -> Dict[str, Any]:
    if not settings.TOMTOM_API_KEY:
        raise RuntimeError("Missing TOMTOM_API_KEY. Set it in Codespaces secret or .env")
    bbox = settings.CORFU_BBOX
    grid = build_grid(bbox, spacing_m=settings.GRID_SPACING_METERS)
    streets, parking = fetch_osm(bbox)
    points = sample_ratios(grid, settings.TOMTOM_API_KEY, settings.MAX_TOMTOM_CALLS)
    streets_ix = compute_parking_index(streets, points)
    save_outputs(streets_ix, points)
    _cache["streets_gdf"] = streets
    _cache["points_gdf"] = points
    _cache["streets_ix"] = streets_ix
    _cache["last_updated"] = datetime.now(timezone.utc).isoformat()
    return {
        "last_updated": _cache["last_updated"],
        "streets": len(streets_ix),
        "points": int(points.shape[0]),
    }

def get_latest_geojson() -> Dict[str, Any]:
    if _cache["streets_ix"] is None:
        refresh_now()
    return _cache["streets_ix"].__geo_interface__

def get_status() -> Dict[str, Any]:
    return {
        "provider": "proxy(osm+tomtom)",
        "last_updated": _cache["last_updated"],
        "streets": None if _cache["streets_ix"] is None else int(_cache["streets_ix"].shape[0]),
        "points": None if _cache["points_gdf"] is None else int(_cache["points_gdf"].shape[0]),
        "bbox": settings.CORFU_BBOX,
        "grid_spacing_m": settings.GRID_SPACING_METERS,
    }

def make_heatmap_html() -> Path:
    from folium import Map
    from folium.plugins import HeatMap
    if _cache["streets_ix"] is None or _cache["points_gdf"] is None:
        refresh_now()
    points = _cache["points_gdf"].dropna(subset=["traffic_ratio"]).copy()
    min_lon, min_lat, max_lon, max_lat = settings.CORFU_BBOX
    center = [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2]
    m = Map(location=center, zoom_start=14, tiles="OpenStreetMap", control_scale=True)
    points["weight"] = points["traffic_ratio"].apply(lambda r: max(0.0, min(1.0, 1.2 - r)))
    HeatMap([[geom.y, geom.x, w] for geom, w in zip(points.geometry, points["weight"])],
            name="Traffic proxy heat").add_to(m)
    out = DATA_DIR / "corfu_parking_heatmap.html"
    m.save(str(out))
    return out
