# Arsitektur API Data Hub

Dokumen ini memetakan arsitektur **fetch dan import data** pada API Data Hub sebagai dasar merapikan struktur kode. Webhook tidak termasuk cakupan dokumen ini. Scheduler hanya disebut sebagai pemanggil fetch/import, bukan sebagai area yang sedang direncanakan. Pemilik utama kode Data Hub adalah addon sibling `../acumatica_all_import`; addon `tijari_wms_18` menyediakan model dan aturan WMS/Odoo yang dipakai saat dokumen operasional dibuat.


## Dasar operation: Pick, Receipts, dan Internal Transfer

Untuk mengelompokkan transaksi Data Hub, mulai dari dua operation utama: **Pick untuk outbound** dan **Receipts untuk inbound**. Internal Transfer dijelaskan setelah keduanya karena merupakan perpindahan internal, bukan transaksi inbound atau outbound.

| Operation | Kode Odoo | Kategori WMS | Makna dalam alur Data Hub |
|---|---|---|---|
| Pick — outbound | `internal` | `pick` | Tahap outbound untuk mengambil barang dari lokasi stok dan menyiapkannya untuk proses keluar. Pick bukan tahap pengiriman/Delivery itu sendiri. |
| Receipts — inbound | `incoming` | `receive` | Tahap inbound untuk menerima barang masuk ke gudang, misalnya PO Receipt dan Inventory Receipt. |
| Internal Transfer | `internal` | `internal` | Perpindahan barang antar lokasi/gudang internal. Ini kategori tersendiri dan tidak diklasifikasikan sebagai inbound atau outbound. |

Di sini istilah inbound/outbound dipakai untuk klasifikasi operation **Receipts** dan **Pick**. Pada alur gudang yang memiliki beberapa tahap, Pick menyiapkan barang outbound dan Delivery (`outgoing`/`delivery`) adalah operation pengiriman keluar yang terpisah. Jangan menyimpulkan semua tahap proses hanya dari nama transaksi Acumatica.

Receipts juga tidak otomatis berarti semua transaksi bernama return. Arah operation ditentukan oleh jalur bisnis dan lokasi sumber/tujuan: PO Return tertentu di implementasi ini dipetakan ke receive, sedangkan Credit Memo Consignment menggunakan Pick. Periksa aturan transaksi spesifik sebelum mengubah mapping.

**Internal Transfer berbeda dari Pick.** Keduanya memakai kode Odoo `internal`, tetapi kategorinya berbeda: Pick berkategori `pick` untuk tahap outbound/pengambilan, sedangkan transfer berkategori `internal` untuk perpindahan internal. Operation type Pick tidak otomatis cocok untuk dokumen Internal Transfer hanya karena sama-sama berkode `internal`.

Pada transfer satu langkah, importer membentuk perpindahan internal dalam satu tahap. Pada transfer dua langkah, perpindahan dibagi ke tahap keluar dan tahap masuk sesuai alur transfer; masing-masing tahap dapat menjadi picking tersendiri. Operation type yang dipakai mengikuti tahap dan konfigurasi warehouse. Karena itu nama “Transfer In/SOTR” atau “Transfer Out/Shipment” saja belum cukup untuk menentukan satu operation tanpa memeriksa jalur importer dan record picking yang dibuat.

### Operation type yang sudah tersedia di warehouse

Warehouse memiliki operation type yang digunakan Data Hub seperti `Pick` (`internal`/`pick`) untuk tahap outbound, `Receipts` (`incoming`/`receive`) untuk tahap inbound, `Internal Transfer`/`Internal Transfers` (`internal`/`internal`) untuk perpindahan internal, dan `Delivery Orders` (`outgoing`/`delivery`) untuk pengiriman keluar. Alur lain juga dapat memakai `Pack`/`Pack Internal`. Nama merupakan label tampilan; resolver mengutamakan pasangan warehouse + `code` + `operation_category` serta field operation type pada warehouse.

