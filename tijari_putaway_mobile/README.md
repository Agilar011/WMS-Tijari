# Tijari Putaway Mobile

Kerangka awal aplikasi mobile untuk user putaway.

## Flow Kasar

1. User buka `/putaway/mobile`.
2. Sistem menampilkan stock picking yang scheduled date-nya hari ini dan belum `done` atau `cancel`.
   - Tab `Penerimaan` menampilkan `picking_type_code = incoming`.
   - Tab `Pengiriman` menampilkan `picking_type_code = outgoing`.
3. User pilih picking.
4. Halaman detail menampilkan stock move line per product, termasuk qty, lot, dan destination location.
5. User tekan `Scan Location` atau `Scan Lot`, lalu input quantity aktual.
6. Browser meminta akses kamera handphone.
7. Hasil scan dikirim ke `/putaway/mobile/scan`.
8. Sistem validasi:
   - Untuk penerimaan, location cocok jika scan sama dengan destination location (`location_dest_id`).
   - Untuk pengiriman, location cocok jika scan sama dengan source location (`location_id`).
   - Lot cocok jika scan sama dengan `lot_id.name` atau `lot_name`.
   - Quantity cocok jika input sama dengan `stock.move.line.quantity`.
9. Jika location, lot, dan quantity sudah cocok, `stock.move.line.matching` diset ke `match`.

## Catatan Implementasi

- Ini masih gambaran kasar, belum ada proses validate picking.
- Scanner memakai `BarcodeDetector` browser jika tersedia, dan tetap menyediakan input manual sebagai fallback.
- Field hasil scan memakai field existing dari `tijari_wms_18`: `confirmation_location_code`, `confirmation_lot_code`, `matching_loc_dest_id`, `matching_lot_id`, dan `matching`.
- Quantity hasil input disimpan di field baru `confirmation_quantity` pada `stock.move.line`.
- Addon ini dibuat sebagai folder terpisah: `tijari_putaway_mobile`.
