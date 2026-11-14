# Nginx image for the rehearsal: static files baked in from src/static,
# avatars come from the shared named volume mounted by docker-compose.yml.
FROM nginx:1.27-alpine

COPY src/static /app/src/static
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