Dalam resolver terpusat, pasangan utama adalah `incoming + receive` → field `in_type_id`, `internal + pick` → `pick_type_id`, dan `internal + internal` → `adt_transfer_internal_type_id`. Resolver mencari operation type aktif yang cocok; konfigurasi yang tidak ditemukan atau ambigu dapat menghasilkan error atau record kosong ketika dipanggil dengan `required=False`. Beberapa wizard memiliki fallback lokal, sehingga jalur transaksi tertentu perlu tetap diverifikasi.

Data Hub juga mengenal operation document-only seperti `Direct Receipt` dan `Direct Delivery Order`. Keduanya merupakan operation khusus yang di-resolve melalui target operation/document-only, bukan pengganti umum untuk Receipt dan Pick. Misalnya transaksi consignment dapat menuju Direct Delivery Order karena kontrak prosesnya, sementara PO Receipt normal tetap memakai Receipt.

## Cakupan dan istilah

- **Fetch**: mengambil data dari endpoint Acumatica dan menyimpannya ke model staging.
- **Import**: membaca staging, memvalidasi data, lalu membuat atau memperbarui master data/dokumen bisnis di Odoo.
- **Staging**: model per jenis master/transaksi yang menyimpan data Acumatica, status import, pesan, serta relasi detail bila transaksi mempunyai baris produk.
- **Operation type**: `stock.picking.type` Odoo yang dipilih saat import dokumen stok. Pemetaan akhir bergantung pada warehouse, konfigurasi operation, kategori, dan resolver yang dipanggil.

## Gambaran alur

```text
                         +-----------------------------+
                         | Unified Import UI / Wizard  |
                         | IMPORT_MAP + type lists     |
                         +--------------+--------------+
                                        |
                           fetch config / parameters
                                        v
Acumatica API ---> fetch + mapping ---> staging models ---> _do_import()
                        ^                                      |
                        |                                      v
               Scheduler caller                      Odoo business models
                                                     master / stock /
                                                     manufacturing
```

Fetch mengubah response Acumatica menjadi staging. Import membaca staging dan membuat/memperbarui master Odoo atau dokumen stok/manufaktur. Scheduler dapat memanggil fetch/import yang sama; logika bisnisnya tetap berada pada jalur fetch/import, bukan di scheduler.

## Komponen dan tanggung jawab saat ini

| Komponen | Tanggung jawab |
|---|---|
| `wizard/acumatica_unified_import_wizard.py` | Registry `IMPORT_MAP`, daftar master/transaksi yang terlihat di Unified Import, pemilihan wizard/config/staging model, dan proses batch import. |
| `wizard/import_*_wizard.py` | Parameter fetch per tipe, pemanggilan endpoint Acumatica, pengubahan hasil fetch menjadi staging, serta aksi import pending untuk beberapa jalur. |
| `models/acumatica_*.py` | Staging per entitas; `_do_import()` berisi validasi bisnis, pencarian/pembuatan Odoo record, pembuatan stock picking/manufacturing, status dan error. |
| `models/stock_picking_type.py` | Resolver `stock.picking.type` yang dipakai importer, termasuk kategori operation; beberapa transaksi juga memiliki fallback lokal. |
| `models/acumatica_cronjob.py`, `models/api_scheduler.py` | Pemanggil fetch/import terjadwal; dicatat sebagai entry point, bukan fokus refactor dalam dokumen ini. |

## Jalur Unified Import

1. Pengguna memilih jenis import. `TRANSACTION_TYPES` dan `MASTER_DATA_TYPES` menentukan pilihan yang ditampilkan; `IMPORT_MAP` memasangkan key dengan wizard, model staging, config field, dan parameter tambahan.
2. Wizard khusus mengambil data dari Acumatica menggunakan konfigurasi yang dipilih.
3. Hasil disimpan sebagai record staging. Jenis transaksi yang memiliki detail biasanya memiliki model header dan model baris terkait.
4. Import pending memilih record berdasarkan state/config dan memanggil `_do_import()` di staging model.
5. Importer memvalidasi referensi dan data, lalu membuat/memperbarui record tujuan Odoo. Untuk transaksi stok, importer meresolusikan operation type dan membentuk picking/move; transaksi tertentu membentuk manufacturing order atau hanya memperbarui picking yang sudah ada.
6. Staging menyimpan state dan pesan hasil. Detail keberhasilan harus dilihat dari state staging dan record tujuan, bukan hanya jumlah baris yang diproses wizard.

