#!/bin/sh
set -e

#echo "Generating config.json..."
#cat <<EOF > /usr/share/nginx/html/config.json
#{
#  "VITE_BACKEND_BASE_URL": "${BACKEND_BASE_URL}"
#}
#EOF

# Se APP_ENV_LABEL è valorizzata (es. DEV) la antepone al titolo e la espone al banner dell'app
if [ -n "${APP_ENV_LABEL}" ]; then
  # escape HTML, poi escape per sed (\\ & |)
  LABEL=$(printf '%s' "${APP_ENV_LABEL}" \
    | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' \
    | sed -e 's/[\\&|]/\\&/g')
  sed -i \
    -e "s|<title>|<title>[${LABEL}] |" \
    -e "s|<meta name=\"env-label\" content=\"\" />|<meta name=\"env-label\" content=\"${LABEL}\" />|" \
    /usr/share/nginx/html/index.html
fi

# Ribbon con l'etichetta d'ambiente sulle icone dell'app (favicon, apple-touch, PWA)
if [ -n "${APP_ENV_LABEL}" ]; then
  /apply-env-icons.sh || echo "Impossibile applicare il ribbon alle icone"
fi

echo "Configuring nginx proxy..."
/tls.sh
export FRONTEND_HTTPS_PORT="${FRONTEND_HTTPS_PORT:-443}"
case "$FRONTEND_HTTPS_PORT" in
  ''|*[!0-9]*) echo "Invalid FRONTEND_HTTPS_PORT: expected a port from 1 to 65535" >&2; exit 1 ;;
esac
if [ "$FRONTEND_HTTPS_PORT" -lt 1 ] || [ "$FRONTEND_HTTPS_PORT" -gt 65535 ]; then
  echo "Invalid FRONTEND_HTTPS_PORT: expected a port from 1 to 65535" >&2
  exit 1
fi
envsubst '${BACKEND_BASE_URL} ${FRONTEND_HTTPS_PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

if [ -z "${TLS_CERT_FILE:-}" ] && [ -z "${TLS_KEY_FILE:-}" ]; then
  (
    while sleep 43200; do
      if /tls.sh; then
        nginx -t && nginx -s reload || echo "TLS: nginx reload failed; retrying in 12 hours" >&2
      else
        echo "TLS: renewal failed; retrying in 12 hours" >&2
      fi
    done
  ) &
fi

exec nginx -g "daemon off;"