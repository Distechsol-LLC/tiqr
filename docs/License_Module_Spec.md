# Offline License Module: Portable Spec (v3)

A self-contained spec for an offline licensing scheme, written so you can rebuild it without the
original source.

**How it works:** The customer's install produces a machine ID and a request code. The vendor issues
a signed key from that request. The customer pastes `base64(payload).base64(signature)` into the
app. The product verifies the signature with a public key compiled into its build, on every status
read. There's no license server and no telemetry.

**Trials are not special.** The product never issues a trial itself. A trial is a vendor-signed key
with `type: 'trial'` and a 30-day `expiresAt`, so the expiry lives inside the signature.

**Limit:** This is not tamper-proof against someone with root on the customer's machine. See section 9.

**What changed from v2:** The payload has no `maxUsers` (no seat limit is enforced, so the field was
removed). The machine is checked on every status read, not only at activation. Error codes are
lowercase slugs. The vendor tool, the history view, and the wall are described as built. Section 9
records the trade-off that the every-read machine check creates.

---

## 1. Non-negotiable design rules

1. **Own key pair.** Generate a new RSA-2048 pair for each product. Put a `product` field in the payload and check it during verification. Never share keys across products.
2. **Verify on every status read.** The database holds a cache. It has no authority over expiry, type, or the machine the key was issued for.
3. **No self-issued trials.** Startup never creates a license. Trials come from the vendor like any other key.
4. **Strict machine check.** A missing or empty `machineId` is a rejection, never a wildcard. A key whose `machineId` differs from this machine's fingerprint is refused on every read (see section 9 for the cost).
5. **Fail closed.** Unknown status means blocked.

---

## 2. Key format and cryptography

Port this as-is. It needs only a standard RSA library and a SHA-256 hash. Node's `crypto`, Python's
`cryptography` (`padding.PKCS1v15()`), Go's `rsa.VerifyPKCS1v15`, and .NET's
`RSA.VerifyData(..., RSASignaturePadding.Pkcs1)` all produce compatible results.

| Parameter | Value |
|---|---|
| Algorithm | RSA-SHA256 with **PKCS#1 v1.5** (not PSS) |
| Modulus | 2048 bits, so the signature is 256 bytes (344 base64 characters) |
| Keys | Public: SPKI PEM. Private: PKCS#8 PEM |
| Format | `base64(payload bytes).base64(signature)`. One dot, two parts. **Not a JWT** |
| Signed data | The raw bytes of the payload JSON |

A typical key runs about 600–700 characters, depending on field lengths.

### Payload

```text
product     string   constant for the program
type        enum     'trial' | 'standard'
licensedTo  string   the holder, shown on the wall when the key has ended
issuedAt    string   ISO 8601 with a UTC offset
expiresAt   string   ISO 8601 with a UTC offset, fixed at issuance
machineId   string   32 uppercase hex
requestId   string   16 uppercase hex, echoed from the request
```

Every field is required. A missing field, a wrong type, an unknown `type`, or a timestamp without an
offset makes the key invalid.

### Signing (vendor)

```text
bytes     = utf8(JSON.stringify(payload))
signature = RSA-PKCS1v15-SHA256-sign(privateKey, bytes)   // 256 bytes
key       = base64(bytes) + "." + base64(signature)
```

### Verifying (product)

```text
parts = trim(licenseKey).split(".")
reject unless parts has exactly 2 non-empty items         // no extra dot
bytes = strict-base64-decode(parts[0])
sig   = strict-base64-decode(parts[1])
reject unless length(sig) == 256                          // 2048-bit modulus
reject unless RSA-PKCS1v15-SHA256-verify(publicKey, bytes, sig)
payload = parse-JSON(bytes)                               // only after the signature passes
reject unless payload is valid (section 2, Payload) and payload.product == PRODUCT_ID
return payload
any exception = reject
```

**Keep two properties in any rewrite:** JSON parsing runs only after the signature checks out, and
the signature covers the payload bytes. Rewrites usually break this by moving to a JWT library or a
different encoding.

### Key generation

