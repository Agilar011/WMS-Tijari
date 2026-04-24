# Acumatica Inventory Receipt Import

Pola modul ini disamakan dengan modul contoh customer:
- 1 config model
- 1 preview/import line model
- 1 wizard import

## Flow
1. Isi API Config
2. Jalankan wizard Import Inventory Receipt
3. Tarik data dari Acumatica
4. Preview line hasil fetch
5. Import semua / pilih sebagian
6. Odoo membuat atau update 1 stock picking per ReceiptNbr

## Matching default
- VendorID -> `res.partner.ref`
- InventoryID -> `product.product.default_code`
- Warehouse -> `stock.warehouse.code`
- Location -> `stock.location.complete_name` atau `name`
- UOM -> `uom.uom.name`

## Contoh data Acumatica
- Header:
  - ReceiptNbr
  - VendorID
  - Date
  - Warehouse
  - Status
  - LastModifiedDateTime
- Detail:
  - InventoryID
  - ReceiptQty
  - UOM
  - Location
  - POLineNbr
  - POOrderNbr
  - LineNbr
