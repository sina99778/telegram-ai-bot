#!/usr/bin/env bash

set -e
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
BUNDLE_DIR="$ROOT_DIR/offline-bundle"
IMAGES_DIR="$BUNDLE_DIR/images"
ARCHIVE_PATH="$ROOT_DIR/zanjir-offline.tar.gz"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
  printf '%b[INFO]%b %s\n' "$YELLOW" "$NC" "$1"
}

success() {
  printf '%b[SUCCESS]%b %s\n' "$GREEN" "$NC" "$1"
}

error() {
  printf '%b[ERROR]%b %s\n' "$RED" "$NC" "$1" >&2
}

step() {
  printf '%b[STEP]%b %s\n' "$BLUE" "$NC" "$1"
}

cleanup() {
  if [[ -d "$BUNDLE_DIR" ]]; then
    rm -rf "$BUNDLE_DIR"
    info "Cleaned up temporary bundle directory."
  fi
}

trap 'error "Bundling failed at line $LINENO."; exit 1' ERR
trap cleanup EXIT

require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    error "Required command not found: $command_name"
    exit 1
  fi
}

sanitize_image_name() {
  local image_name="$1"
  image_name="${image_name//\//_}"
  image_name="${image_name//:/_}"
  image_name="${image_name//@/_}"
  printf '%s' "$image_name"
}

copy_if_exists() {
  local source_path="$1"
  local destination_dir="$2"

  if [[ -e "$source_path" ]]; then
    cp -R "$source_path" "$destination_dir/"
    info "Copied $(basename "$source_path") into the offline bundle."
  else
    info "Skipping missing optional path: $(basename "$source_path")"
  fi
}

detect_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
  else
    error "Docker Compose is required but was not found."
    exit 1
  fi
}

parse_compose_services() {
  local current_service=""
  local in_services=0

  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    local line="$raw_line"

    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    if [[ "$line" =~ ^services:[[:space:]]*$ ]]; then
      in_services=1
      continue
    fi

    if (( in_services == 0 )); then
      continue
    fi

    if [[ "$line" =~ ^[^[:space:]] ]]; then
      break
    fi

    if [[ "$line" =~ ^[[:space:]]{2}([A-Za-z0-9_.-]+):[[:space:]]*$ ]]; then
      current_service="${BASH_REMATCH[1]}"
      ALL_SERVICES+=("$current_service")
      continue
    fi

    if [[ -z "$current_service" ]]; then
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]{4}image:[[:space:]]*(.+)[[:space:]]*$ ]]; then
      local image_ref="${BASH_REMATCH[1]}"
      image_ref="${image_ref%\"}"
      image_ref="${image_ref#\"}"
      SERVICE_IMAGES["$current_service"]="$image_ref"
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]{4}build:([[:space:]].*)?$ ]]; then
      BUILD_SERVICES+=("$current_service")
    fi
  done < "$COMPOSE_FILE"
}

copy_configuration_directories() {
  local config_names=(
    config
    configs
    configuration
    conf
    deploy
    deployment
    docker
    nginx
    traefik
    caddy
    synapse
    matrix
    alembic
  )
  local copied_any=0
  local dir_name=""

  for dir_name in "${config_names[@]}"; do
    if [[ -d "$ROOT_DIR/$dir_name" ]]; then
      cp -R "$ROOT_DIR/$dir_name" "$BUNDLE_DIR/"
      info "Copied configuration directory: $dir_name"
      copied_any=1
    fi
  done

  if (( copied_any == 0 )); then
    info "No known configuration directories were found to copy."
  fi
}

save_pulled_images() {
  local image_ref=""
  local tar_name=""

  if (( ${#PULL_IMAGES[@]} == 0 )); then
    info "No registry images were found in docker-compose.yml."
    return
  fi

  for image_ref in "${PULL_IMAGES[@]}"; do
    step "Pulling image: $image_ref"
    docker pull "$image_ref"

    tar_name="$(sanitize_image_name "$image_ref").tar"
    step "Saving image: $image_ref"
    docker save -o "$IMAGES_DIR/$tar_name" "$image_ref"
    success "Saved $image_ref to images/$tar_name"
  done
}

save_built_images() {
  local service_name=""
  local image_id=""

  if (( ${#BUILD_ONLY_SERVICES[@]} == 0 )); then
    info "No build-only services were found in docker-compose.yml."
    return
  fi

  for service_name in "${BUILD_ONLY_SERVICES[@]}"; do
    step "Building local image for service: $service_name"
    "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" build "$service_name"

    image_id="$("${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" images -q "$service_name" | head -n 1)"
    if [[ -z "$image_id" ]]; then
      error "Could not resolve the built image ID for service: $service_name"
      exit 1
    fi

    step "Saving built image for service: $service_name"
    docker save -o "$IMAGES_DIR/${service_name}.tar" "$image_id"
    success "Saved built image for $service_name to images/${service_name}.tar"
  done
}

main() {
  declare -gA SERVICE_IMAGES=()
  declare -gA UNIQUE_PULL_IMAGES=()
  declare -ga ALL_SERVICES=()
  declare -ga BUILD_SERVICES=()
  declare -ga PULL_IMAGES=()
  declare -ga BUILD_ONLY_SERVICES=()

  require_command docker
  require_command tar

  if [[ ! -f "$COMPOSE_FILE" ]]; then
    error "docker-compose.yml was not found in $ROOT_DIR"
    exit 1
  fi

  detect_compose_cmd

  step "Preparing offline bundle workspace"
  rm -rf "$BUNDLE_DIR"
  mkdir -p "$IMAGES_DIR"
  success "Created temporary bundle directories."

  step "Parsing docker-compose.yml for required images"
  parse_compose_services

  local service_name=""
  for service_name in "${ALL_SERVICES[@]}"; do
    if [[ -n "${SERVICE_IMAGES[$service_name]:-}" ]]; then
      UNIQUE_PULL_IMAGES["${SERVICE_IMAGES[$service_name]}"]=1
      continue
    fi

    if [[ " ${BUILD_SERVICES[*]} " == *" $service_name "* ]]; then
      BUILD_ONLY_SERVICES+=("$service_name")
    fi
  done

  local image_ref=""
  for image_ref in "${!UNIQUE_PULL_IMAGES[@]}"; do
    PULL_IMAGES+=("$image_ref")
  done

  if (( ${#PULL_IMAGES[@]} > 0 )); then
    mapfile -t PULL_IMAGES < <(printf '%s\n' "${PULL_IMAGES[@]}" | sort)
  fi

  if (( ${#BUILD_ONLY_SERVICES[@]} > 0 )); then
    mapfile -t BUILD_ONLY_SERVICES < <(printf '%s\n' "${BUILD_ONLY_SERVICES[@]}" | sort -u)
  fi

  info "Registry images detected: ${#PULL_IMAGES[@]}"
  info "Build-only services detected: ${#BUILD_ONLY_SERVICES[@]}"

  save_pulled_images
  save_built_images

  step "Copying essential project files"
  copy_if_exists "$COMPOSE_FILE" "$BUNDLE_DIR"
  copy_if_exists "$ROOT_DIR/.env.example" "$BUNDLE_DIR"
  copy_if_exists "$ROOT_DIR/install.sh" "$BUNDLE_DIR"
  copy_configuration_directories
  success "Project files copied into the offline bundle."

  step "Creating compressed archive"
  rm -f "$ARCHIVE_PATH"
  tar -czf "$ARCHIVE_PATH" -C "$ROOT_DIR" "$(basename "$BUNDLE_DIR")"
  success "Offline bundle created at $ARCHIVE_PATH"
}

main "$@"
