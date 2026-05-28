#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  install.sh — Telegram AI Bot installer, updater, and doctor
#
#  Usage:
#    ./install.sh install        First-time install (clone-and-go safe)
#    ./install.sh update         git pull + rebuild + migrate (zero data loss)
#    ./install.sh doctor         Diagnose the deployment (read-only)
#    ./install.sh doctor --fix   Diagnose + auto-remediate common issues
#    ./install.sh start          Bring the stack up
#    ./install.sh stop           Bring the stack down (keeps volumes)
#    ./install.sh restart        Restart all services
#    ./install.sh status         Compact health summary
#    ./install.sh logs [SVC]     Tail logs (default: web)
#    ./install.sh migrate        Run alembic upgrade head
#    ./install.sh backup         Trigger an immediate DB backup
#    ./install.sh shell [SVC]    Open a shell inside a container (default: web)
#    ./install.sh env-setup      (Re)create .env interactively
#    ./install.sh help           Show this help
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors / output helpers ──────────────────────────────────────────────────
if [ -t 1 ]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; NC=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; DIM=""; NC=""
fi

info()    { printf "%sℹ%s %s\n" "$BLUE"    "$NC" "$*"; }
ok()      { printf "%s✓%s %s\n" "$GREEN"   "$NC" "$*"; }
warn()    { printf "%s⚠%s %s\n" "$YELLOW"  "$NC" "$*"; }
err()     { printf "%s✗%s %s\n" "$RED"     "$NC" "$*" >&2; }
section() { printf "\n%s━━━ %s ━━━%s\n" "$BOLD" "$*" "$NC"; }
dim()     { printf "%s%s%s\n" "$DIM" "$*" "$NC"; }

# ── Project root ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"

ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

# Settings that MUST be set (not empty, not placeholder) before the app starts.
REQUIRED_KEYS=(
    BOT_TOKEN
    WEBHOOK_URL
    WEBHOOK_SECRET
    GEMINI_API_KEY
    POSTGRES_USER
    POSTGRES_PASSWORD
    POSTGRES_DB
    POSTGRES_HOST
)

# Placeholder values we should reject as "not set".
PLACEHOLDER_VALUES=(
    "your-gemini-api-key-here"
    "change-me-to-a-random-string"
    "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    "secure_password"
    "https://your-domain.example.com/webhook"
)

# ── docker compose plugin vs legacy docker-compose ───────────────────────────
detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
        return 0
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
        return 0
    fi
    return 1
}

if ! COMPOSE="$(detect_compose)"; then
    COMPOSE="docker compose"
fi

# Wrap so we can `dc up -d` etc. without splitting on each call.
dc() { $COMPOSE "$@"; }

# ── Common helpers ───────────────────────────────────────────────────────────
need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        err "Missing required command: $1"
        return 1
    fi
}

env_get() {
    # Read a single key from .env without sourcing it (avoids accidental code exec).
    local key="$1"
    [ -f "$ENV_FILE" ] || return 1
    awk -F= -v k="$key" '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        {
            split($0, kv, "=")
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", kv[1])
            if (kv[1] == k) {
                # everything after the first =
                sub(/^[^=]*=/, "", $0)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
                # strip optional surrounding quotes
                gsub(/^["'\''"]|["'\''"]$/, "", $0)
                print $0
                exit
            }
        }
    ' "$ENV_FILE"
}

env_set() {
    # Set or replace a single key in .env (creates file if missing).
    local key="$1" value="$2"
    touch "$ENV_FILE"
    if grep -qE "^[[:space:]]*${key}=" "$ENV_FILE"; then
        # GNU sed and BSD sed both accept -i with backup, then we drop the backup.
        sed -i.bak "s|^[[:space:]]*${key}=.*|${key}=${value}|" "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
    else
        printf "%s=%s\n" "$key" "$value" >> "$ENV_FILE"
    fi
}

