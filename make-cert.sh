#!/bin/sh
# Makes the HTTPS certificate the iPhone needs: iOS Safari only opens the camera on a secure page.
#
# Safety: a fresh CA signs this one server certificate and then its private key is DELETED, so the
# CA the phone trusts can never sign anything else (no key left to steal or misuse). The trade-off:
# each run makes a new CA, so the phone needs the new profile. The phone connects by the Mac's
# .local name, so a changed Wi-Fi IP doesn't need a re-run; the certificate lasts 397 days.
set -eu
cd "$(dirname "$0")"
mkdir -p certs
chmod 700 certs
cd certs

HOST="$(scutil --get LocalHostName).local"
IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo 127.0.0.1)"
STAMP="$(date +%Y-%m-%d)"

cat > ca.cnf <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca
[dn]
CN = Teleprompter Local CA ($HOST $STAMP)
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF

cat > server.cnf <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = $HOST
[ext]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = DNS:$HOST, DNS:localhost, IP:$IP, IP:127.0.0.1
EOF

umask 077
openssl req -x509 -new -newkey rsa:2048 -nodes -sha256 -days 825 -keyout ca.key -out ca.crt -config ca.cnf
openssl req -new -newkey rsa:2048 -nodes -sha256 -keyout server.key -out server.csr -config server.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -set_serial "0x$(openssl rand -hex 8)" -sha256 -days 397 \
  -extfile server.cnf -extensions ext -out server.crt
rm -f ca.key server.csr ca.srl
chmod 644 ca.crt server.crt
openssl verify -CAfile ca.crt server.crt
echo "Certificate for $HOST and $IP. CA key deleted; install the new profile on the phone."