Generate an RSA-2048 pair with PKCS#8 private and SPKI public PEM encodings. The public key is a
string constant compiled into the product build. Rotating it means rebuilding and redelivering the
product, and it voids every issued key. Don't document a key file that the code never reads.

---

## 3. Machine ID

```text
addresses = sorted(set(every network interface's hardware address, lowercase))
            minus the empty and all-zero addresses
parts     = [hostname, lowercase(OS name), architecture, ...addresses]
machineId = uppercase(first 32 hex chars of SHA-256(join(parts, "|")))
```

- **Sort and de-duplicate the addresses.** Enumeration order is not guaranteed between boots.
- **Drop the zero address.** It adds nothing and varies between runtimes.
- **Ignore a random placeholder address.** Some runtimes invent an address when the OS reports none. A
  placeholder has the multicast bit set; skip it. If no address remains, the fingerprint uses the
  other fields alone.
- **Interfaces are read, not chosen.** The reference includes every interface the OS lists, virtual
  ones too (container bridges, VPN tunnels, VM adapters). Creating or removing one changes the
  fingerprint. Section 9 covers the consequence.
- **Inputs are owner-controlled.** Hostnames and addresses can be changed. Accept this for customers
  with root on their own server, and don't count the fingerprint as protection.

---

## 4. Request codes and activation

### Request code

The customer never types a machine ID by hand. The product generates a request code, which the
customer sends to the vendor.

```text
request = {
  product,
  requestId:   16 random hex characters, uppercase,
  machineId:   this machine's fingerprint,
  requestType: 'trial' | 'standard',
  contact?:    optional string
}
code = base64(utf8(JSON.stringify(request)))
```

Any signed-in role can generate a code, so a viewer who sees the wall can pass it to an administrator.

The request code is untrusted input. The vendor validates every field strictly: `product` must match,
`machineId` must be 32 uppercase hex, `requestId` must be 16 uppercase hex, `requestType` must be one
of the allowed values, and `contact`, if present, must be a string. The `requestId` is echoed into
the signed payload, which links the request to the key.

### Activation

Only an administrator may activate. Steps, in order:

1. Verify the key (section 2). Failure: `license_bad_signature`, 400.
2. Check the machine (section 4, activation). Failure: `license_wrong_machine`, 400.
3. Reject a key whose `expiresAt` is not in the future. Failure: `license_already_expired`, 400.
4. In one transaction: if the key is a trial and the stored license is a live paid one, refuse with
   `license_trial_over_paid`, 409. Otherwise deactivate every stored key, then store the new one as
   active, caching `expiresAt` and `licensedTo`.

```text
machine check: payload.machineId must be non-empty and equal machineId()
               otherwise refuse, with the first 8 characters of both IDs in the message
```

**The order matters.** A customer who pastes a wrong or expired key can't knock out a working
installation, because the old license is deactivated only after every check passes.

---

## 5. Data model and status

```text
license
  id           integer, primary key, autoincrement
  license_key  text            the signed blob; never varchar, because keys run past 500 characters
  is_active    boolean         exactly one row is active at a time
  activated_at timestamp
  expires_at   timestamp       cache only
  licensed_to  text            cache only
```

- **`license_key` must be `text`.** A truncated blob never verifies again, and some databases truncate
  silently in non-strict modes.
