# Panel

Panel de control para un servidor casero: muestra CPU, memoria, red, discos y procesos, y comprueba si responden los servicios que tengas montados. En español, sin JavaScript de terceros.

## Qué hace
- **Métricas del servidor** leídas de `/proc` (solo lectura): CPU, memoria, red, procesos y discos.
- **Vigilancia de servicios:** comprueba por HTTP los servicios definidos en `data/services.json` y enlaza a cada uno.
- **Acceso con usuario y contraseña**, con un primer usuario que se crea con un código de configuración.

## Pila
Python 3.12 · FastAPI · Jinja2 · SQLite · Docker.

## Puesta en marcha
```bash
cp .env.example .env        # y rellena SECRET_KEY y SETUP_CODE
docker compose up -d --build
```
El panel queda en el puerto `8085`. La primera vez, entra en `/configurar` con el código `SETUP_CODE` para crear tu usuario. Para uso real, ponlo detrás de un proxy con HTTPS (con `COOKIE_SECURE=1` el login solo funciona por HTTPS).

## Servicios vigilados
Edita `data/services.json`; cada entrada tiene `name`, `type`, `target` (URL que se comprueba, desde el contenedor se llega al servidor con `host.docker.internal`) y `link` (enlace público).

## Seguridad
Contraseñas con Argon2, CSRF en los formularios y `/proc` y `/etc/passwd` montados en solo lectura. Los datos viven en `./data/app.db`; haz copia de esa carpeta.
