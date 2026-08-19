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
  restore [FILE]     Restore the DB from a .sql.gz/.sql file (interactive if omitted)
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

# ── Interactive menu ─────────────────────────────────────────────────────────
#
# When the script is run with no arguments (or with `menu`), we drop into a
# polished, no-deps TUI built out of plain bash + ANSI. It shows the live
# state of the stack at the top, presents categorized actions, and pauses
# after each action so you can read the output before going back.
#
# CLI subcommands keep working (./install.sh doctor --fix, etc.) so this is
# strictly additive — power users can stay on the command line.

# Service indicator: ●  with color reflecting Docker state.
#   green  = running + healthy
#   yellow = running but unhealthy / starting
#   red    = stopped or missing
#   gray   = docker daemon unreachable (we can't tell)
menu_service_dot() {
    local svc="$1"
    if ! docker info >/dev/null 2>&1; then
        printf "%s●%s %s" "$DIM" "$NC" "$svc"
        return
    fi
    local cid; cid="$(dc ps -q "$svc" 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        printf "%s●%s %s" "$RED" "$NC" "$svc"
        return
    fi
    local state health
    state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
    if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }; then
        printf "%s●%s %s" "$GREEN" "$NC" "$svc"
    elif [ "$state" = "running" ]; then
        printf "%s●%s %s" "$YELLOW" "$NC" "$svc"
    else
        printf "%s●%s %s" "$RED" "$NC" "$svc"
    fi
}

menu_webhook_indicator() {
    local token; token="$(env_get BOT_TOKEN 2>/dev/null || true)"
    if is_placeholder "$token"; then
        printf "%s—%s no token" "$DIM" "$NC"
        return
    fi
    local resp; resp="$(curl -s --max-time 3 "https://api.telegram.org/bot${token}/getWebhookInfo" 2>/dev/null || true)"
    if [ -z "$resp" ]; then
        printf "%s—%s unreachable" "$DIM" "$NC"
        return
    fi
    local url; url="$(echo "$resp" | grep -oE '"url"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
    if [ -n "$url" ]; then
        printf "%sregistered%s" "$GREEN" "$NC"
    else
        printf "%snot set%s" "$RED" "$NC"
    fi
}

menu_git_indicator() {
    if [ -d "$PROJECT_ROOT/.git" ]; then
        local branch sha
        branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
        sha="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
        printf "%s  %s" "$branch" "$sha"
    else
        printf "%s—%s" "$DIM" "$NC"
    fi
}

menu_env_indicator() {
    if [ ! -f "$ENV_FILE" ]; then
        printf "%s.env missing%s" "$RED" "$NC"
        return
    fi
    local missing=0
    for k in "${REQUIRED_KEYS[@]}"; do
        local v; v="$(env_get "$k" 2>/dev/null || true)"
        if is_placeholder "$v"; then missing=$((missing + 1)); fi
    done
    if [ "$missing" -eq 0 ]; then
        printf "%sready%s" "$GREEN" "$NC"
    else
        printf "%s%d key(s) missing%s" "$YELLOW" "$missing" "$NC"
    fi
}

menu_clear_screen() {
    # Only clear if stdout is a real terminal — otherwise just print a separator.
    if [ -t 1 ]; then
        printf "\033[2J\033[H"
    else
        printf "\n\n%s\n\n" "────────────────────────────────────────────────────────────"
    fi
}

menu_header() {
    local title="$1"
    menu_clear_screen
    printf "%s╔══════════════════════════════════════════════════════════════╗%s\n" "$BOLD" "$NC"
    printf "%s║%s              Telegram AI Bot — %s%-30s%s%s║%s\n" \
           "$BOLD" "$NC" "$BOLD" "$title" "$NC" "$BOLD" "$NC"
    printf "%s║%s              git: %-43s %s║%s\n" \
           "$BOLD" "$NC" "$(menu_git_indicator)" "$BOLD" "$NC"
    printf "%s╠══════════════════════════════════════════════════════════════╣%s\n" "$BOLD" "$NC"
    printf "%s║%s  stack:   %s   %s   %s   %s   %s║%s\n" \
           "$BOLD" "$NC" \
           "$(menu_service_dot db)" "$(menu_service_dot redis)" \
           "$(menu_service_dot web)" "$(menu_service_dot worker)" \
           "$BOLD" "$NC"
    printf "%s║%s  webhook: %-50s %s║%s\n" \
           "$BOLD" "$NC" "$(menu_webhook_indicator)" "$BOLD" "$NC"
    printf "%s║%s  .env:    %-50s %s║%s\n" \
           "$BOLD" "$NC" "$(menu_env_indicator)" "$BOLD" "$NC"
    printf "%s╚══════════════════════════════════════════════════════════════╝%s\n" "$BOLD" "$NC"
    echo
}

