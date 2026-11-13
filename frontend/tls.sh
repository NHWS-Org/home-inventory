#!/bin/bash
set -euo pipefail

TLS_STORE=${TLS_STORE:-/var/lib/frontend-tls}
TLS_RUNTIME=${TLS_RUNTIME:-/run/frontend-tls}
TLS_HOSTS=${TLS_HOSTS:-}
TLS_CERT_FILE=${TLS_CERT_FILE:-}
TLS_KEY_FILE=${TLS_KEY_FILE:-}

fail() { echo "TLS: $*" >&2; exit 1; }

validate_pair() {
  local cert=$1 key=$2 cert_public key_public
  [[ -r $cert && -r $key ]] || fail "certificate or private key is not readable"
  openssl x509 -in "$cert" -noout >/dev/null || fail "certificate is invalid"
  cert_public=$(openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)
  key_public=$(openssl pkey -in "$key" -pubout -outform DER | openssl dgst -sha256)
  [[ $cert_public == "$key_public" ]] || fail "certificate and private key do not match"
}

prepare_names() {
  local item
  local -a hosts
  SAN="DNS:localhost,IP:127.0.0.1,IP:::1"
  [[ $TLS_HOSTS =~ ^[a-zA-Z0-9.,:-]*$ && $TLS_HOSTS != ,* && $TLS_HOSTS != *, && $TLS_HOSTS != *,,* ]] ||
    fail "invalid TLS_HOSTS"
  [[ -n $TLS_HOSTS ]] || return 0
  IFS=',' read -r -a hosts <<< "$TLS_HOSTS"
  for item in "${hosts[@]}"; do
    [[ -n $item ]] || fail "TLS_HOSTS contains an empty name"
    [[ $item =~ ^[a-zA-Z0-9.:-]+$ ]] || fail "invalid TLS_HOSTS entry: $item"
    if [[ $item == *:* || $item =~ ^[0-9.]+$ ]]; then
      SAN+=",IP:$item"
    else
      SAN+=",DNS:$item"
    fi
  done
}

prepare_ca() {
  local ca="$TLS_STORE/ca"
  if [[ ! -e $ca ]]; then
    local directory
    directory=$(mktemp -d "$TLS_STORE/ca.XXXXXXXX")
    if ! openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 3650 \
        -keyout "$directory/key.pem" -out "$directory/cert.pem" \
        -subj "/CN=Home Inventory Local CA" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1; then
      rm -f "$directory/key.pem" "$directory/cert.pem"
      rmdir "$directory"
      fail "could not generate local CA"
    fi
    mv "$directory" "$ca"
    echo "TLS: generated local CA; install its certificate on trusted devices"
  fi
  validate_pair "$ca/cert.pem" "$ca/key.pem"
  openssl x509 -in "$ca/cert.pem" -noout -checkend 2592000 >/dev/null ||
    fail "local CA expires in less than 30 days; replace it and re-establish device trust"
}

generate_if_needed() {
  local current="$TLS_STORE/current" directory
  prepare_names
  prepare_ca
  if [[ -e $current ]]; then
    [[ -f $current/names && -f $current/cert.pem && -f $current/key.pem ]] || fail "stored TLS certificate is incomplete"
    validate_pair "$current/cert.pem" "$current/key.pem"
    openssl verify -no_check_time -CAfile "$TLS_STORE/ca/cert.pem" "$current/cert.pem" >/dev/null ||
      fail "stored TLS certificate is not signed by the local CA"
    if [[ $(< "$current/names") == "$SAN" ]] && openssl x509 -in "$current/cert.pem" -noout -checkend 2592000 >/dev/null; then
      return 0
    fi
  fi
  directory=$(mktemp -d "$TLS_STORE/cert.XXXXXXXX")
  printf 'subjectAltName=%s\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\n' "$SAN" > "$directory/extensions"
  if ! openssl req -new -newkey rsa:2048 -noenc -sha256 \
      -keyout "$directory/key.pem" -out "$directory/request.pem" \
      -subj "/CN=Home Inventory" >/dev/null 2>&1 ||
     ! openssl x509 -req -in "$directory/request.pem" -CA "$TLS_STORE/ca/cert.pem" \
      -CAkey "$TLS_STORE/ca/key.pem" -set_serial "0x$(openssl rand -hex 16)" \
      -days 365 -sha256 -extfile "$directory/extensions" \
      -out "$directory/cert.pem" >/dev/null 2>&1; then
    rm -f "$directory/key.pem" "$directory/cert.pem" "$directory/request.pem" "$directory/extensions"
    rmdir "$directory"
    fail "could not generate certificate (check TLS_HOSTS)"
  fi
  rm "$directory/request.pem" "$directory/extensions"
  printf '%s\n' "$SAN" > "$directory/names"
  validate_pair "$directory/cert.pem" "$directory/key.pem"
  ln -s "$directory" "$directory/current-link"
  if [[ $(uname -s) == Darwin ]]; then
    mv -fh "$directory/current-link" "$current"
  else
    mv -Tf "$directory/current-link" "$current"
  fi
  echo "TLS: generated local certificate for $SAN"
}

umask 077
mkdir -p "$TLS_STORE" "$TLS_RUNTIME"
if [[ -n $TLS_CERT_FILE || -n $TLS_KEY_FILE ]]; then
  [[ -n $TLS_CERT_FILE && -n $TLS_KEY_FILE ]] || fail "set both TLS_CERT_FILE and TLS_KEY_FILE"
  [[ $TLS_CERT_FILE == /* && $TLS_KEY_FILE == /* ]] || fail "certificate and private key paths must be absolute"
  validate_pair "$TLS_CERT_FILE" "$TLS_KEY_FILE"
  openssl x509 -in "$TLS_CERT_FILE" -noout -checkend 0 >/dev/null || fail "provided certificate is expired"
  ln -sfn "$TLS_CERT_FILE" "$TLS_RUNTIME/cert.pem"
  ln -sfn "$TLS_KEY_FILE" "$TLS_RUNTIME/key.pem"
else
  generate_if_needed
  ln -sfn "$TLS_STORE/current/cert.pem" "$TLS_RUNTIME/cert.pem"
  ln -sfn "$TLS_STORE/current/key.pem" "$TLS_RUNTIME/key.pem"
fi
