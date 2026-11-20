# Security boundaries and known limits

The local application binds to 127.0.0.1 only. HTTP APIs require a same-site session cookie; writes also require a CSRF token. The Chrome WebSocket accepts Chrome-extension origins and a single-use expiring pairing code or session reconnect token. Neither website scripts nor model-generated text can supply arbitrary JavaScript/CDP commands through the connector: its operations are fixed in the extension source.

Task goal, capabilities, URL scope, duration, and approved action are trusted inputs. Page text, metadata, attachments, and model outputs are untrusted. d1 selects a typed candidate ID. The execution layer independently checks scope. Approvals expire after five minutes and bind to the prepared page/form fingerprint. A changed form invalidates approval. A uncertain submission is not replayed. Restarted tasks require a new read-only run rather than replaying writes.

## Existing Chrome mode

The selected tab uses existing cookies and login naturally, without cookie export or password-vault access. The extension requires debugger, activeTab, tabs, storage, and localhost host permissions. `tabs` permits tab metadata; implementation sends only the explicitly selected tab to the backend. The debugger permission is powerful: review the local source before installing. No remotely hosted code is used. Chrome displays an attachment indicator; disconnect detaches it. The app never closes the user's Chrome.

Only the selected main document is exposed. Sensitive input controls are omitted from candidates and visually masked in screenshots; this is not comprehensive sensitive-data detection. Page text may contain account information. Task evidence stays on this computer. Connected tasks cannot opt into plaintext public indexing.

Every connected field edit or button interaction requires review, since an input/change event may autosave. This **does not intercept existing page traffic**: background requests, redirects, service workers, site JavaScript, and GET side effects are still possible. Domain/private-address checks occur before issuing commands and before inspecting newly observed pages. Unlike isolated mode, Chrome's own DNS/network stack is not pinned by the proxy, and a redirect may reach a new site before the next scope check stops inspection. Do not describe this adapter as network-isolated or safe for arbitrary hostile applications.

Passwords, OTP, CAPTCHA, and unsupported controls require the user's manual interaction. No approval grants arbitrary tools, filesystem reads, account access, or code execution. The connector implements no cookie-export, password-reading, shell, or filesystem operation.

## Isolated mode

Playwright uses a temporary profile and a validating proxy that connects to vetted IP addresses. Private/loopback/reserved addresses and nonstandard ports are blocked unless explicitly granted as exact origins in Settings. Write requests and unsolicited downloads are blocked; preparing fields freezes network requests until a reviewed action. The browser sandbox and TLS verification remain enabled. These restrictions may break some websites, particularly authenticated applications.

## Storage

Task payloads, source records, uploads, screenshots, decision logs, and exports are encrypted with Fernet; the key is wrapped by Windows DPAPI. The key protects at rest, not against another process running as the same Windows user. Filenames/SQLite metadata and service logs are not all encrypted. Optional public-page FTS indexing is plaintext and disabled by default; it is disallowed for connected Chrome tasks. Finished tasks expire by retention setting; uploaded attachments currently require manual workspace management and are not automatically expired with their originating task.

Quarantined downloads are never executed. Selected attachments alone do not authorize external upload. The API serves encrypted artifacts only through the local authenticated session. Generated HTML reports escape source text, and CSV exports guard against formula injection.

This is a locally tested first release, not a guarantee of correctness on every website or a completed independent security audit.