## Master dan transaksi di Unified Import

Key berikut diambil dari daftar Unified Import saat ini. Nama label dan model staging bersumber dari `IMPORT_MAP`.

| Kategori | Key | Label UI | Staging model |
|---|---|---|---|
| Master | `customer` | Customer | `acumatica.customer.line` |
| Master | `vendor` | Vendor | `acumatica.vendor.line` |
| Master | `uom` | UoM | `acumatica.uom.line` |
| Master | `warehouse` | Warehouse & Location | `acumatica.warehouse.line` |
| Master | `stock_item` | Stock Item | `acumatica.stock.item.line` |
| Master | `non_stock_item` | Non-Stock Item | `acumatica.non.stock.item.line` |
| Master | `inventory_adjustment` | Inventory Adjustment | `acumatica.inventory.adjustment.staging` |
| Master/data | `inventory_stock` | Detail Stock Acumatica | `acumatica.inventory.stock.line` |
| Transaksi | `po_receipt` | Purchase Order | `acumatica.receipt.line` |
| Transaksi | `inventory_received` | Inventory Receipt | `acumatica.inventory.recieved.line` |
| Transaksi | `shipment_so` | SO Return | `acumatica.shipment.line` |
| Transaksi | `so_shipment` | SO Shipment | `acumatica.shipment.gi.staging` |
| Transaksi | `inventory_issue` | Inventory Issue | `acumatica.inventory.issue.line` |
| Transaksi | `issue_po_return` | Vendor Return / PO Return | `acumatica.issue.po.return.line` |
| Transaksi | `so_transfer` | Transfer (In/SOTR) | `acumatica.transfer.line` |
| Transaksi | `transfer_shipment` | Transfer (Out/Shipment) | `acumatica.transfer.shipment.line` |
| Transaksi | `transfer_one_step` | Transfer 1 Step | `acumatica.transfer.one.step.line` |
| Transaksi | `transfer_two_step` | Transfer 2 Step | `acumatica.transfer.two.step.line` |
| Transaksi | `invoice_consignment` | Invoice Consignment | `acumatica.invoice.consignment.staging` |
| Transaksi | `credit_memo_consignment` | Credit Memo Consignment | `acumatica.credit.memo.consignment.staging` |
| Transaksi | `shipment_completed` | Update SO completed | `acumatica.shipment.completed.staging` |
| Transaksi | `shipment_transfer_completed` | Shipment Transfer Completed | `acumatica.shipment.transfer.completed.staging` |
| Transaksi | `kit_assembly` | Kit Assembly | `acumatica.kit.assembly` |
| Transaksi | `vendor_return_direct_transfer` | Return Consignment | `acumatica.vendor.return.direct.transfer.staging` |
| Transaksi | `vendor_return_document_direct_transfer` | Return Consignment Document | `acumatica.direct.transfer.staging` |

`issue_change_item` masih ada di `IMPORT_MAP`, tetapi sedang dikomentari pada `TRANSACTION_TYPES`, sehingga tidak muncul sebagai pilihan transaksi Unified Import.

Dalam klasifikasi arsitektur Data Hub, Inventory Adjustment dikelompokkan sebagai **Master Data** sesuai struktur yang dituju. Pada implementasi kode saat ini, key `inventory_adjustment` masih tercantum dalam `TRANSACTION_TYPES`; registry Unified Import perlu diselaraskan saat refactor.

## Pemetaan transaksi ke operation type

