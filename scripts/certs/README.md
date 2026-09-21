# NOAA TLS intermediate

`digicert-global-g2-tls-rsa-sha256-2020-ca1.pem` is the public intermediate
certificate downloaded from the issuer URL in NOAA's server certificate,
using HTTPS:

https://cacerts.digicert.com/DigiCertGlobalG2TLSRSASHA2562020CA1-1.crt

On September 21, 2026, satellitemaps.nesdis.noaa.gov served its leaf certificate
twice and omitted this intermediate. The collector supplies it only for that
hostname. Hostname, expiry, signature, and system root trust checks remain
required; partial-chain trust is disabled. No private keys are included.

To verify the bundled intermediate against the system roots:

```sh
openssl verify scripts/certs/digicert-global-g2-tls-rsa-sha256-2020-ca1.pem
```
