# Panel

Panel de control para un servidor casero, en español y sin JavaScript de terceros. Muestra el estado del servidor, gestiona los contenedores Docker y vigila tus aplicaciones desde una sola página.

## Qué hace
- **Métricas del servidor** leídas de `/proc` (solo lectura): CPU, memoria, red, procesos y discos.
- **Aplicaciones:** vigila por HTTP los servicios que añadas y enlaza a cada uno; arranca, para o reinicia grupos de contenedores.
- **Docker:** lista contenedores, registros, consumo y recursos; iniciar, parar, reiniciar y limpiar.
- **Red:** dispositivos vistos en la LAN (ARP), puertos a la escucha y equipos de Tailscale.
- **Archivos:** explorador de solo lectura de una carpeta del servidor; no muestra claves ni `.env`.
- **Consola restringida:** una lista cerrada de comandos (`docker ps`, `docker logs`…), sin intérprete de órdenes detrás.
- **Automatizaciones:** tareas con disparador horario o por caída de una aplicación (reiniciar un contenedor, llamar a una URL, limpiar).
- **Plugins:** secciones extra desde un `.zip`, ejecutadas en un marco aislado que no puede leer la sesión ni llamar a la API.
- **Usuarios y seguridad:** varios usuarios, cambio de contraseña, verificación en dos pasos (2FA) y registro de auditoría.

## Pila
Python 3.12 · FastAPI · Jinja2 · SQLite · Docker.

## Puesta en marcha
```bash
cp .env.example .env        # y rellena SECRET_KEY y SETUP_CODE
docker compose up -d --build
```
El panel queda en el puerto `8085`. La primera vez, entra en `/configurar` con el código `SETUP_CODE` para crear tu usuario. Para uso real, ponlo detrás de un proxy con HTTPS (con `COOKIE_SECURE=1` el login solo funciona por HTTPS).

Ajusta en `docker-compose.yml` el grupo (`group_add`, el GID del grupo `docker` de tu servidor: `getent group docker`) y la carpeta que quieres exponer en la sección Archivos.

## Aviso de seguridad
El contenedor monta `/var/run/docker.sock`, lo que equivale a tener acceso de administrador al servidor. Úsalo solo detrás de HTTPS, con contraseñas largas y 2FA, y no lo expongas a Internet sin protección adicional.

## Datos
Todo vive en `./data` (base de datos `app.db` y plugins). Haz copia de esa carpeta.
