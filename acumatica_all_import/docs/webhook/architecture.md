# Webhook Architecture

## Overview

Webhook menerima payload Acumatica melalui satu pola URL. Master dan transaksi memakai endpoint yang sama, sedangkan pemetaan payload dipisahkan agar perubahan field master tidak bercampur dengan mapping transaksi. Fungsi untuk operation type juga dipisahkan dari mapping field transaksi.

## Request flow

```text
Acumatica
   |
   | POST /acumatica/webhook/<webhook_key>
   | X-API-Key + JSON payload
   v
AcumaticaWebhookController (controllers/webhook.py)
   |-- validate API key and webhook key
   |-- normalize key and classify as master or transaction
   |-- save payload to acumatica.webhook.log (pending)
   v
Webhook Logs / scheduler
   |-- action_process_to_staging()
   |-- dispatch using saved webhook_type and webhook_name
   v
MasterMappingMixin or TransactionMappingMixin
   |-- map Acumatica values into staging fields
   |-- shared payload and upsert helpers
   v
Master or transaction staging model
   |-- _do_import()
   v
Odoo master/business records and stock operations
```

Receiving a webhook only validates and queues its payload in the log. The staging and import steps happen later when the log is processed. This keeps API receipt separate from Odoo business processing and retains the original payload for review/replay.

## Controller and mapping modules

### `controllers/webhook.py`

Defines `AcumaticaWebhookController` and the single HTTP route. `_resolve_webhook_type()` recognizes master keys first, then transaction keys and aliases. `_receive_webhook()` checks the API key, extracts JSON, creates a pending log, and returns the JSON response. The controller composes the mapping and helper mixins below.

### `controllers/webhook_common.py`

`WebhookCommonMixin` holds functions shared by master and transaction processing:

- `_env()`, `_json_response()`, and `_check_api_key()` provide environment access, API responses, and authentication.
- `_raw_payload()`, `_create_webhook_log()`, and payload record helpers read and record incoming data.
- `_value()`, `_first_value()`, `_bool_value()`, `_float_value()`, `_int_value()`, and `_note_value()` normalize Acumatica scalar values.
- `_upsert_line()` and `_process_lines()` create/update master staging lines and invoke their import method.

### `controllers/master_mapping.py`

`MasterMappingMixin` owns the master field mappings, `_master_configs()`, master key normalization, and `_process_master_payload()`. It supports Customer, Vendor, UoM, Warehouse, Stock Item, and Non-Stock Item staging models.

### `controllers/transaction_mapping.py`

`TransactionMappingMixin` owns transaction header and product-line field mappings, `_transaction_configs()`, transaction key aliases, date conversion, and selection of the staging model/configuration for each transaction. Supported types include receipts, returns, inventory, transfers, shipments, consignment, and Kit Assembly.

### `controllers/operation_type_mapping.py`

`OperationTypeMappingMixin` resolves warehouse and stock picking operation types. Keeping this logic separate lets transaction field mapping call a focused operation resolver without embedding operation selection rules in each payload mapper.

### `controllers/transaction_processing.py`

`TransactionProcessingMixin` owns transaction processing behavior: flattening header/detail payloads, grouping records by document number, creating/updating headers and product lines, running specialized transaction processors, and invoking staging imports.

### `models/acumatica_webhook_log.py`

`action_process_to_staging()` replays the saved payload through the unified controller. The stored `webhook_type` remains `master` or `transaction`, and `webhook_name` remains the normalized mapping key, so the log's processing and reporting continue to distinguish the two domains.

## URL and webhook keys

Use the same URL pattern for both domains. Examples:

```text
/acumatica/webhook/customer
/acumatica/webhook/stock-item
/acumatica/webhook/po_receipt
/acumatica/webhook/shipment_completed
```

Hyphens and supported transaction aliases are normalized before the key is written to the log. The old domain-specific paths such as `/acumatica/customer/line/webhook` are removed; update any Acumatica endpoint configuration using those paths to the unified pattern.

## Data handling details

1. The route validates `X-API-Key` before accepting a payload.
2. The key is normalized and checked against master and transaction configuration.
3. The payload is stored as JSON in `acumatica.webhook.log` with state `pending`; company/event metadata is copied into log fields.
4. The Webhook Logs action or scheduler selects processing based on the stored domain and key.
5. The relevant mapper converts payload values to staging fields. Master lines use shared line upsert helpers. Transaction processing groups detail lines by document, upserts the header, replaces mapped product lines, and calls the staging model's `_do_import()`.
6. The log records the processing counts/result and transitions to processed or error according to the existing log flow.

Transaction staging and stock operation behavior remain in their existing staging models. The controller maps and dispatches data; it does not replace the business logic in those models.
