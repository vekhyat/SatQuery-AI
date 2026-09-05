from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin

root = Path(__file__).resolve().parent / "fixtures"
root.mkdir(exist_ok=True)
y, x = np.mgrid[0:64, 0:96]
for name, bands, offset, date in [
    ("before", 3, 0, "2024-06-12"),
    ("after", 3, 0, "2024-06-24"),
    ("sar", 1, 0, "2024-06-24"),
    ("mismatch", 3, 1, "2024-06-24"),
]:
    with rasterio.open(root / f"{name}.tif", "w", driver="GTiff", width=96, height=64,
                       count=bands, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(77 + offset, 29, 0.001, 0.001)) as scene:
        for band in range(1, bands + 1):
            scene.write(((x * (band + 1) + y * band) % 250 + 1).astype("uint8"), band)
        scene.update_tags(acquisition_date=date, modality="sar" if bands == 1 else "optical")
print(root)