Tabel ini menjelaskan maksud operation yang terlihat dari jalur importer saat ini. Operation final perlu diverifikasi bersama warehouse dan konfigurasi database; label UI tidak selalu identik dengan nama record `stock.picking.type`.

| Transaksi | Operation | Penjelasan |
|---|---|---|
| PO Receipt | Receipt (`incoming`/`receive`) | Menerima barang PO ke gudang. |
| Inventory Receipt | Receipt (`incoming`/`receive`) | Menerima barang dari transaksi inventory receipt ke gudang. |
| SO Return | Receipt (`incoming`/`receive`) | Menerima kembali barang dari proses SO return. |
| Vendor Return / PO Return | Receipt (`receive`) pada jalur yang terdeteksi | Jalur importer ini membentuk penerimaan; pastikan arah fisik dan lokasi sesuai proses bisnis sebelum mapping diubah. |
| SO Shipment | Pick (`internal`/`pick`); transaksi berkode CO dapat memakai `internal` | Pick adalah tahap pengambilan barang untuk proses SO, bukan Delivery Orders. Cabang CO memiliki kategori berbeda. |
| Inventory Issue | Pick (`internal`/`pick`) | Mengambil barang dari stok untuk inventory issue. |
| Credit Memo Consignment | Pick (`internal`/`pick`) | Membentuk tahap Pick pada jalur importer yang terdeteksi. |
| Transfer (In/SOTR) | Receipt (`incoming`) | Wizard mencari operation incoming yang ditandai sebagai default API pada warehouse terkait. |
| Transfer (Out/Shipment) | Operation internal yang dikonfigurasi untuk shipment transfer | Tahap keluar transfer perlu dibedakan dari Pick pada SO Shipment; gunakan operation type transfer yang dikonfigurasi. |
| Transfer 1 Step | Internal Transfer (`internal`/`internal`) | Memindahkan barang antar lokasi/gudang internal dalam satu tahap. |
| Transfer 2 Step | Internal Transfer (`internal`/`internal`) untuk tahap transfer | Memindahkan barang melalui tahap keluar dan masuk; masing-masing tahap dapat menjadi picking tersendiri. |
| Update SO completed | - | Memperbarui status/dampak dokumen existing; tidak membuat operation type baru. |
| Shipment Transfer Completed | Operation pada picking transfer yang sudah ada | Memperbarui status/dampak transfer existing; tidak membuat operation type baru. |
| Kit Assembly | Manufacturing (`operation_type='manufacturing'`) | Membentuk proses manufacturing untuk perakitan kit. |
| Invoice Consignment | Direct Delivery Order; beberapa jalur juga memakai Internal Transfer | Target operation khusus consignment; langkah aktual mengikuti cabang proses dan konfigurasi. |
| Return Consignment | Direct Delivery Order dan langkah internal terkait | Jalur direct transfer memakai target operation khusus dan dapat membuat langkah internal. |
| Return Consignment Document | Direct Delivery Order pada mode dokumen terkait | Target operation bergantung konfigurasi document-only dan cabang import. |

Resolver operation memiliki beberapa strategi: target khusus (termasuk document-only), resolver warehouse+kode+kategori, dan fallback pada beberapa wizard. Karena itu pengujian perlu memeriksa operation type aktual pada hasil picking untuk tiap warehouse, bukan sekadar mengandalkan nama Receipt/Pick atau tabel ini.

## Risiko arsitektur dan titik refactor

