# Functional Guide

This guide explains how to configure Approval Types using Approval Base.

Approval Models are provided by developers and are automatically available after the corresponding business module is installed.

---

# Create Approval Type

Navigate to

```
Approval

↓

Approval Types
```

Click **Create** and fill in the following information.

```
Name

Code

Approval Model
```

Example

```
Name
Inventory Approval

Code
INV

Approval Model
Stock Inventory
```

The available **Approval Models** depend on the installed business modules and cannot be created manually by functional users.

---

# Configure Approval Flow

Approval Base supports two approval methods.

- Standard Approval
- Amount Based Approval

---

# Standard Approval

Leave **Amount Based Approval** unchecked.

Configure the Approval Lines.

Example

```
Sequence    Approver

1           Manager

2           Director

3           CEO
```

Approvers will approve the document sequentially according to the configured sequence.

---

# Amount Based Approval

Enable **Amount Based Approval**.

Instead of configuring Approval Lines directly, configure one or more Approval Ranges.

Example

```
Range Name        Min Amount     Max Amount

Small             0              5,000,000

Medium            5,000,001      20,000,000

Large             20,000,001     (Empty)
```

Leave **Max Amount** empty to indicate that the range has no upper limit.

Each Approval Range has its own Approval Lines.

Example

### Small (0 - 5,000,000)

```
1   Manager
```

### Medium (5,000,001 - 20,000,000)

```
1   Manager

2   Director
```

### Large (> 20,000,000)

```
1   Manager

2   Director

3   CEO
```

When a document is submitted, Approval Base automatically determines the correct Approval Range based on the document amount.

---

# Approval Process

The approval process follows the workflow below.

```
Draft

↓

Submit

↓

Waiting Approval

↓

Approved
```

or

```
Draft

↓

Submit

↓

Waiting Approval

↓

Rejected
```

For documents with multiple approvers, the document will remain in **Waiting Approval** until the last approver completes the approval process.

---

# Best Practices

- Create Approval Type for each business process.
- Use clear and descriptive Approval Type names.
- Configure approval sequences in ascending order.
- Avoid overlapping Amount Ranges.
- Leave **Max Amount** empty for the highest range.
- Test every Approval Type before using it in production.

---

# Troubleshooting

## Approval Type does not appear

Check that:

- The business module has been installed correctly.
- The corresponding Approval Model has been registered by the developer.
- An Approval Type has been created for that Approval Model.

---

## Wrong Approval Range is selected

Verify that:

- The Amount Ranges do not overlap.
- The document amount is correct.
- Min Amount and Max Amount are configured properly.

---

## Cannot submit the document

Verify that:

- An Approval Type has been selected.
- The Approval Type has valid Approval Lines.
- For Amount Based Approval, a matching Approval Range exists.

---

## Current Approver is incorrect

Verify that:

- Approval Lines are configured in the correct sequence.
- Each Approval Line has the correct approver assigned.