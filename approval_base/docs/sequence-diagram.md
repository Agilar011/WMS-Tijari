User
 │
 │ Submit
 ▼
Document
 │
 │ action_submit_approval()
 ▼
Approval Request
 │
 │ create_from_document()
 ▼
Generate Approval Lines
 │
 ▼
Waiting
 │
 │ Approve
 ▼
Approval Request Line
 │
 ▼
Current Line Updated
 │
 ▼
Last Approver?
 │
 ├── No
 │      ▼
 │   Waiting Next Approver
 │
 └── Yes
        ▼
Document._approval_approved()
        ▼
Document State = Approved