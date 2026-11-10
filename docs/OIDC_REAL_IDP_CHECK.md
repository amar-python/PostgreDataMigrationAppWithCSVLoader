# Checking OIDC sign-in against the real identity provider (#113)

One sign-in against the deployment's real IdP (Keycloak or Entra ID) proves what no automated test can: that **its** certificate is trusted, **its** issuer and audience match the configuration, and **its** tokens carry a claim that names a local user. This is the procedure and the script for it. It needs access to the IdP, and a person who can sign in there.

## What is already tested, and what is not

| | Where | Status |
|---|---|---|
| Signature, issuer, audience, expiry and claim checks | `tests/system/test_oidc.py` (file:// key set) | Automated |
| The `https://` key fetch (PyJWT's `PyJWKClient`), key rotation, an untrusted certificate, an IdP that is down or hangs, the sign-in through the API | `tests/system/test_oidc_https.py`, against a local TLS server | Automated (#113) |
| This script's checks and their hints | `tests/system/test_check_oidc.py` | Automated |
| **That the real IdP's certificate, issuer, audience, claims and key set work with this configuration** | This procedure | **To do, by a person with IdP access** |

## 1. Gather the values

| Setting | Keycloak | Entra ID (v2 endpoints) |
|---|---|---|
| `OIDC_ISSUER` | `https://<host>/realms/<realm>` | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| `OIDC_JWKS_URL` | `<issuer>/protocol/openid-connect/certs` | `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys` |
| `OIDC_AUDIENCE` | the client id | the application (client) id |
| `OIDC_USERNAME_CLAIM` | `preferred_username` (default) | `preferred_username` (v2 tokens). v1 tokens use `upn` |

The IdP publishes the right issuer and key URL at `<issuer>/.well-known/openid-configuration`; the script compares yours with it. The issuer must match the token's `iss` **exactly**, including any trailing slash.

## 2. Get an ID token

Use the device-code flow, so the token never goes through a browser address bar or a third-party site. **Don't paste an ID token into an online debugger, an issue or a chat: it is a credential.** Register a **test** client (public, device flow enabled, scope `openid`), then:

```bash
umask 077                                         # the token file is private to you
CLIENT_ID=<client id>
# Keycloak: DEVICE=<issuer>/protocol/openid-connect/auth/device   TOKEN=<issuer>/protocol/openid-connect/token
# Entra:    DEVICE=https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/devicecode
#           TOKEN=https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token
curl -s "$DEVICE" -d "client_id=$CLIENT_ID" -d "scope=openid" | tee /tmp/device.json | jq '{user_code, verification_uri}'
# Sign in at the verification_uri as the user, enter the user_code, then:
curl -s "$TOKEN" -d "client_id=$CLIENT_ID" -d "grant_type=urn:ietf:params:oauth:grant-type:device_code" \
     -d "device_code=$(jq -r .device_code /tmp/device.json)" | jq -r .id_token > idtoken.txt
rm /tmp/device.json
```

The user must **already exist** in the platform and be a **member of the tenant** (nobody is created from token claims), and their local username must equal the token's username claim, for example `alice@example.org` for Entra's `preferred_username`.

## 3. Run the check

On a machine that can reach the IdP, with the API's `OIDC_*` values and the token file:

```bash
export OIDC_ISSUER=... OIDC_AUDIENCE=... OIDC_JWKS_URL=...
python scripts/check_oidc.py --token-file idtoken.txt                      # the IdP, its keys, the token
python scripts/check_oidc.py --token-file idtoken.txt --api http://localhost:8000 --tenant <slug>   # and the real sign-in
rm idtoken.txt
```

A private CA: set `SSL_CERT_FILE=/path/to/ca-bundle.pem` for the script **and** in the API's own environment, or the key fetch fails closed. Passing means every stage printed `OK`. The last line says whether the sign-in itself was checked. The script never prints the token or the session token.

Run the same sign-in once through the real front end too, because the front end builds the authorization request.

## 4. What to record on #113

Paste the script's output (it holds no secrets), plus: which IdP and version, the date, and who ran it. For example:

```
OK    config     issuer https://…, audience …, keys https://…, username claim 'preferred_username'
OK    discovery  issuer and key URL match what the IdP publishes
OK    keys       2 signing key(s): …
OK    token      alg RS256, kid …, expires in … s, preferred_username = '…'. Signature, issuer, audience and expiry verified
OK    sign-in    200: signed in as '…' to tenant '…' with role '…'; …
```

Then close #113.

## When a stage fails

| Stage | Message | Usual cause |
|---|---|---|
| keys | `CERTIFICATE_VERIFY_FAILED` | The host doesn't trust the IdP's CA. Set `SSL_CERT_FILE` (above) |
| keys | connection refused or timed out | A firewall or proxy between the API host and the IdP. The API waits 5 s for the key set, then refuses the sign-in |
| discovery | issuer differs | Trailing slash, or the wrong tenant id or realm in `OIDC_ISSUER` |
| token | `InvalidAudienceError` | `OIDC_AUDIENCE` isn't the client id the token was issued for |
| token | `InvalidIssuerError` | The token's `iss` isn't exactly `OIDC_ISSUER` |
| token | no username claim | Set `OIDC_USERNAME_CLAIM` to the claim that holds the username |
| token | key id not in the key set | The IdP rotated its keys. A new key can be refused for up to 30 s after rotation (PyJWT re-fetches at most every 30 s, so random key ids can't be used to hammer the IdP). Retry |
| token | `ImmatureSignatureError` | Clock skew between this host and the IdP |
| sign-in | 401 | The token verifies but that user isn't a member of that tenant, or the user doesn't exist locally |
| sign-in | 404 | The **API's** environment has no `OIDC_ISSUER`: the check passed here, but the API wasn't configured |