| Risiko pada fetch/import | Dampak yang mungkin | Arah perapihan |
|---|---|---|
| Registry tipe data dan pemetaan `IMPORT_MAP` tersebar dari konfigurasi sampai wizard/model staging. | Tipe dapat terpilih tetapi salah wizard, config, atau staging model; perbedaan baru terlihat saat runtime. | Inventaris lalu konsolidasikan metadata fetch/import per tipe, dengan pemeriksaan konsistensi pilihan UI, config, dan model staging. |
| Wizard per tipe menggabungkan parameter UI, request, pagination, mapping response, upsert staging, dan kadang import. | Perubahan transport/pagination perlu diulang dan file wizard menjadi sulit dipahami. | Pisahkan UI, komponen fetch bersama, adapter per tipe, operasi staging, dan importer domain secara bertahap. |
| Implementasi pagination dan fetch manual/fetch-all berulang. | Batas batch, offset, atau counter dapat berbeda dan menyebabkan record terlewat/duplikat. | Satukan mekanisme umum; biarkan filter, body, dan strategi khusus tetap menjadi konfigurasi/adaptor endpoint. |
| Pola upsert staging berbeda antar tipe dan identitas record tidak selalu terlihat eksplisit. | Fetch ulang dapat membuat duplikat, menimpa data yang belum diimpor, atau menghapus detail yang tidak dikirim. | Dokumentasikan key header/detail dan kontrak full snapshot vs delta sebelum menyatukan upsert. |
| Validasi fetch dan validasi bisnis import bercampur. | Error sulit dikategorikan; perubahan parsing bisa tanpa sengaja mengubah aturan bisnis. | Pisahkan validasi bentuk/kelengkapan payload dari validasi domain yang dilakukan importer. |
| Logika import tersebar antara wizard batch dan `_do_import()` pada model staging. | Beberapa entry point dapat menghasilkan aturan batch, status, atau jumlah sukses yang berbeda. | Tetapkan satu kontrak pemanggilan importer dan hasil per record; wizard hanya mengorkestrasi batch dan menampilkan hasil. |
| Resolver operation dipakai bersama tetapi terdapat fallback lokal. | Warehouse dapat menghasilkan operation type yang salah atau kosong, dan penyebabnya sulit dilacak. | Pertahankan resolver bersama sebagai rujukan; inventaris fallback dan catat kebijakan per transaksi/warehouse sebelum merapikannya. |
| Status dan counter fetch/import tidak selalu menunjukkan tahap mana yang berhasil. | Fetch sukses bisa disalahartikan sebagai dokumen Odoo berhasil dibuat; jumlah dicoba bisa berbeda dari jumlah sukses. | Bedakan hasil fetch/staging dari hasil import (`created`, `updated`, `skipped`, `error`) dan ambil counter dari state akhir. |
| Beberapa batch dapat commit sebelum seluruh proses selesai. | Kegagalan di batch berikutnya meninggalkan hasil parsial dan retry perlu aman. | Dokumentasikan batas commit dan pastikan pemrosesan ulang staging yang sama idempotent. |

## Rencana refactor khusus Fetch & Import Data

Scope ini mencakup alur **Acumatica → fetch → staging → import → record bisnis Odoo**. Scheduler hanya menjadi pemanggil yang harus tetap kompatibel; webhook tidak masuk rencana ini.

```text
Fetch:  parameter/config → HTTP request → pagination → parse/map → upsert staging
Import: pilih staging → validasi domain → resolve referensi/operation → create/update Odoo → simpan state dan hasil
```

### Tahap Fetch

| Urutan | Fokus | Hasil yang diharapkan |
|---|---|---|
| 1 | Inventaris tiap data type: wizard, endpoint, HTTP method, parameter/body, filter, response shape, batch strategy, staging target, dan external key. | Peta fetch per tipe dan daftar pola duplikat yang benar-benar setara. |
| 2 | Pisahkan UI wizard dari request. Konsolidasikan base URL, autentikasi, session/header, timeout, HTTP/JSON error, dan request ke client fetch bersama. | Wizard hanya menyiapkan parameter lalu memanggil fetcher; perbedaan endpoint tetap eksplisit. |
| 3 | Konsolidasikan pagination limit/offset, stop condition, validasi batch size, dan counter. Petakan filter incremental (`LastModified`, `fetch_skip`, nomor referensi/OData). | Perilaku halaman konsisten tanpa mengubah kontrak filter endpoint. |
| 4 | Pisahkan parsing generik dari mapping khusus tipe. Gunakan `utils/acumatica_data.py` untuk normalisasi nilai umum; adapter per tipe memetakan field dan struktur header/detail. | Respons mudah ditelusuri dan parsing generik tidak menduplikasi helper. |
| 5 | Standarkan operasi upsert staging setelah key dan kontrak payload diketahui. | Fetch ulang memperbarui record yang tepat; snapshot dan delta diperlakukan sesuai kontrak masing-masing. |
| 6 | Samakan hasil/error fetch dan migrasikan pemanggil wizard/scheduler per keluarga tipe. | Jumlah received/created/updated/skipped/error dan konteks batch dapat ditelusuri; scheduler tetap memakai fetcher yang sama. |

