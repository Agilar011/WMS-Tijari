# Developer Guide

This guide explains how to integrate **Approval Base** into a business module.

---

# Step 1

## Inherit `approval.mixin`

Add `approval.mixin` to your business model.

```python
class StockInventory(models.Model):
    _name = 'stock.inventory'
    _inherit = [
        "approval.mixin",
    ]
```

This mixin provides the approval engine and common approval fields.

---

# Step 2

## Register Approval Model

Every business model that supports Approval Base must be registered in `approval.model`.

Create a new XML data file, for example:

```
inside data/approval_model_data.xml
```

Register the model:

```xml
<odoo>

    <record id="approval_model_stock_inventory"
            model="approval.model">

        <field name="name">Stock Inventory</field>

        <field name="model_id"
               ref="stock_inventory.model_stock_inventory"/>

    </record>

</odoo>
```

Then include the XML file in your module manifest.

```python
'data': [
    'data/approval_model_data.xml',
]
```

After installing or upgrading the module, the business model will automatically become available in **Approval Type**.

---

# Step 3

## Override `approval_type_id`

Override the field so users can only select Approval Types that belong to the current business model.

```python
approval_type_id = fields.Many2one(
    "approval.type",
    string="Approval Type",
    domain="[('approval_model_id.model','=','stock.inventory')]",
)
```

Replace `"stock.inventory"` with your own model.

---

# Step 4

## Synchronize Document State

Approval Base manages the approval process only.

Each business document is responsible for updating its own state.

Override the following methods if needed.

```python
def _approval_submitted(self):
    self.state = "waiting"

def _approval_approved(self):
    self.state = "approved"

def _approval_rejected(self):
    self.state = "rejected"
```

These methods are optional and should be implemented according to the business requirements.

---

# Step 5

## Amount Based Approval (Optional)

If the document supports amount-based approval, override:

```python
def _get_approval_amount(self):
    return self.amount_total
```

Approval Base will use this value to determine the appropriate approval range.

If this method is not overridden, the default amount is:

```python
0
```

---

# Step 6

## Submit Approval

Create a button that submits the document for approval.

```python
def action_submit(self):
    self.action_submit_approval()
```

---

# Step 7

## Approve Document

Create an Approve button.

```python
def action_approve(self):
    self.ensure_one()
    self.approval_request_id.action_approve()
```

---

# Step 8

## Reject Document

Create a Reject button.

```python
def action_reject(self):
    self.ensure_one()
    self.approval_request_id.action_reject()
```

---

# Step 9

## Display Approval Information

It is recommended to display the following fields on the form view.

```
Approval Type

Approval State (Optional)

Current Approver

Approval Request Lines
```

Approval Request Lines can be displayed using:

```python
approval_line_ids
```

This allows users to see:

- Approval sequence
- Approver
- Approval status
- Action date
- Remarks (if implemented)

---

# Optional

Hide action buttons based on the document state or current approver.

Example:

```
Submit

Visible only when the document is in Draft.
```

```
Approve

Visible only for the current approver.
```

```
Reject

Visible only for the current approver.
```

---

# Extension Methods

Approval Base provides several extension methods that can be overridden by business modules.

```
_create_approval_request()

action_submit_approval()

_get_approval_amount()

_approval_submitted()

_approval_approved()

_approval_rejected()
```

These methods allow each business module to customize its approval behavior while keeping the approval engine reusable.

---

# Integration Checklist

Before using Approval Base, make sure the following steps have been completed.

- Inherit `approval.mixin`
- Register the business model in `approval_model_data.xml`
- Override `approval_type_id`
- Implement document state synchronization (optional)
- Override `_get_approval_amount()` if using amount-based approval
- Add Submit, Approve, and Reject actions
- Display approval information on the form view
- Upgrade the module
- Configure the Approval Type