#!/usr/bin/env bash
set -euo pipefail

# Utilitário manual de demonstração; não faz parte da aplicação.
mode="${1:---dry-run}"
case "$mode" in
  --dry-run) transaction_end=ROLLBACK ;;
  --apply) transaction_end=COMMIT ;;
  *) echo 'Uso: bash seeds/ieducar/run.sh [--dry-run|--apply]' >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then echo 'Informe apenas --dry-run ou --apply.' >&2; exit 2; fi

institution="${SEED_INSTITUTION_ID:-1}"
schools="${SEED_SCHOOL_IDS:-2,3}"
year="${SEED_YEAR:-2026}"
[[ "$institution" =~ ^[1-9][0-9]*$ && "$schools" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ && "$year" =~ ^[0-9]{4}$ ]] || {
  echo 'Instituição/escolas devem ser códigos positivos; ano deve ter quatro dígitos.' >&2; exit 2;
}
seed_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$seed_dir/../.." && pwd)"
database_exec=(docker compose --project-directory "$repo_root" -f "$repo_root/docker-compose.yml" exec -T ieducar-db)
if [[ -n "${SEED_CONTAINER:-}" ]]; then
  database_exec=(docker exec -i "$SEED_CONTAINER")
fi
echo "Seed i-Educar: $mode; instituição=$institution; escolas=$schools; ano=$year"
{
  printf 'BEGIN;\n'
  printf "SELECT set_config('seed.institution', '%s', true);\n" "$institution"
  printf "SELECT set_config('seed.schools', '%s', true);\n" "$schools"
  printf "SELECT set_config('seed.year', '%s', true);\n" "$year"
  cat "$seed_dir/professores.sql"
  printf '\n%s;\n' "$transaction_end"
} | "${database_exec[@]}" \
  psql -X -U "${SEED_DB_USER:-ieducar}" -d "${SEED_DB_NAME:-ieducar}" \
  -v ON_ERROR_STOP=1
