import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse

from app.core.config import settings
from app.providers import osm_traffic_proxy as proxy

app = FastAPI(title="Corfu Parking API", version="1.0")

_refresh_task = None

@app.on_event("startup")
async def startup_event():
    global _refresh_task
    if settings.PARKING_PROVIDER.lower() == "proxy":
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, proxy.refresh_now)
        async def refresher():
            interval = int(settings.REFRESH_INTERVAL_SECONDS)
            while True:
                try:
                    await loop.run_in_executor(None, proxy.refresh_now)
                except Exception as e:
                    print("[refresh] error:", e)
                await asyncio.sleep(interval)
        _refresh_task = asyncio.create_task(refresher())

@app.on_event("shutdown")
async def shutdown_event():
    global _refresh_task
    if _refresh_task:
        _refresh_task.cancel()

@app.get("/", response_class=PlainTextResponse)
def root():
    return "Welcome to Corfu Parking API. See /docs. Providers: mock, proxy(osm+tomtom)."

@app.get("/parking-proxy/status")
def parking_proxy_status():
    if settings.PARKING_PROVIDER.lower() != "proxy":
        raise HTTPException(400, "Proxy provider is not enabled. Set PARKING_PROVIDER=proxy")
    return proxy.get_status()

@app.get("/parking-proxy/geojson")
def parking_proxy_geojson():
    if settings.PARKING_PROVIDER.lower() != "proxy":
        raise HTTPException(400, "Proxy provider is not enabled. Set PARKING_PROVIDER=proxy")
    return JSONResponse(proxy.get_latest_geojson())

@app.get("/parking-proxy/heatmap")
def parking_proxy_heatmap():
    if settings.PARKING_PROVIDER.lower() != "proxy":
        raise HTTPException(400, "Proxy provider is not enabled. Set PARKING_PROVIDER=proxy")
    path = proxy.make_heatmap_html()
    return FileResponse(path)
