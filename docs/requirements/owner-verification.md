# Owner verification boundary

ChezPG currently stores owner verification submissions as metadata only:
relationship type, optional submission notes, status, and submission/review
timestamps. The API does not collect identity documents, perform SMS/email OTP,
or claim that an owner has been independently identified.

Administrators must review supporting evidence out of band before marking an
owner verified. The current administrator credential is a shared development
API key; it does not identify an individual reviewer, so no reviewer identity
is stored. Replace this gate with individually authenticated administrator
accounts and authorization before production.

The `owner_verifications` record represents the latest submission. A rejected
owner may submit again; the latest status and notes replace the previous
submission's values. Preserve a separate audit history before production if
review decisions must be immutable.

Private document handling is not implemented. Before adding it, select private
storage, define allowed file types and size limits, restrict access to
authorized reviewers, avoid public URLs and logs, and establish retention and
deletion policies. Never expose document contents or private storage paths in
public API responses.

The additive database migration leaves existing PG rows with `owner_id = NULL`.
They cannot be managed by an owner or approved until an administrator has
verified an owner and deliberately assigned the listing to that owner.
