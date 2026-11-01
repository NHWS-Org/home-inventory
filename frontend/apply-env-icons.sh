#!/bin/sh
# Sovrappone alle icone dell'app un ribbon d'angolo con l'etichetta APP_ENV_LABEL.
# Parte sempre dagli originali in ICONS_SRC, quindi è idempotente tra i riavvii.
set -e

ICONS_SRC="${ICONS_SRC:-/opt/icons-orig}"
ICONS_DST="${ICONS_DST:-/usr/share/nginx/html}"

[ -n "${APP_ENV_LABEL}" ] || exit 0

# Maiuscolo, massimo 10 caratteri, escape XML
LABEL=$(printf '%.10s' "${APP_ENV_LABEL}" | tr '[:lower:]' '[:upper:]' \
  | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g')
LEN=$(printf '%s' "${LABEL}" | wc -m | tr -d ' ')
FONT_SIZE=$((300 / (LEN > 4 ? LEN : 4)))
[ "${FONT_SIZE}" -le 56 ] || FONT_SIZE=56

# $1 = id clip, $2 = elemento di clip (rettangolo arrotondato o pieno)
ribbon_group() {
  cat <<EOF
<defs><clipPath id="$1">$2</clipPath></defs>
<g clip-path="url(#$1)">
  <g transform="translate(404 108) rotate(45)">
    <rect x="-220" y="-38" width="440" height="76" fill="#f59e0b"/>
    <rect x="-220" y="-38" width="440" height="76" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="3"/>
    <text x="0" y="0" text-anchor="middle" dominant-baseline="central" font-family="DejaVu Sans, sans-serif" font-weight="700" font-size="${FONT_SIZE}" fill="#000">${LABEL}</text>
  </g>
</g>
EOF
}

ROUNDED_CLIP='<rect width="512" height="512" rx="112"/>'
SQUARE_CLIP='<rect width="512" height="512"/>'

# SVG: stesso disegno originale con il ribbon in coda
{
  sed '$d' "${ICONS_SRC}/icon.svg"
  ribbon_group env-clip "${ROUNDED_CLIP}"
  echo '</svg>'
} > "${ICONS_DST}/icon.svg"

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

for kind in rounded square; do
  if [ "${kind}" = rounded ]; then CLIP="${ROUNDED_CLIP}"; else CLIP="${SQUARE_CLIP}"; fi
  {
    echo '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    ribbon_group env-clip "${CLIP}"
    echo '</svg>'
  } > "${TMP}/ribbon-${kind}.svg"
done

# PNG con angoli arrotondati / PNG a pieno campo (apple-touch e maskable)
overlay() {
  file="$1"; kind="$2"
  size=$(identify -format '%w' "${ICONS_SRC}/${file}")
  rsvg-convert -w "${size}" -h "${size}" "${TMP}/ribbon-${kind}.svg" -o "${TMP}/ribbon.png"
  convert "${ICONS_SRC}/${file}" "${TMP}/ribbon.png" -composite "${ICONS_DST}/${file}"
}

overlay favicon-32.png rounded
overlay icon-192.png rounded
overlay icon-512.png rounded
overlay apple-touch-icon.png square
overlay icon-maskable-512.png square