menu_item() {
    # menu_item <number> <emoji> <label> [<hint>]
    local num="$1" emoji="$2" label="$3" hint="${4:-}"
    if [ -n "$hint" ]; then
        printf "  %s%2s)%s %s  %-32s %s%s%s\n" "$BOLD" "$num" "$NC" "$emoji" "$label" "$DIM" "$hint" "$NC"
    else
        printf "  %s%2s)%s %s  %s\n" "$BOLD" "$num" "$NC" "$emoji" "$label"
    fi
}

menu_pause() {
    echo
    printf "%sPress Enter to return to the menu…%s " "$DIM" "$NC"
    # shellcheck disable=SC2034
    read -r _ || true
}

menu_confirm() {
    # Returns 0 if user types y/yes, 1 otherwise. Defaults to NO.
    local prompt="${1:-Are you sure?}"
    printf "%s%s [y/N]:%s " "$YELLOW" "$prompt" "$NC"
    local reply
    read -r reply || return 1
    case "$reply" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

# Run a cmd_X function (or arbitrary command) inside the menu shell. We
# tolerate non-zero exit codes so a failing action doesn't kick the user
# out of the menu — they read the output, hit Enter, and try again.
menu_run() {
    set +e
    "$@"
    local rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        echo
        warn "Action exited with status $rc (returned to menu)."
    fi
    menu_pause
}

# ── Sub-menus ───────────────────────────────────────────────────────────────

menu_daily_ops() {
    while true; do
        menu_header "Daily operations"
        menu_item 1 "▶ " "Start"           "docker compose up -d"
        menu_item 2 "■ " "Stop"            "docker compose down (volumes preserved)"
        menu_item 3 "↻ " "Restart"         "docker compose restart"
        menu_item 4 "📊" "Status"          "containers + Telegram webhook"
        menu_item 5 "📜" "Tail web logs"
        menu_item 6 "📜" "Tail worker logs"
        menu_item 7 "📜" "Tail db logs"
        menu_item 8 "📜" "Tail redis logs"
        echo
        menu_item 0 "←" "Back"
        echo
        printf "%sChoose:%s " "$BOLD" "$NC"
        local ch; read -r ch || return 0
        case "$ch" in
            1) menu_run cmd_start ;;
            2) menu_run cmd_stop ;;
            3) menu_run cmd_restart ;;
            4) menu_run cmd_status ;;
            5) menu_run cmd_logs web ;;
            6) menu_run cmd_logs worker ;;
            7) menu_run cmd_logs db ;;
            8) menu_run cmd_logs redis ;;
            0|q|Q) return 0 ;;
            *) warn "Unknown choice: $ch"; sleep 1 ;;
        esac
    done
}

menu_backup_ops() {
    while true; do
        menu_header "Backup & restore"
        menu_item 1 "💾" "Take a manual backup now" "gzipped pg_dump → ./backups/"
        menu_item 2 "📋" "List existing backups"
        menu_item 3 "🔄" "Restore from a backup"   "interactive — pick a file"
        echo
        menu_item 0 "←" "Back"
        echo
        printf "%sChoose:%s " "$BOLD" "$NC"
        local ch; read -r ch || return 0
        case "$ch" in
            1) menu_run cmd_backup ;;
            2) menu_run menu_list_backups ;;
            3) menu_run menu_restore_backup ;;
            0|q|Q) return 0 ;;
            *) warn "Unknown choice: $ch"; sleep 1 ;;
        esac
    done
}