is_placeholder() {
    local v="$1"
    [ -z "$v" ] && return 0
    for p in "${PLACEHOLDER_VALUES[@]}"; do
        [ "$v" = "$p" ] && return 0
    done
    return 1
}

gen_secret() {
    # 48 chars of URL-safe entropy from /dev/urandom.
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 24
    else
        head -c 32 /dev/urandom | base64 | tr -d '=+/' | head -c 48
    fi
}

require_prereqs() {
    section "Prerequisites"
    local missing=0
    for c in docker git curl; do
        if command -v "$c" >/dev/null 2>&1; then
            ok "$c is installed"
        else
            err "$c is NOT installed"
            missing=$((missing + 1))
        fi
    done

    if dc version >/dev/null 2>&1; then
        ok "Docker Compose is available ($COMPOSE)"
    else
        err "Docker Compose plugin is not available"
        missing=$((missing + 1))
    fi

    if docker info >/dev/null 2>&1; then
        ok "Docker daemon is reachable"
    else
        err "Docker daemon is NOT reachable (is it running? do you need sudo?)"
        missing=$((missing + 1))
    fi

    if [ "$missing" -gt 0 ]; then
        err "$missing prerequisite check(s) failed. Please install/fix them and re-run."
        return 1
    fi
}

# ── Subcommands ──────────────────────────────────────────────────────────────

cmd_env_setup() {
    section "Environment setup"

    if [ ! -f "$ENV_EXAMPLE" ]; then
        err ".env.example is missing; cannot bootstrap .env"
        return 1
    fi

    if [ -f "$ENV_FILE" ]; then
        warn ".env already exists at $ENV_FILE"
        printf "Overwrite it from .env.example? [y/N] "
        read -r reply
        case "$reply" in
            y|Y|yes|YES) ;;
            *) info "Keeping existing .env"; return 0 ;;
        esac
        cp -- "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)"
        info "Existing .env backed up"
    fi

    cp -- "$ENV_EXAMPLE" "$ENV_FILE"
    ok ".env created from .env.example"

    # Auto-generate WEBHOOK_SECRET if it's still the placeholder.
    local current_secret
    current_secret="$(env_get WEBHOOK_SECRET || true)"
    if is_placeholder "$current_secret"; then
        local generated; generated="$(gen_secret)"
        env_set WEBHOOK_SECRET "$generated"
        ok "Generated a random WEBHOOK_SECRET"
    fi

    warn "Now edit $ENV_FILE and set:"
    for k in BOT_TOKEN WEBHOOK_URL GEMINI_API_KEY POSTGRES_PASSWORD ADMIN_IDS; do
        printf "    - %s\n" "$k"
    done
    info "Then run: $0 install"
}

cmd_install() {
    section "Install"
    require_prereqs

    if [ ! -f "$ENV_FILE" ]; then
        warn ".env is missing; bootstrapping from .env.example"
        cmd_env_setup
        err "Edit .env and re-run: $0 install"
        return 1
    fi

    validate_env || { err "Fix the .env values above and re-run"; return 1; }

    info "Building images (this may take a few minutes on first run)…"
    dc build

    info "Starting the stack…"
    dc up -d

    wait_for_db
    info "Applying database migrations…"
    run_migrations || warn "Migrations failed; run '$0 doctor --fix' to inspect"

    wait_for_web

    info "Registering Telegram webhook…"
    set_telegram_webhook || warn "Webhook registration failed; '$0 doctor' will tell you why"

    ok "Install complete."
    cmd_status
}

