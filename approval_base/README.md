# Approval Base

Approval Base is a reusable approval framework for Odoo that provides configurable multi-level approval workflows for any business document.

## Features

- Reusable approval framework
- Multi-level sequential approval
- Amount-based approval
- Approval request management
- Current approver tracking
- Approval status tracking
- Easy integration with any business module

---

# Supported Features

✅ Multi Level Approval

✅ Sequential Approval

✅ Amount Based Approval

✅ Reusable Framework

---

# Project Structure

```
approval_base/

models/
    approval_model.py
    approval_type.py
    approval_request.py
    approval_mixin.py

views/
    approval_type_views.xml

security/
    ir.model.access.csv

data/
    approval_model_data.xml
    ir.sequence.xml
```

---

# Documentation

Developer Guide

```
docs/developer-guide.md
```

Functional Guide

```
docs/functional-guide.md
```

Architecture

```
docs/architecture.md
```