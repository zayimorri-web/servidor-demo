#!/usr/bin/env bash
# Servidor demo BATEY — arranque de Paper + plugins (Geyser, Floodgate, BlueMap)
# Usa el JRE local (~/workspace/servidor-demo/jre) para sobrevivir reemplazos de la VM.
# Si el entorno define un proxy de salida (https_proxy), lo traduce a flags de la JVM
# para que el servidor pueda validar sesiones contra Mojang. Sin credenciales en el repo.
cd "$(dirname "$0")"
JAVA="$(cd .. && pwd)/jre25/bin/java"

# Todo el trafico HTTPS del servidor pasa por el puente local (proxy_shim.py,
# puerto 18080): el proxy de salida de esta maquina rompe el tunel nativo de
# Java; el puente le habla en el formato que Java espera. Ver proxy_shim.py.
# Algunas librerias leen el proxy de las propiedades -D y otras de las
# variables de entorno: se apuntan AMBAS al puente. (El puente es otro
# proceso y conserva en su propio entorno la direccion del proxy real.)
export http_proxy="http://127.0.0.1:18080"
export https_proxy="http://127.0.0.1:18080"
export HTTP_PROXY="http://127.0.0.1:18080"
export HTTPS_PROXY="http://127.0.0.1:18080"
export all_proxy="http://127.0.0.1:18080"
export ALL_PROXY="http://127.0.0.1:18080"
PROXY_FLAGS=(
  -Dhttp.proxyHost="127.0.0.1" -Dhttp.proxyPort="18080"
  -Dhttps.proxyHost="127.0.0.1" -Dhttps.proxyPort="18080"
  -Dhttp.nonProxyHosts="localhost|127.0.0.1"
)

exec "$JAVA" "${PROXY_FLAGS[@]}" -Xms512M -Xmx1536M -XX:+UseG1GC -jar paper.jar nogui