menu_list_backups() {
    section "Existing backups"
    local dir="$PROJECT_ROOT/backups"
    if [ ! -d "$dir" ] || [ -z "$(ls -A "$dir" 2>/dev/null)" ]; then
        info "No backups found in $dir"
        return 0
    fi
    ls -lh --time=ctime "$dir" 2>/dev/null || ls -lh "$dir"
}

# Restore a single backup file (.sql.gz or .sql) into the running db.
# Used by both the menu and `./install.sh restore <file>`.
_do_restore() {
    local file="$1"
    if [ ! -f "$file" ]; then
        err "Backup file not found: $file"
        return 1
    fi
    warn "About to restore $(basename "$file") into the running database."
    warn "This DROPs and recreates existing objects (--clean --if-exists in the dump)."
    warn "It is wise to take a fresh backup first ($0 backup)."
    if ! menu_confirm "Proceed with restore?"; then
        info "Cancelled"
        return 0
    fi
    local pg_user pg_db
    pg_user="$(env_get POSTGRES_USER || echo postgres)"
    pg_db="$(env_get POSTGRES_DB     || echo postgres)"
    info "Restoring into database '$pg_db'…"
    local rc=0
    if [[ "$file" == *.gz ]]; then
        gunzip -c "$file" | dc exec -T db psql -U "$pg_user" -d "$pg_db" >/dev/null || rc=$?
    else
        dc exec -T db psql -U "$pg_user" -d "$pg_db" < "$file" >/dev/null || rc=$?
    fi
    if [ "$rc" -eq 0 ]; then
        ok "Restore complete."
    else
        err "Restore failed (exit $rc); the database may be in a partial state."
        return 1
    fi
}

