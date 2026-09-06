"""Evaluate categorical maps against supplied labels; never infer ground truth."""
import numpy as np
import rasterio
from .inputs import BandSource, DatasetError, inspect_source, read_aligned


def evaluate_arrays(predicted, reference):
    """Rows are reference, columns prediction; 0=other, 1=water, 2=built-up."""
    predicted, reference = np.asarray(predicted), np.asarray(reference)
    if predicted.shape != reference.shape or predicted.ndim != 2:
        raise DatasetError("Evaluation arrays must be two-dimensional with identical shapes.")
    for name, data in (("prediction", predicted), ("reference", reference)):
        observed = data[np.isfinite(data) & (data != 255)]
        if not np.isin(observed, [0, 1, 2]).all():
            raise DatasetError(f"{name} has unsupported class codes. Use 0=other, 1=water, 2=built-up, 255=nodata.")
    pv = np.isfinite(predicted) & (predicted != 255)
    rv = np.isfinite(reference) & (reference != 255)
    common = pv & rv
    if not common.any():
        raise DatasetError("No jointly valid prediction/reference pixels are available for evaluation.")
    codes = reference[common].astype(np.int64) * 3 + predicted[common].astype(np.int64)
    matrix = np.bincount(codes, minlength=9).reshape(3, 3)
    metrics = {}
    def ratio(numerator, denominator):
        return float(numerator / denominator) if denominator else None
    for code, name in enumerate(("other", "water", "builtup")):
        tp = int(matrix[code, code])
        support, predicted_count = int(matrix[code].sum()), int(matrix[:, code].sum())
        fp, fn = predicted_count - tp, support - tp
        metrics[name] = {"reference_pixels": support, "predicted_pixels": predicted_count,
                         "true_positive": tp, "false_positive": fp, "false_negative": fn,
                         "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
                         "f1": ratio(2 * tp, 2 * tp + fp + fn), "iou": ratio(tp, tp + fp + fn)}
    ious = [item["iou"] for item in metrics.values() if item["iou"] is not None]
    f1s = [item["f1"] for item in metrics.values() if item["f1"] is not None]
    return {"evaluated_pixels": int(common.sum()), "reference_valid_pixels_on_prediction_grid": int(rv.sum()),
            "reference_pixels_without_prediction": int((rv & ~pv).sum()),
            "prediction_pixels_without_reference": int((pv & ~rv).sum()),
            "prediction_coverage_of_reference": ratio(int(common.sum()), int(rv.sum())),
            "accuracy": float(np.trace(matrix) / matrix.sum()), "mean_iou": float(np.mean(ious)),
            "macro_f1": float(np.mean(f1s)), "confusion_matrix": matrix.tolist(),
            "matrix_order": ["other", "water", "builtup"], "matrix_axes": "rows=reference, columns=prediction",
            "per_class": metrics,
            "scope": "Only jointly valid pixels on the prediction grid; review coverage alongside accuracy. Absent classes have null undefined metrics. This evaluation does not calibrate confidence or prove accuracy on other scenes."}


def evaluate_files(prediction_path, reference_path, reference_nodata=None, max_pixels=16_000_000):
    if type(max_pixels) is not int or max_pixels < 1:
        raise DatasetError("max_pixels must be a positive integer.")
    prediction = BandSource(prediction_path)
    reference = BandSource(reference_path, nodata=reference_nodata)
    pred_meta = inspect_source(prediction, max_pixels)
    ref_meta = inspect_source(reference, max_pixels)
    for role, spec, meta in (("prediction", prediction, pred_meta), ("reference", reference, ref_meta)):
        with rasterio.open(spec.path) as src:
            if src.count != 1:
                raise DatasetError(f"{role} must be a single-band categorical label raster.")
        if meta["scale"] != 1 or meta["offset"] != 0:
            raise DatasetError(f"{role} must contain unscaled class codes, not calibrated continuous values.")
        if meta["nodata"] in (0, 1, 2):
            raise DatasetError(f"{role} nodata conflicts with class codes 0/1/2. Correct its nodata metadata" +
                               (" or provide --reference-nodata 255." if role == "reference" else "."))
    with rasterio.open(prediction.path) as src:
        grid = {"crs": src.crs, "transform": src.transform, "width": src.width, "height": src.height, "bounds": list(src.bounds)}
    pred = read_aligned(prediction, pred_meta, grid, "valid_mask")
    labels = read_aligned(reference, ref_meta, grid, "valid_mask")
    result = evaluate_arrays(pred, labels)
    result["inputs"] = {"prediction": pred_meta, "reference": ref_meta}
    result["reference_alignment"] = "nearest-neighbour resampling onto the prediction grid"
    return result
