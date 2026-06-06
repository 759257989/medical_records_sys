Technical Challenge: AI Clinical Scribe Platform

Overview

You will build a provider-facing AI clinical documentation platform. The end user is a physician or clinical staff member. The core workflow: a provider either pastes a raw encounter transcript (e.g. a verbatim record of what was discussed during a visit), or types freeform clinical observations, and the AI transforms that input into a structured, professional SOAP note (Subjective, Objective, Assessment, Plan), including suggested ICD-10 diagnosis codes based on the clinical content.

The product must feel polished enough that a real physician would trust it with their clinical workflow.

Core Requirements

Authentication and Multi-Role Access

Implement a real login system with two distinct roles: Provider and Admin. Providers can only see and interact with their own encounters. Admins can view all providers' encounters, manage the provider roster, and modify note templates. Hard-code at least three provider accounts and one admin account for demo purposes. Use JWTs or session tokens, and be prepared to explain every layer of your auth implementation.

Encounter Workspace (Provider View)

The main interface for a logged-in provider. They can:

Start a new encounter by entering the patient's first name, last name, and date of birth
Paste a raw encounter transcript or type freeform clinical observations into a text area
Click Generate Note, at which point the AI streams a structured SOAP note back in real time using server-sent events or WebSockets (no full-page reloads, no waiting for a complete response before rendering begins)
The generated SOAP note must include a Subjective section, an Objective section, an Assessment section with at least one suggested ICD-10 code and description semantically matched to the clinical content, and a Plan section
The provider can edit the generated note inline before saving
Save the finalized note to the database
Patient History and Context Injection

When a provider starts an encounter for a patient who already has prior saved notes in the system (matched by first name, last name, and DOB), the AI must automatically retrieve and inject that patient's prior encounter history as context when generating the new SOAP note. The AI should reference relevant prior diagnoses or treatments where clinically appropriate. This retrieval must happen via a backend tool or function call during generation, not by stuffing prior notes into the frontend prompt. The AI should demonstrably behave differently for a returning patient versus a first-time patient.

Note Versioning and Audit Trail

Every time a provider edits and re-saves a note, a new version must be written to the database. The prior version must never be overwritten or deleted. Providers can view the full version history of any note, including who saved each version and at what time. This version history must be stored in and retrieved from AWS RDS, not in memory or in a flat file.

ICD-10 Code Search

Implement a standalone ICD-10 search widget within the encounter workspace. The provider can type a symptom or condition in plain English, and the system returns the top semantically relevant ICD-10 codes using either a vector similarity approach or an AI call. The provider can click any result to append it to the Assessment section of the open note. Hard-code or embed a reasonably sized subset of ICD-10 codes (at minimum 200 to 300 entries) to power this. Do not rely on an external ICD-10 API.

Admin Dashboard

A separate view accessible only to Admin accounts. Must support:

Viewing all encounters across all providers, filterable by provider and date range
Adding and deactivating provider accounts
Managing a library of note templates, which are structured prompts that shape how the AI generates SOAP notes for different encounter types (e.g. orthopedic follow-up vs. new patient evaluation vs. urgent care visit). Admins can create, edit, and delete templates. Providers select a template before generating a note, and the AI must visibly behave differently depending on which template is active.
Changes to templates must take effect immediately. If a provider has the encounter workspace open and the admin updates the active template, the next generation the provider runs must use the new template without requiring a page refresh.
Session Persistence

If a provider is mid-encounter (transcript entered, note not yet saved) and refreshes the page or closes and reopens the browser, the in-progress draft must be restored from the database. The provider should be able to continue exactly where they left off. This must work across devices, meaning that logging in from a different browser should restore the same draft state.

Non-Happy-Path Scenarios

Your system must handle at least two non-happy-path scenarios and demonstrate both in your walkthrough. Examples: a provider submits a transcript that contains no clinically meaningful content (the AI should respond gracefully rather than generate a hallucinated SOAP note); a provider attempts to save a note while their session has expired (handle this without data loss); an admin deactivates a provider account while that provider has a draft open (define and implement a reasonable behavior). You choose the two scenarios, but they must be substantive and clearly demonstrated.

Infrastructure Requirements

Hosted on AWS EC2. The application must be accessible over HTTPS with a valid SSL certificate. Self-signed certs are not acceptable.
All persistent data, including encounters, note versions, patients, providers, templates, and audit logs, must live in AWS RDS (PostgreSQL or MySQL). No SQLite, no local files, no in-memory stores for anything that needs to survive a server restart.
Your schema must be normalized and defensible. You will be asked to walk through your ERD during the code review portion of the video.
Implement database connection pooling correctly. Your EC2 instance must not open a new DB connection on every request.
All environment secrets (DB credentials, API keys) must be managed via AWS Secrets Manager or Parameter Store. No hardcoded credentials anywhere in the codebase, including in .env files committed to the repo.
Your EC2 instance must sit behind a reverse proxy such as nginx. The application process must not be directly exposed on port 80 or 443.
Your RDS instance must not be publicly accessible. It must only accept connections from within the VPC. Be prepared to demonstrate this in your code walkthrough.
Evaluation Criteria

Correctness and reliability of the core AI scribe workflow end to end
Streaming implementation: does note generation render progressively, or does it feel like a spinner followed by a content dump?
Database design: schema quality, normalization, indexing decisions, and whether you can defend every table and relationship
Infrastructure rigor: secrets management, VPC isolation of RDS, connection pooling, reverse proxy configuration
UI quality: this must look like something a physician would actually open. Clinical tool aesthetics are clean, dense, and high-trust, not consumer-app bubbly.
Prioritization: does the build feel complete even if some features are unfinished, or does it feel broken in obvious places?
Non-happy-path handling: are edge cases handled gracefully, or do they produce errors or nonsensical AI output?
Code walkthrough quality: can you explain every architectural decision clearly, including why you chose your AI model and how you structured your prompts?
This is intentionally a large scope. We do not expect every feature to be perfect. We expect the core scribe workflow, streaming, RDS persistence, and infrastructure requirements to be airtight, and we expect the rest to be prioritized intelligently. An incomplete build that feels finished to a user and has a solid infrastructure foundation will outscore a complete build with sloppy infrastructure and a broken UI.

Pioneer Features

You will stand out if you build one or two features not described above. Strong candidates have added things like: provider-specific writing style learning, where the AI adapts to how a specific provider tends to phrase their notes over time based on their history in the database; automatic flagging of clinical red flags in the transcript before note generation; a diff view between note versions so providers can see exactly what changed; or a bulk export of all encounters for a given patient across all visits as a single structured PDF.