menu_restore_backup() {
    section "Restore from backup"
    local dir="$PROJECT_ROOT/backups"
    local files=()
    if [ -d "$dir" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] && files+=("$line")
        done < <(ls -1t "$dir"/*.sql.gz 2>/dev/null || true)
    fi

    if [ "${#files[@]}" -eq 0 ]; then
        # Normal when delete-after-send is on: the backup lives in Telegram.
        info "No local backups found. Download the .sql.gz the bot sent you,"
        info "put it on the server, and give its full path here."
        printf "Path to a .sql.gz / .sql file (empty to cancel): "
        local path; read -r path || return 0
        [ -z "$path" ] && { info "Cancelled"; return 0; }
        _do_restore "$path"
        return $?
    fi

    echo "Available local backups (newest first):"
    local idx=1
    for f in "${files[@]}"; do
        printf "  %s%2d)%s %s  (%s)\n" "$BOLD" "$idx" "$NC" "$(basename "$f")" "$(du -h "$f" | cut -f1)"
        idx=$((idx + 1))
    done
    echo
    printf "Pick a number, or paste a path (0 to cancel): "
    local pick; read -r pick || return 0
    [ "$pick" = "0" ] && { info "Cancelled"; return 0; }
    if [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -ge 1 ] && [ "$pick" -le "${#files[@]}" ]; then
        _do_restore "${files[$((pick - 1))]}"
    elif [ -f "$pick" ]; then
        _do_restore "$pick"
    else
        err "Invalid selection / path"
        return 1
    fi
}

cmd_restore() {
    section "Restore"
    local file="${1:-}"
    if [ -n "$file" ]; then
        _do_restore "$file"
        return $?
    fi
    menu_restore_backup
}

menu_advanced() {
    while true; do
        menu_header "Advanced"
        menu_item 1 "🐚" "Shell into web"        "/bin/bash inside the container"
        menu_item 2 "🐚" "Shell into worker"
        menu_item 3 "🐚" "Shell into db"          "psql access"
        menu_item 4 "🔧" "Rebuild .env"           "from .env.example"
        menu_item 5 "📐" "alembic upgrade head"   "apply pending migrations"
        menu_item 6 "🧹" "Prune dangling images"  "reclaim disk (safe)"
        menu_item 7 "⚠ " "Full reset"            "stop & DELETE volumes (DESTRUCTIVE)"
        echo
        menu_item 0 "←" "Back"
        echo
        printf "%sChoose:%s " "$BOLD" "$NC"
        local ch; read -r ch || return 0
        case "$ch" in
            1) menu_run cmd_shell web ;;
            2) menu_run cmd_shell worker ;;
            3) menu_run menu_shell_db ;;
            4) menu_run cmd_env_setup ;;
            5) menu_run cmd_migrate ;;
            6) menu_run menu_prune_images ;;
            7) menu_run menu_full_reset ;;
            0|q|Q) return 0 ;;
            *) warn "Unknown choice: $ch"; sleep 1 ;;
        esac
    done
}

menu_shell_db() {
    section "psql shell"
    local pg_user pg_db
    pg_user="$(env_get POSTGRES_USER || echo postgres)"
    pg_db="$(env_get POSTGRES_DB     || echo postgres)"
    dc exec db psql -U "$pg_user" -d "$pg_db"
}

menu_prune_images() {
    section "Prune dangling images"
    docker system prune -f
}

menu_full_reset() {
    section "Full reset"
    err "This will:"
    err "  - stop every container"
    err "  - DELETE the postgres_data and redis_data volumes"
    err "  - DROP all user, conversation, billing, and ledger data"
    err "It does NOT touch .env or ./backups/."
    echo
    if ! menu_confirm "Type 'y' to confirm full reset"; then
        info "Cancelled"
        return 0
    fi
    # Second confirmation gate — destructive.
    printf "%sType the word DELETE in capitals to proceed:%s " "$RED" "$NC"
    local confirm; read -r confirm || return 0
    if [ "$confirm" != "DELETE" ]; then
        info "Cancelled (confirmation phrase did not match)"
        return 0
    fi
    dc down -v
    ok "Volumes removed. Run 'Install' next to recreate the stack from scratch."
}

# ── Top-level menu ───────────────────────────────────────────────────────────

menu_main() {
    while true; do
        menu_header "Manager"
        printf "%s  Setup%s\n" "$DIM" "$NC"
        menu_item 1 "⚙️ " ".env setup"          "create or refresh .env"
        menu_item 2 "🚀" "Install"              "first-time: build, start, migrate"
        echo
        printf "%s  Maintenance%s\n" "$DIM" "$NC"
        menu_item 3 "🔄" "Update"               "git pull + rebuild + migrate"
        menu_item 4 "🩺" "Doctor"               "11-step diagnosis (read-only)"
        menu_item 5 "🛠 " "Doctor --fix"         "diagnose + safe auto-remediation"
        echo
        printf "%s  Operations%s\n" "$DIM" "$NC"
        menu_item 6 "⚡" "Daily operations >"   "start, stop, restart, logs, status"
        menu_item 7 "💾" "Backup & restore >"
        menu_item 8 "🧰" "Advanced >"           "shells, migrate, prune, full reset"
        echo
        menu_item 9 "📖" "Show help"
        menu_item 0 "❌" "Exit"
        echo
        printf "%sChoose:%s " "$BOLD" "$NC"
        local ch; read -r ch || return 0
        case "$ch" in
            1) menu_run cmd_env_setup ;;
            2) menu_run cmd_install ;;
            3) menu_run cmd_update ;;
            4) menu_run cmd_doctor ;;
            5) menu_run cmd_doctor --fix ;;
            6) menu_daily_ops ;;
            7) menu_backup_ops ;;
            8) menu_advanced ;;
            9) menu_run cmd_help ;;
            0|q|Q|exit|quit) clear 2>/dev/null || true; ok "Bye 👋"; return 0 ;;
            *) warn "Unknown choice: $ch"; sleep 1 ;;
        esac
    done
}

cmd_menu() { menu_main; }

# ── Entrypoint ───────────────────────────────────────────────────────────────
main() {
    # No args ⇒ launch the interactive menu (most users want this).
    if [ "$#" -eq 0 ]; then
        cmd_menu
        return $?
    fi

    local cmd="$1"
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
        restore)    cmd_restore     "$@" ;;
        shell)      cmd_shell       "$@" ;;
        env-setup)  cmd_env_setup   "$@" ;;
        menu)       cmd_menu        "$@" ;;
        help|-h|--help) cmd_help ;;
        *)
            err "Unknown command: $cmd"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
