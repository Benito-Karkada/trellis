#!/bin/sh
# Run after `az login` and `az account set --subscription ...`.
set -eu
cd "$(dirname "$0")/.."
registry_name="${1:-cs1301pocacr26}"
image_tag="${2:-poc-v1}"
command -v az >/dev/null 2>&1 || { echo "Install Azure CLI first: brew install azure-cli" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Start Docker Desktop first." >&2; exit 1; }
registry_host=$(az acr show --name "$registry_name" --query loginServer --output tsv)
[ -n "$registry_host" ] || { echo "Registry login server was not returned." >&2; exit 1; }
# Build locally first; the allowlisted context excludes secrets and course data.
docker buildx build --platform linux/amd64 --load -f deploy/azure/Dockerfile -t "$registry_host/cs1301-web:$image_tag" .
az acr login --name "$registry_name"
docker push "$registry_host/cs1301-web:$image_tag"
az acr repository show --name "$registry_name" --image "cs1301-web:$image_tag" --query '{image:name,digest:digest}' --output json
printf '\nUploaded. Portal Image: cs1301-web; Image tag: %s\n' "$image_tag"
