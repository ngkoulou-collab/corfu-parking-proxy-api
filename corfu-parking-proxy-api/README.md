# Corfu Parking API — Free Live Proxy (OSM + TomTom)

This repo contains a FastAPI app and a provider that estimates **street-level parking availability** in Corfu town using **free data**:
- **OpenStreetMap** (Overpass) for streets/parking geometry
- **TomTom Traffic API** (free tier) for near-real-time congestion, used as a **proxy** for parking pressure
- Optional Folium heatmap

> ⚠️ This does **not** use paid satellite imagery, and it does **not** count individual cars. It’s a practical, zero-cost approximation.

## Quick start (GitHub Codespaces)
1. Click **Code → Create Codespace on main**.
2. Add a Codespaces **secret** named `TOMTOM_API_KEY` with your key.
3. The container will install deps and auto-run `uvicorn`.
4. Open:
   - Docs → `/docs`
   - Status → `/parking-proxy/status`
   - GeoJSON → `/parking-proxy/geojson`
   - Heatmap → `/parking-proxy/heatmap`

## Local dev
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit TOMTOM_API_KEY and settings
uvicorn app.main:app --reload
```

## Environment (.env / secrets)
```
PARKING_PROVIDER=proxy
REFRESH_INTERVAL_SECONDS=60
CORFU_BBOX=19.9100,39.6100,19.9400,39.6400
GRID_SPACING_METERS=250
MAX_TOMTOM_CALLS=300
TOMTOM_API_KEY=YOUR_TOMTOM_KEY
```

## Endpoints
- `GET /` — welcome
- `GET /parking-proxy/status` — provider status
- `GET /parking-proxy/geojson` — streets with `parking_index` (0..1)
- `GET /parking-proxy/heatmap` — Folium HTML map

## How it works
We sample a grid over the bbox and query TomTom `flowSegmentData` for `currentSpeed` vs `freeFlowSpeed`. Lower ratios ≈ congestion → **lower** parking availability (proxy). We aggregate the ratios to nearby street segments and compute `parking_index` ∈ [0,1] (higher means more likely availability).

## Caveats
- This is **not** ground truth; treat it as an **indicator**.
- Overpass and TomTom have **rate limits**; tune `GRID_SPACING_METERS` and `MAX_TOMTOM_CALLS`.
- For production, add caching/queuing and backoff; consider a paid traffic tier if needed.

## License
MIT
