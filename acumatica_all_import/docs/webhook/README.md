# Acumatica Webhook

Webhook Acumatica menerima master data dan transaksi melalui satu endpoint:

```text
POST /acumatica/webhook/<webhook_key>
```

Kirim payload JSON dengan header `X-API-Key`. Nilai `<webhook_key>` menyatakan jenis data, misalnya `customer`, `stock-item`, `po_receipt`, atau `shipment_completed`. Contoh payload dan request tersedia di `postman/acumatica-webhooks.postman_collection.json` pada repository WMS-Tijari.

Endpoint memvalidasi API key dan nama webhook, lalu menyimpan payload sebagai `pending` di Webhook Logs. Proses staging dan import dijalankan setelah log diproses dari menu Webhook Logs atau oleh scheduler.

Untuk pembagian modul, fungsi, dan alur data lengkap, lihat [architecture.md](architecture.md).