- **Never delete rows.** Activation deactivates the current row and inserts a new one, so the table
  stays a history. Deactivation (an admin's manual swap) only clears `is_active`.

### Status

```text
state:          'none' | 'invalid' | 'expired' | 'active'
is_valid:       true only for 'active'
machine_id:     present in every state
type:           present when a key verifies
licensed_to:    present when a key verifies
expires_at:     present when a key verifies
days_remaining: whole days left, rounded up; 0 when expired
```

```text
status():
  machine = machineId()
  row = active row, if any; else return none
  payload = verify(row.license_key) and payload.machineId == machine
            ; if not, return invalid     // the signature, product, and machine are all checked here
  if payload.expiresAt <= now: return expired (with holder and expiry)
  state = active
  return state, type, holder, expiry, daysRemaining = ceil((expiresAt - now) / 1 day)
```

A trial is an `active` state whose `type` is `trial`. Read the type from the signed payload. Never derive it from a string prefix or from the cache.
The cached columns feed history and listings only; nothing reads them to decide access.

---

## 6. Enforcement

### Server: default-deny gate

Every API route requires a valid license, except a named exempt list: health, branding and logo
(public assets), login, logout, the session read, the license status, the request-code read, and
activation. The gate is attached once to the whole API router, so a route added later is protected
until someone lists it as exempt. An opt-in list of protected routes fails open whenever someone
forgets a decorator.

A refusal returns 403 with code `license_required` and the state in the detail, for example
`A valid license is required (expired)`.

### Client: the gate

The app shell decides what to show, in this order:

1. Not signed in: the sign-in page.
2. The status check failed (network or server error, not a sign-in problem): a retry screen. Unknown
   is blocked.
3. Status not yet loaded: a loading state.
4. `is_valid` is false: the wall.
5. Otherwise: the application.

The gate sits in the shell, so no page mounts, and so fetches no data, before a valid status arrives.
An unauthenticated answer is not a license failure; it sends the user to sign-in.

When any API request returns `license_required` (for example, a key ends mid-session), the client
refreshes the status, and the wall appears without a reload.

### Wall contents

- **Banner:** the reason. `none` says activation is needed. `expired` and `invalid` give a red banner;
  `invalid` says the stored license couldn't be verified. When an expired key is still readable, show
  the holder and the expiry.
- **Request area:** a trial or standard choice (default trial), the request code in monospace with a
  Copy button, and a visible error if the code can't be fetched.
- **Activation area:** a paste box and an Activate button for administrators only. Everyone else sees
  the request area and a note that an administrator must activate.
- **Machine ID:** shown so that the customer can quote it.
- **Always:** a sign-out button and a language switcher.

Show action errors as text. Map the server's codes to translated messages, and fall back to the
server's own detail text for any code the client doesn't know. Never swallow a failure with a bare
log statement.

---

## 7. HTTP surface and error codes

| Route | Access | Purpose |
|---|---|---|
| `GET /license/status` | any signed-in role | The status above, including `machine_id` |
| `GET /license/request-code?type=trial\|standard` | any signed-in role | A request code to send to the vendor; default `standard` |
| `POST /license/activate` | admin, with CSRF | Submit a key; returns the new status. A refused key leaves the current license in place |
| `POST /license/deactivate` | admin, with CSRF | Retire the active key for a manual swap. Resets nothing else; returns 204 |
| `GET /license/history` | admin | Every stored row, newest first. Each key is shown as its first 8 and last 6 characters |

Error codes are lowercase slugs in the response's `code` field. The client translates them.

| Code | HTTP | When |
|---|---|---|
| `license_required` | 403 | Any gated route without a valid license |
| `license_bad_signature` | 400 | The key doesn't verify, or isn't for this product |
| `license_wrong_machine` | 400 | The key is for another machine; the message has the first 8 characters of both IDs |
| `license_already_expired` | 400 | The key's expiry is not in the future |
| `license_trial_over_paid` | 409 | A trial was pasted over a live paid license |

---

## 8. Vendor side

### Issuance rules

- **Trial:** `type` is forced to `trial`, `expiresAt` is `issuedAt + 30 days`, and whatever the
  operator passed for days is ignored. **Refuse if the history already has a non-revoked trial for
  this `machineId`.** Warn, but don't refuse, when the `contact` already had a trial elsewhere.
- **Standard:** the operator sets `licensedTo` and the number of days. Both are required,
  and days must not be negative. Use a real parser for numbers, so that `0` means zero days, not
  "unset".
- **A trial request** must be answered with a trial. Refuse any other type for it.
- **Always** validate the request code strictly and echo its `requestId` into the payload.
- **Before issuing**, check that the signing key's public half matches the one compiled into the
  product. Refuse on a mismatch. Never generate a key pair silently; fail if the key folder is missing.
- **Supersede** the machine's previously active history records when a new key is issued.
- **Normalize optional fields to null** before serializing, since serializers drop undefined values.

### Command line

```text
issue-license --request <CODE> --type trial
issue-license --request <CODE> --type standard --licensedTo "Company" --days 365
```

Use an argument parser that rejects unknown options and does not accept abbreviations of them.

### History schema

```text
IssuanceRecord
  id          string
  status      'active' | 'superseded' | 'revoked'
  requestId   string
  machineId   string
  contact     string, optional
  type        'trial' | 'standard'
  licensedTo  string
  issuedAt    string
  expiresAt   string
  supersedes  string, optional
  note        string, optional
  licenseKey  string              a working credential
```

The history is also the **trial registry**. Lose it and every machine becomes eligible for a new
trial. It also holds customer names and working keys. Back it up, restrict access (owner-only file
mode on POSIX systems, or ACLs or a DPAPI-backed store on Windows), and keep it out of source control
and off the network.

### Local tooling

- Bind any web tool to `127.0.0.1` **and** check the `Host` and `Origin` headers. Binding alone doesn't
  stop DNS rebinding.
- Keep the vendor key folder outside the repository, the build, and any artifact.

---

## 9. Accepted limitations and trade-offs

These can't be closed offline. You can raise their cost, but not drive it to zero.

- **The every-read machine check has a cost.** A copied installation is refused on the new machine,
  which is the intent. But any change to the fingerprint inputs ends a valid license until it is
  reissued: a hostname change, an interface added or removed, a VPN or container bridge or VM adapter
  that appears or disappears, or a hardware swap. Section 3 lists the virtual interfaces the reference
  includes. This is the current behaviour, and the tolerance rule is an open decision (section 10).
- **Machine-ID rotation gets a new trial.** A changed hostname or address looks like a new machine.
  Mitigate on the vendor side: one trial per contact or company, and manual review of repeat requests.
- **Clock rollback extends a license.** Expiry is compared against the local clock. A monotonic "latest
  time seen" check raises the cost, but its record lives on the same machine.
- **Forging the embedded key.** Anyone can remove the embedded public key and sign with their own.
  Protecting against this needs a signed updater. Per-file hashes only protect against corruption.
- **No revocation.** Revocation needs a design decision up front: short licenses with scheduled
  reissuance, a serial number checked against a signed list, or an online heartbeat. Rotating the key
  pair kills every license at once.
- **Owner-controlled fingerprint.** Anyone with root can change the inputs (section 3). The fingerprint
  identifies a machine; it does not protect one.

---

## 10. Porting checklist

**Core**
- [ ] New RSA-2048 pair; private key only on the vendor's machine
- [ ] `product` in the payload, checked during verification
- [ ] Every payload field validated; timestamps require a UTC offset
- [ ] Sign and verify raw bytes; check signature length
- [ ] Trial is vendor-signed; startup issues nothing
- [ ] Request code with random `requestId`, validated on the vendor side
- [ ] `requestId` echoed into the signed payload
- [ ] Machine fingerprint sorted, de-duplicated, and free of placeholder addresses

**Status and enforcement**
- [ ] `status()` verifies signature, product, and machine on every read; columns are cache only
- [ ] `machine_id` present in every status state
- [ ] Default-deny gate on the whole API with a named exempt list
- [ ] Gate in the app shell; no page fetches before a valid status
- [ ] Client refreshes status on `license_required`
- [ ] Sign-out and language switcher on the wall
- [ ] Action errors shown to the user, with translated codes

**Vendor side**
- [ ] History backed up, restricted, and used as the trial registry
- [ ] Trial rule: one non-revoked trial per machine ID (and warn on a repeat contact)
- [ ] Public-key match preflight before signing
- [ ] Argument parser rejects unknown options
- [ ] Local tools: Host/Origin allowlist; fail on missing keys

**Open decisions**
- [ ] Machine-ID tolerance: keep strict every-read matching, or exclude virtual interfaces and add a
      grace period. Strict matching ends a license on a VPN, container, or VM change
- [ ] Revocation strategy
- [ ] Clock tolerance and monotonic check
- [ ] Trial clock starts at issuance (current design) or at activation (needs an extra signed field)
- [ ] Seat limits: none in v3. If one is added, enforce it at user creation, not only in message text,
      and add the field back to the payload
- [ ] Which users count as seats, if seat limits are added