cmd_update() {
    section "Update"
    require_prereqs

    if [ -d "$PROJECT_ROOT/.git" ]; then
        info "Pulling latest changes from git…"
        local before; before="$(git rev-parse HEAD)"
        git fetch --quiet origin
        local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
        git pull --ff-only origin "$branch" || {
            err "git pull is not a fast-forward. Resolve manually and re-run update."
            return 1
        }
        local after; after="$(git rev-parse HEAD)"
        if [ "$before" = "$after" ]; then
            info "Already at the latest commit ($after)"
        else
            ok "Pulled $(git log --oneline "$before..$after" | wc -l | tr -d ' ') new commit(s)"
        fi
    else
        warn "Not a git checkout — skipping git pull (rebuilding with current source)"
    fi

    info "Rebuilding images…"
    dc build --pull

    info "Recreating containers…"
    dc up -d

    wait_for_db
    info "Applying migrations…"
    run_migrations || warn "Migrations failed; run '$0 doctor --fix' to inspect"

    wait_for_web
    info "Re-registering webhook (URL may have changed)…"
    set_telegram_webhook || warn "Webhook registration failed; '$0 doctor' will tell you why"

    ok "Update complete."
    cmd_status
}

cmd_start()    { section "Start";    dc up -d;        cmd_status; }
cmd_stop()     { section "Stop";     dc down;         ok "Stopped (volumes preserved)"; }
cmd_restart()  { section "Restart";  dc restart;      cmd_status; }
cmd_migrate()  { section "Migrate";  run_migrations; }

cmd_logs() {
    local svc="${1:-web}"
    section "Logs ($svc, Ctrl+C to exit)"
    dc logs -f --tail=200 "$svc"
}

cmd_shell() {
    local svc="${1:-web}"
    section "Shell in $svc"
    dc exec "$svc" /bin/bash || dc exec "$svc" /bin/sh
}

cmd_backup() {
    section "Backup"
    info "Triggering an immediate DB backup via pg_dump…"
    local ts; ts="$(date -u +%Y-%m-%d_%H-%M-%S)"
    local outdir="$PROJECT_ROOT/backups"
    mkdir -p "$outdir"
    local outfile="$outdir/manual_${ts}.sql.gz"

    local pg_user pg_db
    pg_user="$(env_get POSTGRES_USER || echo postgres)"
    pg_db="$(env_get POSTGRES_DB     || echo postgres)"

    if dc exec -T db pg_dump -U "$pg_user" -d "$pg_db" \
            --clean --if-exists --no-owner --no-privileges \
            | gzip > "$outfile"; then
        ok "Backup written: $outfile ($(du -h "$outfile" | cut -f1))"
    else
        rm -f "$outfile"
        err "Backup failed"
        return 1
    fi
}

cmd_status() {
    section "Status"
    dc ps

    # Telegram webhook status
    local token; token="$(env_get BOT_TOKEN || true)"
    if [ -n "$token" ] && ! is_placeholder "$token"; then
        local info_json
        info_json="$(curl -s --max-time 5 "https://api.telegram.org/bot${token}/getWebhookInfo" || true)"
        if [ -n "$info_json" ]; then
            local url; url="$(echo "$info_json" | grep -oE '"url"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
            local pending; pending="$(echo "$info_json" | grep -oE '"pending_update_count"[[:space:]]*:[[:space:]]*[0-9]+' | grep -oE '[0-9]+$' || echo 0)"
            local last_err; last_err="$(echo "$info_json" | grep -oE '"last_error_message"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/' || true)"

            if [ -n "$url" ]; then
                ok "Telegram webhook is set: $url"
                [ "${pending:-0}" -gt 0 ] && warn "  pending updates: $pending"
                [ -n "$last_err" ]        && warn "  last_error_message: $last_err"
            else
                warn "Telegram webhook is NOT set"
            fi
        else
            warn "Could not reach Telegram API to check webhook status"
        fi
    fi
}

