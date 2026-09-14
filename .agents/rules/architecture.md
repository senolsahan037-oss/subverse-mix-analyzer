# SubverseLab Architecture & Development Guidelines

This document outlines the core architectural principles, deployment rules, and development constraints for the SubverseLab ecosystem. All AI agents MUST strictly adhere to these rules.

## 1. Architecture
- **subverselab-v2 = Presentation Layer only.** The core website is strictly a frontend/showcase.
- **Microservices:** Every AI tool must be an independent repository or at least a separately deployable service.
- **Decoupling:** Services must never depend on each other's codebase. Communication is strictly via HTTP API.

## 2. Deployment
- **Independent Services:** Every AI tool is deployed to its own dedicated Google Cloud Run service.
- **Independent Versioning:** Each service has its own versioning (e.g., `mix-analyzer:v1`, `synthpulse:v2`).
- **Isolation:** Deploying one tool cannot and must not affect or break another tool or the main website.

## 3. Database (Firebase / Firestore)
- **Frontend Restrictions:** The frontend accesses Firestore directly ONLY for essential collections (e.g., Auth, Products listing).
- **Backend Authority:** Quota tracking, rate limits, and usage statistics are strictly written and managed by the backend (Cloud Run).
- **Client Security:** The client application (frontend) must never be allowed to modify quota documents or rate limit counters.

## 4. Security
- **API Keys:** Never expose backend or third-party API Keys in the frontend code.
- **Service Accounts:** Google Cloud Service Accounts are only used securely inside the backend Cloud Run environments.
- **Firestore Rules:** Firestore Security Rules must be strict enough to prevent users from bypassing backend logic or altering limits.

## 5. Rate Limit (CRITICAL)
- **Immutable Rules:** IP/User limits (e.g., 1 free analysis per IP per day) are unchangeable business rules in the backend.
- **No Bypassing:** Terms like "temporary disable", "bypass limit for testing" (in production), or "remove quota" are strictly forbidden. The limits must be enforced at all times.

## 6. Language
- **User Interface:** All UI text, logs, system warnings, error messages, and quota notifications MUST be in English.
- **Code Comments:** Code comments should also be written in English.

## 7. Data Protection
- **No Bulk Deletion:** Bulk deleting collections (like Users or Products) is strictly prohibited.
- **Schema Changes:** Database schemas cannot be changed without an explicit migration script.
- **Production Integrity:** Never perform manual deletion operations on the production Firestore database.

## 8. Admin Panel
- **Link Management Only:** The admin panel is strictly for managing metadata, external Cloud Run URLs (`externalUrl`), and file download links.
- **No Embedded Code:** The actual code of AI tools is never embedded into the main website's codebase.
- **Integration:** The "Iframe or New Tab" policy is strictly maintained for connecting tools to the frontend.

## 9. Future Implementations
- **No Monolithic Additions:** New AI tools will NEVER be added to the existing `subverselab-v2` project.
- **New Infrastructure:** A new AI tool requires a new repository and a new Cloud Run service.

## 10. AI Independence Rule
- **Core Architecture Protection:** AI tools must never modify the core website architecture. If a new feature requires backend logic, it must be implemented as an independent service and integrated through APIs or external links.
