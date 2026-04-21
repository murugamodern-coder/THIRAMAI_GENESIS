# Business Operations Notes

## Wood-Pressed Oil (Maraseku)
- Track seeds by lot, moisture %, and extraction day.
- Maintain cold-press temperature discipline to preserve quality.
- Separate inventory buckets: raw seeds, WIP cake, finished oil, dispatch.

## Inventory Tracking Logic
- Recommended keys: item_code, lot_id, opening_qty, inward_qty, outward_qty, closing_qty.
- Closing quantity formula: opening + inward - outward.
- Add reorder alert threshold per SKU and monitor daily variance.
- Keep unit conversions explicit (kg, liters, tins) to avoid reporting drift.