cmd_help() {
    cat <<EOF
${BOLD}Telegram AI Bot — installer & manager${NC}

${BOLD}Usage:${NC}
  $0 <command> [args]

${BOLD}Commands:${NC}
  install            First-time install (validates .env, builds, starts, migrates)
  update             git pull + rebuild + migrate (idempotent; preserves data)
  doctor [--fix]     Diagnose deployment; with --fix, auto-remediate safely
  start              Bring the stack up
  stop               Bring the stack down (volumes preserved)
  restart            Restart services
  status             Show container + webhook status
  logs [SVC]         Tail logs (default: web; try: worker, db, redis)
  migrate            Run alembic upgrade head
  backup             Take a manual gzipped pg_dump backup into ./backups/
  shell [SVC]        Open a shell inside a container (default: web)
  env-setup          Bootstrap or rebuild .env from .env.example
  help               Show this help

${BOLD}Quick start:${NC}
  $0 env-setup       # creates .env, generates WEBHOOK_SECRET
  \$EDITOR .env       # fill in BOT_TOKEN, WEBHOOK_URL, GEMINI_API_KEY, …
  $0 install
  $0 doctor

${BOLD}Daily maintenance:${NC}
  $0 doctor          # quick health read
  $0 update          # safe in-place upgrade
EOF
}

# ── Doctor ───────────────────────────────────────────────────────────────────

# Each doctor_check_* function:
#   - prints findings using ok/warn/err
#   - returns 0 if healthy, 1 if a problem was found
#   - if --fix mode, attempts a remediation when there is a safe one

DOCTOR_FIX=0
DOCTOR_ISSUES=0

doctor_problem() {
    DOCTOR_ISSUES=$((DOCTOR_ISSUES + 1))
    err "$*"
}

doctor_check_prereqs() {
    section "1. Prerequisites"
    require_prereqs
}