### Tahap Import

| Urutan | Fokus | Hasil yang diharapkan |
|---|---|---|
| 1 | Inventaris `_do_import()` per staging model: validasi, pencarian referensi, create/update tujuan, side effect, status/error, dan commit. Kelompokkan master, transaksi inbound/outbound, transfer, dan transaksi khusus. | Batas perilaku umum dan khusus tiap importer terlihat sebelum kode dipindah. |
| 2 | Seragamkan kontrak hasil importer dan transisi state staging. Pisahkan jumlah dicoba dari created/updated/skipped/error. | UI dan pemanggil batch melaporkan hasil akhir yang konsisten. |
| 3 | Satukan layanan domain yang benar-benar berulang, seperti resolusi partner/product/UoM dan pencatatan hasil. | Mengurangi duplikasi tanpa menghapus validasi khusus transaksi. |
| 4 | Rapikan resolver operation untuk transaksi stok dengan aturan eksplisit per transaksi, tahap, warehouse, dan mode khusus. | Receipt, Pick, dan Internal Transfer terpilih sesuai kebijakan dan konfigurasi; operasi aktual dapat ditelusuri. |
| 5 | Audit idempotency, retry, dan batas commit saat record staging diproses ulang atau dari beberapa pemanggil. | Retry aman dan kegagalan parsial meninggalkan status yang bisa dipahami. |
| 6 | Migrasikan per keluarga importer dengan payload/staging representatif, lalu bandingkan record tujuan dan state lama/baru sebelum menghapus implementasi lama. | Refactor bisa ditinjau bertahap dengan bukti kesetaraan hasil. |

### Prinsip pemisahan file

- File per data type menyimpan parameter, mapping response, aturan staging, dan perilaku import yang memang khusus tipe tersebut.
- Service bersama hanya menampung kontrak yang terbukti sama, seperti HTTP client, pagination generik, helper normalisasi, serta bentuk hasil.
- Wizard menangani input/aksi UI; model staging/importer menangani validasi domain dan perubahan record Odoo.
- Jangan memindahkan atau menggabungkan kode hanya karena namanya mirip. Pertahankan perbedaan endpoint, snapshot/delta, validasi transaksi, serta side effect yang berbeda.

Urutan pengerjaan keseluruhan: inventaris dan baseline → konsolidasi fetch → kontrak staging → hasil fetch → kontrak importer → layanan domain bersama → resolver operation → migrasi per keluarga dan pembandingan hasil. Mulai dengan satu master data dan satu transaksi stok yang mewakili variasi payload dan operation.

### Batas refactor helper

Helper data generik sudah digabung ke `utils/acumatica_data.py` dan dipakai lintas wizard/model. Refactor fetch/import berikutnya berfokus pada pembagian tanggung jawab serta kontrak bersama; jangan membuat wrapper helper per file. Mapping endpoint, validasi bisnis, dan side effect transaksi tetap berada di adapter/importer yang sesuai.

## Batas bukti

Dokumen ini merupakan peta source saat ini, bukan bukti runtime untuk seluruh konfigurasi warehouse/database. Nama operation final, perilaku payload aktual, dan hasil transaksi harus diverifikasi melalui konfigurasi aktif dan record Odoo yang dihasilkan. Kode importer utama berada pada sibling addon `../acumatica_all_import`; perubahan dokumentasi ini ditempatkan di repository `tijari_wms_18` yang menjadi workspace writable saat ini.
