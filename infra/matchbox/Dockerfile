# Matchbox with our IPS IG configuration baked in, so platforms without bind mounts
# (Virtuozzo) can run it. Keep the version in sync with infra/docker-compose.yml.
FROM europe-west6-docker.pkg.dev/ahdis-ch/ahdis/matchbox:v4.1.21
COPY application.yaml /config/application.yaml