doctor_check_env() {
    section "2. Environment file"

    if [ ! -f "$ENV_FILE" ]; then
        doctor_problem ".env is missing"
        if [ "$DOCTOR_FIX" = 1 ]; then
            info "[fix] bootstrapping .env from .env.example"
            cmd_env_setup || true
        fi
        return 1
    fi
    ok ".env exists"

    local missing=()
    for k in "${REQUIRED_KEYS[@]}"; do
        local v; v="$(env_get "$k" || true)"
        if is_placeholder "$v"; then
            missing+=("$k")
        fi
    done

    if [ ${#missing[@]} -eq 0 ]; then
        ok "All required keys are populated"
    else
        doctor_problem "These required keys are empty or still placeholders: ${missing[*]}"
        if [ "$DOCTOR_FIX" = 1 ]; then
            for k in "${missing[@]}"; do
                if [ "$k" = "WEBHOOK_SECRET" ]; then
                    local s; s="$(gen_secret)"
                    env_set WEBHOOK_SECRET "$s"
                    ok "[fix] Generated a fresh WEBHOOK_SECRET"
                fi
            done
            local still_missing=()
            for k in "${missing[@]}"; do
                [ "$k" = "WEBHOOK_SECRET" ] && continue
                still_missing+=("$k")
            done
            if [ ${#still_missing[@]} -gt 0 ]; then
                warn "[fix] Cannot auto-fill these — please edit .env manually: ${still_missing[*]}"
            fi
        fi
    fi

    # Cheap sanity checks
    local webhook_url; webhook_url="$(env_get WEBHOOK_URL || true)"
    if [ -n "$webhook_url" ] && ! [[ "$webhook_url" =~ ^https:// ]]; then
        doctor_problem "WEBHOOK_URL must start with https:// (Telegram refuses http)"
    fi
}

doctor_check_compose_file() {
    section "3. docker-compose.yml"
    if [ ! -f "$PROJECT_ROOT/docker-compose.yml" ]; then
        doctor_problem "docker-compose.yml is missing"
        return 1
    fi
    ok "docker-compose.yml present"
}

doctor_check_containers() {
    section "4. Containers"
    if ! docker info >/dev/null 2>&1; then
        doctor_problem "Docker daemon unreachable; cannot inspect containers"
        return 1
    fi

    local services=(db redis web worker)
    local any_down=0
    for svc in "${services[@]}"; do
        local cid; cid="$(dc ps -q "$svc" 2>/dev/null || true)"
        if [ -z "$cid" ]; then
            doctor_problem "$svc container is not running"
            any_down=1
            continue
        fi
        local state; state="$(docker inspect -f '{{.State.Status}}' "$cid")"
        local health; health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
        if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }; then
            ok "$svc: $state ($health)"
        else
            doctor_problem "$svc: $state ($health)"
            any_down=1
        fi
    done

    if [ "$any_down" -ne 0 ] && [ "$DOCTOR_FIX" = 1 ]; then
        info "[fix] Re-running 'docker compose up -d' to recover unhealthy services"
        dc up -d
    fi
}

doctor_check_db() {
    section "5. Database connectivity"
    local cid; cid="$(dc ps -q db 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        doctor_problem "db container is not running"
        return 1
    fi
    local pg_user pg_db
    pg_user="$(env_get POSTGRES_USER || echo postgres)"
    pg_db="$(env_get POSTGRES_DB     || echo postgres)"
    if dc exec -T db pg_isready -U "$pg_user" -d "$pg_db" >/dev/null 2>&1; then
        ok "Postgres accepts connections"
    else
        doctor_problem "Postgres is not accepting connections"
    fi
}

doctor_check_redis() {
    section "6. Redis connectivity"
    local cid; cid="$(dc ps -q redis 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        doctor_problem "redis container is not running"
        return 1
    fi
    local pong; pong="$(dc exec -T redis redis-cli ping 2>/dev/null | tr -d '\r\n' || true)"
    if [ "$pong" = "PONG" ]; then
        ok "Redis responds to PING"
    else
        doctor_problem "Redis did not PONG (got: '$pong')"
    fi
}

doctor_check_migrations() {
    section "7. Database migrations"
    local cid; cid="$(dc ps -q web 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        warn "web container is not running; skipping migration check"
        return 0
    fi
    local current head
    current="$(dc exec -T web alembic current 2>/dev/null | tail -n 1 | awk '{print $1}' || true)"
    head="$(dc exec -T web alembic heads 2>/dev/null | tail -n 1 | awk '{print $1}' || true)"
    if [ -z "$current" ] || [ -z "$head" ]; then
        warn "Could not read alembic state (is the web container fully up?)"
        return 0
    fi
    if [ "$current" = "$head" ]; then
        ok "Migrations are up to date (rev: $current)"
    else
        doctor_problem "Database is behind: at $current, head is $head"
        if [ "$DOCTOR_FIX" = 1 ]; then
            info "[fix] Running alembic upgrade head"
            dc exec -T web alembic upgrade head || warn "[fix] Migration run failed"
        fi
    fi
}

doctor_check_health_endpoint() {
    section "8. /health endpoint"
    local cid; cid="$(dc ps -q web 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        doctor_problem "web container is not running; cannot probe /health"
        return 1
    fi
    if dc exec -T web curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        ok "/health returns 200"
    else
        doctor_problem "/health did not return 200"
    fi
}

doctor_check_telegram_webhook() {
    section "9. Telegram webhook"
    local token; token="$(env_get BOT_TOKEN || true)"
    if is_placeholder "$token"; then
        doctor_problem "BOT_TOKEN is missing or still a placeholder; skipping live check"
        return 1
    fi

    local resp
    resp="$(curl -s --max-time 5 "https://api.telegram.org/bot${token}/getWebhookInfo" || true)"
    if [ -z "$resp" ]; then
        doctor_problem "Could not reach api.telegram.org (network?)"
        return 1
    fi

    if echo "$resp" | grep -q '"ok":true'; then
        local url; url="$(echo "$resp" | grep -oE '"url"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
        local pending; pending="$(echo "$resp" | grep -oE '"pending_update_count"[[:space:]]*:[[:space:]]*[0-9]+' | grep -oE '[0-9]+$' || echo 0)"
        local err_msg; err_msg="$(echo "$resp" | grep -oE '"last_error_message"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/' || true)"
        local expected; expected="$(env_get WEBHOOK_URL || true)"

        if [ -z "$url" ]; then
            doctor_problem "No webhook is registered with Telegram"
            if [ "$DOCTOR_FIX" = 1 ]; then
                info "[fix] Re-registering webhook"
                set_telegram_webhook || warn "[fix] Re-registration failed"
            fi
        elif [ -n "$expected" ] && [ "$url" != "$expected" ]; then
            doctor_problem "Registered webhook ($url) differs from .env WEBHOOK_URL ($expected)"
            if [ "$DOCTOR_FIX" = 1 ]; then
                info "[fix] Re-registering webhook to match .env"
                set_telegram_webhook || warn "[fix] Re-registration failed"
            fi
        else
            ok "Webhook registered: $url"
        fi

        if [ "${pending:-0}" -gt 50 ]; then
            warn "  $pending pending updates queued at Telegram — webhook may be slow or returning errors"
        fi
        [ -n "$err_msg" ] && warn "  Telegram reports last_error_message: $err_msg"
    else
        doctor_problem "Telegram getWebhookInfo failed: $resp"
    fi
}

doctor_check_disk() {
    section "10. Disk space"
    local avail
    if command -v df >/dev/null 2>&1; then
        avail="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')"
        # warn under 1 GiB free
        if [ -n "$avail" ] && [ "$avail" -lt 1048576 ]; then
            doctor_problem "Less than 1 GiB free on the project filesystem ($((avail / 1024)) MiB)"
            if [ "$DOCTOR_FIX" = 1 ]; then
                info "[fix] Running 'docker system prune -f' to reclaim space"
                docker system prune -f >/dev/null || true
            fi
        else
            ok "Free space: ~$((avail / 1024)) MiB on $(df -P "$PROJECT_ROOT" | awk 'NR==2 {print $1}')"
        fi
    else
        warn "df not available; skipping disk check"
    fi
}

doctor_check_recent_errors() {
    section "11. Recent ERROR/CRITICAL log lines (last 200 per service)"
    local services=(web worker)
    for svc in "${services[@]}"; do
        local cid; cid="$(dc ps -q "$svc" 2>/dev/null || true)"
        [ -z "$cid" ] && continue
        local count
        count="$(dc logs --no-color --tail=200 "$svc" 2>/dev/null \
                    | grep -E '\[(ERROR|CRITICAL)\]' | wc -l | tr -d ' ')"
        if [ "$count" = "0" ]; then
            ok "$svc: no recent ERROR/CRITICAL lines"
        else
            warn "$svc: $count recent ERROR/CRITICAL lines"
            dc logs --no-color --tail=200 "$svc" 2>/dev/null \
                | grep -E '\[(ERROR|CRITICAL)\]' \
                | tail -n 5 \
                | sed "s/^/    ${DIM}|${NC} /"
        fi
    done
}

cmd_doctor() {
    DOCTOR_FIX=0
    DOCTOR_ISSUES=0
    if [ "${1:-}" = "--fix" ]; then
        DOCTOR_FIX=1
        section "Doctor (with --fix)"
        info "Auto-remediation is ENABLED. Safe operations only — never destroys data."
    else
        section "Doctor"
        info "Read-only diagnosis. Re-run with '--fix' to auto-remediate."
    fi

    # Each check returns nonzero on failure but we want to continue regardless.
    doctor_check_prereqs            || true
    doctor_check_env                || true
    doctor_check_compose_file       || true
    doctor_check_containers         || true
    doctor_check_db                 || true
    doctor_check_redis              || true
    doctor_check_migrations         || true
    doctor_check_health_endpoint    || true
    doctor_check_telegram_webhook   || true
    doctor_check_disk               || true
    doctor_check_recent_errors      || true

    section "Summary"
    if [ "$DOCTOR_ISSUES" -eq 0 ]; then
        ok "All checks passed."
    else
        warn "$DOCTOR_ISSUES issue(s) detected."
        if [ "$DOCTOR_FIX" = 0 ]; then
            info "Re-run with '$0 doctor --fix' to attempt safe auto-remediation."
        else
            info "Re-run plain '$0 doctor' afterwards to confirm the fixes stuck."
        fi
        return 1
    fi
}

# ── Internal helpers used by install/update ──────────────────────────────────

validate_env() {
    local missing=()
    for k in "${REQUIRED_KEYS[@]}"; do
        local v; v="$(env_get "$k" || true)"
        if is_placeholder "$v"; then
            missing+=("$k")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        err "These required keys are empty or still placeholders: ${missing[*]}"
        return 1
    fi
    local webhook_url; webhook_url="$(env_get WEBHOOK_URL || true)"
    if ! [[ "$webhook_url" =~ ^https:// ]]; then
        err "WEBHOOK_URL must start with https:// (Telegram rejects http)"
        return 1
    fi
    ok ".env validation passed"
}

wait_for_db() {
    info "Waiting for the database to accept connections…"
    local pg_user pg_db
    pg_user="$(env_get POSTGRES_USER || echo postgres)"
    pg_db="$(env_get POSTGRES_DB     || echo postgres)"
    local i=0
    until dc exec -T db pg_isready -U "$pg_user" -d "$pg_db" >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -gt 30 ]; then
            err "Postgres did not become ready in 60s"
            return 1
        fi
        sleep 2
    done
    ok "Postgres is ready"
}

wait_for_web() {
    info "Waiting for the web container's /health endpoint…"
    local i=0
    until dc exec -T web curl -sf http://localhost:8000/health >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -gt 30 ]; then
            warn "/health did not respond in 60s — see '$0 logs web' for clues"
            return 1
        fi
        sleep 2
    done
    ok "/health is up"
}

run_migrations() {
    dc exec -T web alembic upgrade head
}

set_telegram_webhook() {
    local token url secret
    token="$(env_get BOT_TOKEN     || true)"
    url="$(env_get   WEBHOOK_URL   || true)"
    secret="$(env_get WEBHOOK_SECRET || true)"

    if is_placeholder "$token" || is_placeholder "$url" || is_placeholder "$secret"; then
        warn "Cannot register webhook — BOT_TOKEN / WEBHOOK_URL / WEBHOOK_SECRET are not all set"
        return 1
    fi

    # NOTE: on the first request after lifespan startup the app already
    # registers its own webhook. This call is a safe net for redeployments
    # where the URL or secret has changed without a container restart.
    local resp
    resp="$(curl -s --max-time 5 \
        --data-urlencode "url=${url}" \
        --data-urlencode "secret_token=${secret}" \
        --data-urlencode "drop_pending_updates=false" \
        "https://api.telegram.org/bot${token}/setWebhook" || true)"
    if echo "$resp" | grep -q '"ok":true'; then
        ok "Telegram webhook registered: $url"
    else
        err "Telegram setWebhook failed: $resp"
        return 1
    fi
}

# ── Entrypoint ───────────────────────────────────────────────────────────────
main() {
    local cmd="${1:-help}"
    shift || true
    case "$cmd" in
        install)    cmd_install     "$@" ;;
        update)     cmd_update      "$@" ;;
        doctor)     cmd_doctor      "$@" ;;
        start)      cmd_start       "$@" ;;
        stop)       cmd_stop        "$@" ;;
        restart)    cmd_restart     "$@" ;;
        status)     cmd_status      "$@" ;;
        logs)       cmd_logs        "$@" ;;
        migrate)    cmd_migrate     "$@" ;;
        backup)     cmd_backup      "$@" ;;
        shell)      cmd_shell       "$@" ;;
        env-setup)  cmd_env_setup   "$@" ;;
        help|-h|--help) cmd_help ;;
        *)
            err "Unknown command: $cmd"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
