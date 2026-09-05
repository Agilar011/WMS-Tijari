# Architecture

## Overview

Approval Base is a reusable approval framework designed for Odoo business modules.

Instead of implementing approval logic repeatedly in every module, Approval Base provides a common approval engine that can be integrated into any business document through `approval.mixin`.

The framework separates:

- Approval configuration
- Approval execution
- Business document implementation

This separation allows the approval engine to remain reusable while each business module manages its own business logic.

---

# Architecture Overview

```
                   +----------------------+
                   |  Business Document   |
                   | (stock.inventory)    |
                   +----------+-----------+
                              |
                              | approval.mixin
                              |
                              v
                   +----------------------+
                   |  Approval Request    |
                   +----------+-----------+
                              |
                              |
                              v
                   +----------------------+
                   | Approval Request Line|
                   +----------------------+

                              ▲
                              |
                              |
                   +----------+-----------+
                   |   Approval Type      |
                   +----------+-----------+
                              |
            +-----------------+-----------------+
            |                                   |
            | Standard Approval                 | Amount Based Approval
            |                                   |
            v                                   v
     Approval Lines                   Approval Ranges
                                              |
                                              v
                                      Approval Lines

                              ▲
                              |
                              |
                   +----------------------+
                   |   Approval Model     |
                   +----------------------+
```

---

# Core Components

## Approval Model

`approval.model` is a registry of business documents that support Approval Base.

Instead of exposing every record from `ir.model`, only registered business models are available for approval configuration.

Approval Models are registered by developers through XML data.

Example:

```xml
<record id="approval_model_stock_inventory"
        model="approval.model">

    <field name="name">Stock Inventory</field>

    <field name="model_id"
           ref="stock_inventory.model_stock_inventory"/>

</record>
```

This approach ensures that only supported business documents appear in Approval Type.

---

## Approval Type

Approval Type defines how a document should be approved.

Each Approval Type belongs to one Approval Model.

Approval Base supports two approval methods:

- Standard Approval
- Amount Based Approval

---

### Standard Approval

A fixed approval sequence is used for every document.

```
Approval Type

↓

Approval Lines

↓

Manager

↓

Director

↓

CEO
```

Every submitted document follows the same approval flow.

---

### Amount Based Approval

Approval flow is selected based on the document amount.

```
Approval Type

↓

Approval Ranges

↓

Approval Lines
```

Example:

```
0 - 5,000,000

↓

Manager
```

```
5,000,001 - 20,000,000

↓

Manager

↓

Director
```

```
>20,000,000

↓

Manager

↓

Director

↓

CEO
```

Approval Base automatically selects the appropriate Approval Range during submission.

---

## Approval Request

Approval Request is the runtime representation of an approval process.

When a document is submitted:

- A new Approval Request is created.
- Approval Lines are generated from the selected Approval Type.
- The document enters the approval process.

Unlike Approval Type, Approval Request stores transaction data.

---

## Approval Request Line

Approval Request Line represents one approval step.

Each line stores:

- Sequence
- Approver
- Status
- Action Date

Approval progresses sequentially from one line to the next until all approvers have completed their actions.

---

# Approval Flow

The approval lifecycle is illustrated below.

```
Business Document

↓

Submit

↓

Create Approval Request

↓

Generate Approval Lines

↓

Waiting Approval

↓

Approve / Reject

↓

Completed
```

If the document has multiple approvers, Approval Base automatically determines the current approver and advances the approval sequence after each approval.

---

# Business Document Integration

Business modules integrate with Approval Base by inheriting `approval.mixin`.

```
Business Document

↓

approval.mixin

↓

Approval Engine

↓

Approval Request

↓

Business State Updated
```

Approval Base manages the approval workflow only.

Business modules remain responsible for updating their own document state.

This separation keeps the framework generic and reusable.

---

# Extension Methods

Approval Base provides several extension methods that allow business modules to customize their behavior.

```
_get_approval_amount()

_approval_submitted()

_approval_approved()

_approval_rejected()
```

Example:

```python
def _approval_approved(self):
    self.state = "approved"
```

These methods enable Approval Base to work with different business documents without embedding business-specific logic into the framework.

---

# Design Principles

Approval Base follows several design principles.

## Separation of Responsibilities

Approval Base handles:

- Approval workflow
- Approval sequence
- Current approver
- Approval status

Business modules handle:

- Business validation
- Business state
- Business actions

---

## Reusability

The approval engine is implemented once and shared by multiple business modules.

New business modules only need to integrate with `approval.mixin`.

---

## Configuration Driven

Approval behavior is configured through Approval Types instead of source code.

Functional users can modify approval flows without changing application logic.

---

## Extensibility

Business modules can customize approval behavior through extension methods without modifying the framework itself.

---

# Integration Flow

```
Developer

↓

Register Approval Model

↓

Inherit approval.mixin

↓

Add Approval Fields

↓

Implement Extension Methods

↓

Upgrade Module

↓

Functional User

↓

Create Approval Type

↓

Configure Approval Flow

↓

Users Submit Documents

↓

Approval Base Executes Approval Process
```

---

# Summary

Approval Base separates approval configuration, approval execution, and business logic into independent components.

This architecture allows multiple business modules to share a single approval engine while maintaining flexibility, reusability, and consistency across the system.