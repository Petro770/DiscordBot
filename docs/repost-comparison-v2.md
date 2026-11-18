# Repost image comparison v2

Implementation checklist:
- [ ] Inspect existing image matching, caching, attachment ingestion, and warning flow; preserve current behavior until tested.
- [ ] Add SSIM on normalized images (only for suitable alignment); record metric and confidence.
- [ ] Add ORB feature matching + RANSAC geometric inlier validation for crops, screenshots and resized images.
- [ ] Add 4x4 spatial color histogram comparison and dominant-color proportions.
- [ ] Add Canny edge structure comparison with appropriate alignment safeguards.
- [ ] Retain existing pHash/dHash screening and configurable REPOST_WARNING_THRESHOLD.
- [ ] Add configurable per-metric minimum similarity thresholds and weights, with safe defaults and validation.
- [ ] Add a configurable minimum count of agreeing metrics / veto logic to reduce false positives; don't treat semantic resemblance as proof of a repost.
- [ ] Expose per-metric scores, threshold decisions and overall score in debug logs; keep Discord warning concise.
- [ ] Add sample .env documentation and tests for identical, recompressed, resized, cropped, color-shifted and unrelated-but-similar-color images.
- [ ] Benchmark performance and avoid costly full comparisons across all stored images.
- [ ] Optional later: moderator true/false-positive feedback for calibration.

Proposed configuration names (final names should follow existing project conventions):
```dotenv
REPOST_WARNING_THRESHOLD=90
REPOST_SSIM_MIN=85
REPOST_ORB_MIN=65
REPOST_SPATIAL_COLOR_MIN=70
REPOST_EDGE_MIN=75
REPOST_MIN_AGREEING_METRICS=2
REPOST_WEIGHT_HASH=20
REPOST_WEIGHT_SSIM=30
REPOST_WEIGHT_ORB=30
REPOST_WEIGHT_COLOR=10
REPOST_WEIGHT_EDGE=10
```
These values are illustrative, not calibrated production thresholds. ORB match score needs explicit normalization and low-feature handling. Ensure weights sum to 100 and handle unavailable metrics without accidental score inflation. Do not enable new automatic warning decisions before regression testing.