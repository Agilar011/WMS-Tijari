# Acumatica UoM Import — Modul Odoo

## 📦 Deskripsi
Modul ini mengkonversi script Python test API Acumatica WMS menjadi modul Odoo yang fully integrated.
Memungkinkan import Unit of Measure (UoM) dari Acumatica langsung ke master data `uom.uom` Odoo.

---

## 🚀 Cara Install

1. Copy folder `acumatica_uom_import` ke direktori addons Odoo kamu:
   ```
   /odoo/addons/acumatica_uom_import/
   ```

2. Restart Odoo server:
   ```bash
   sudo systemctl restart odoo
   # atau
   ./odoo-bin -u acumatica_uom_import
   ```

3. Aktifkan Developer Mode di Odoo:
   `Settings → Activate Developer Mode`

4. Install modul:
   `Apps → Cari "Acumatica UoM Import" → Install`

---

## 🔧 Konfigurasi

### 1. Setting API Config
Buka menu: **Acumatica WMS → Konfigurasi → API Config**

Isi:
| Field | Nilai Default | Keterangan |
|-------|---------------|------------|
| Base URL | `http://34.101.103.239/acumportal/entity` | URL server Acumatica |
| API Version | `25.200.001` | Versi endpoint WMS |
| Username | `wms` | Username login |
| Password | *(isi password)* | Password login |
| Company Code | `asgjkt` | Kode perusahaan |

Klik tombol **🔌 Test Koneksi** untuk verifikasi.

---

## 📥 Cara Import UoM

### Cara Cepat (Import Semua)
1. Buka **Acumatica WMS → Import Data → 📥 Import UoM**
2. Pilih konfigurasi API
3. Klik **📥 Tarik Data dari Acumatica**
4. Lihat ringkasan (total data, data baru, sudah ada)
5. Klik **⬆️ Import Sekarang** → selesai!

### Cara Selektif (Pilih Manual)
1. Setelah tarik data, klik **🔍 Lihat & Pilih Data**
2. Di list view, centang/uncentang kolom **Pilih**
3. Klik tombol **Import** per baris, atau select multiple → Action → Import Selected

---

## 📋 Fitur

| Fitur | Keterangan |
|-------|------------|
| ✅ Test Koneksi | Verifikasi kredensial API sebelum import |
| ✅ Preview Data | Lihat semua data sebelum dieksekusi |
| ✅ Deteksi Duplikat | Skip otomatis UoM yang sudah ada di Odoo |
| ✅ Import Selektif | Pilih baris tertentu yang mau diimport |
| ✅ Status Tracking | Badge warna per status (pending/imported/skipped/error) |
| ✅ Log Keterangan | Setiap baris ada info hasilnya |
| ✅ Link ke UoM Odoo | Setelah import, ada link langsung ke record `uom.uom` |

---

## 🗂️ Struktur Modul

```
acumatica_uom_import/
├── __manifest__.py          # Metadata modul
├── __init__.py
├── models/
│   ├── acumatica_config.py  # Model konfigurasi & koneksi API
│   └── acumatica_uom_line.py # Tabel staging data UoM
├── wizard/
│   ├── import_uom_wizard.py # Wizard 3-step import
│   └── import_uom_wizard_views.xml
├── views/
│   ├── acumatica_config_views.xml
│   ├── acumatica_uom_import_views.xml
│   └── menu.xml
└── security/
    └── ir.model.access.csv
```

---

## 🔄 Kompatibilitas
- Odoo 18.0
- Python 3.10+
- Requires: `uom`, `stock` modules
