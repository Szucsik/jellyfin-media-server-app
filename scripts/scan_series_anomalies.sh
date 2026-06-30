#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_ENV_FILE="$REPO_ROOT/.env"
DEFAULT_OUTPUT_DIR="$SCRIPT_DIR/reports"
DEFAULT_MAX_SEASON=40

series_dir=""
env_file="$DEFAULT_ENV_FILE"
output_root="$DEFAULT_OUTPUT_DIR"
max_season="$DEFAULT_MAX_SEASON"

timestamp="$(date +"%Y%m%d_%H%M%S")"

usage() {
  cat <<'EOF'
Usage: ./scripts/scan_series_anomalies.sh [options]

Scans VOLUME_SERIES_DIR and generates anomaly reports as TXT files.

Options:
  --series-dir <path>   Override VOLUME_SERIES_DIR from .env
  --env-file <path>     Path to .env file (default: repo/.env)
  --output-dir <path>   Directory where timestamped report folder is created
  --max-season <num>    Maximum allowed season number (default: 40)
  --help                Show this help

Examples:
  ./scripts/scan_series_anomalies.sh
  ./scripts/scan_series_anomalies.sh --series-dir /mnt/media/shows
EOF
}

trim_quotes() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

read_env_value() {
  local key="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    return 1
  fi

  local line
  line="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi

  local value="${line#*=}"
  trim_quotes "$value"
}

normalize_show_name() {
  local name="$1"
  name="${name%% [[][iI][mM][dD][bB][iI][dD]-*}"
  name="$(echo "$name" | sed -E 's/[[:space:]]+$//')"
  printf '%s' "$name"
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --series-dir)
        series_dir="${2:-}"
        shift 2
        ;;
      --env-file)
        env_file="${2:-}"
        shift 2
        ;;
      --output-dir)
        output_root="${2:-}"
        shift 2
        ;;
      --max-season)
        max_season="${2:-}"
        shift 2
        ;;
      --help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done

  if ! [[ "$max_season" =~ ^[0-9]+$ ]]; then
    echo "--max-season must be a non-negative integer" >&2
    exit 1
  fi
}

parse_args "$@"

if [[ -z "$series_dir" ]]; then
  if series_from_env="$(read_env_value "VOLUME_SERIES_DIR" "$env_file")"; then
    series_dir="$series_from_env"
  elif [[ -n "${VOLUME_SERIES_DIR:-}" ]]; then
    series_dir="$VOLUME_SERIES_DIR"
  fi
fi

if [[ -z "$series_dir" ]]; then
  echo "Could not resolve VOLUME_SERIES_DIR. Use --series-dir or set it in .env / environment." >&2
  exit 1
fi

if [[ ! -d "$series_dir" ]]; then
  echo "Series directory not found: $series_dir" >&2
  exit 1
fi

mkdir -p "$output_root"
report_dir="$output_root/series_anomaly_report_${timestamp}"
mkdir -p "$report_dir"

summary_file="$report_dir/00_summary.txt"
root_invalid_file="$report_dir/01_root_level_invalid_directories.txt"
duplicate_file="$report_dir/02_duplicate_show_names.txt"
season_gap_file="$report_dir/03_season_jump_anomalies.txt"
season_gt_max_file="$report_dir/04_seasons_greater_than_max.txt"
missing_season_one_file="$report_dir/05_missing_season_1.txt"
episode_gap_file="$report_dir/06_episode_jump_anomalies.txt"

# Anomaly collectors.
declare -a root_level_invalid_dirs=()
declare -a duplicate_show_lines=()
declare -a season_gap_lines=()
declare -a season_gt_max_lines=()
declare -a missing_season_one_lines=()
declare -a episode_gap_lines=()

# Map normalized show name -> newline separated list of full paths.
declare -A show_name_to_paths=()

shopt -s nullglob

declare -a scan_entries=()
for entry in "$series_dir"/*; do
  [[ -d "$entry" ]] || continue
  scan_entries+=("$entry")
done

total_entries=${#scan_entries[@]}
processed_entries=0
progress_last_percent=-1

echo "Starting scan in: ${series_dir}"
echo "Root entries to scan: ${total_entries}"

for entry in "${scan_entries[@]}"; do
  processed_entries=$((processed_entries + 1))
  if ((total_entries > 0)); then
    progress_percent=$((processed_entries * 100 / total_entries))
    if ((progress_percent != progress_last_percent)); then
      echo "Progress: ${progress_percent}% (${processed_entries}/${total_entries}) - scanning $(basename "$entry")"
      progress_last_percent=$progress_percent
    fi
  fi

  entry_name="$(basename "$entry")"

  if [[ "$entry_name" =~ ^[Ss]eason[[:space:]_-]*[0-9]+$ ]]; then
    root_level_invalid_dirs+=("$entry")
    continue
  fi

  normalized_name="$(normalize_show_name "$entry_name")"
  if [[ -n "${show_name_to_paths[$normalized_name]+x}" ]]; then
    show_name_to_paths[$normalized_name]+=$'\n'"$entry"
  else
    show_name_to_paths[$normalized_name]="$entry"
  fi

  declare -a season_numbers=()

  for child in "$entry"/*; do
    [[ -d "$child" ]] || continue

    child_name="$(basename "$child")"
    if [[ "$child_name" =~ ^[Ss]eason[[:space:]_-]*([0-9]+)$ ]]; then
      season_number="${BASH_REMATCH[1]}"
      season_number="$((10#$season_number))"
      season_numbers+=("$season_number")

      declare -a episode_numbers=()
      for media_item in "$child"/*; do
        [[ -f "$media_item" || -L "$media_item" ]] || continue
        media_name="$(basename "$media_item")"

        if [[ "$media_name" =~ [Ss][0-9]{1,4}[Ee]([0-9]{1,4}) ]]; then
          episode_number="${BASH_REMATCH[1]}"
          episode_number="$((10#$episode_number))"
          episode_numbers+=("$episode_number")
        fi
      done

      if ((${#episode_numbers[@]} > 1)); then
        mapfile -t sorted_episodes < <(printf '%s\n' "${episode_numbers[@]}" | sort -n -u)
        previous_episode=""
        for current_episode in "${sorted_episodes[@]}"; do
          if [[ -n "$previous_episode" ]]; then
            jump=$((current_episode - previous_episode))
            if ((jump > 1)); then
              episode_gap_lines+=("$entry | Season ${season_number} | jumps from episode ${previous_episode} to ${current_episode} (jump=${jump})")
            fi
          fi
          previous_episode="$current_episode"
        done
      fi
    fi
  done

  if ((${#season_numbers[@]} == 0)); then
    missing_season_one_lines+=("$entry | no season directories found")
    continue
  fi

  mapfile -t sorted_unique_seasons < <(printf '%s\n' "${season_numbers[@]}" | sort -n -u)

  if [[ "${sorted_unique_seasons[0]}" != "1" ]]; then
    missing_season_one_lines+=("$entry | first season is ${sorted_unique_seasons[0]}")
  fi

  previous_season=""
  for current_season in "${sorted_unique_seasons[@]}"; do
    if ((current_season > max_season)); then
      season_gt_max_lines+=("$entry | Season ${current_season} > ${max_season}")
    fi

    if [[ -n "$previous_season" ]]; then
      jump=$((current_season - previous_season))
      if ((jump > 1)); then
        season_gap_lines+=("$entry | jumps from Season ${previous_season} to Season ${current_season} (jump=${jump})")
      fi
    fi
    previous_season="$current_season"
  done

done

echo "Progress: 100% (${processed_entries}/${total_entries}) - root scan completed"
echo "Analyzing duplicate show names..."

for show_name in "${!show_name_to_paths[@]}"; do
  mapfile -t paths < <(printf '%s\n' "${show_name_to_paths[$show_name]}" | sed '/^$/d')
  if ((${#paths[@]} > 1)); then
    duplicate_show_lines+=("Show name: ${show_name}")
    for show_path in "${paths[@]}"; do
      duplicate_show_lines+=("  - ${show_path}")
    done
    duplicate_show_lines+=("")
  fi
done

write_header() {
  local file_path="$1"
  local title="$2"
  cat >"$file_path" <<EOF
${title}
Generated: $(date '+%Y-%m-%d %H:%M:%S')
Series root: ${series_dir}

EOF
}

write_lines_or_none() {
  local file_path="$1"
  shift
  local -a lines=("$@")

  if ((${#lines[@]} == 0)); then
    echo "None found." >>"$file_path"
    return
  fi

  printf '%s\n' "${lines[@]}" | sed '/^$/N;/^\n$/D' >>"$file_path"
}

mapfile -t root_level_invalid_dirs_sorted < <(printf '%s\n' "${root_level_invalid_dirs[@]}" | sort -u)
mapfile -t duplicate_show_lines_sorted < <(printf '%s\n' "${duplicate_show_lines[@]}")
mapfile -t season_gap_lines_sorted < <(printf '%s\n' "${season_gap_lines[@]}" | sort -u)
mapfile -t season_gt_max_lines_sorted < <(printf '%s\n' "${season_gt_max_lines[@]}" | sort -u)
mapfile -t missing_season_one_lines_sorted < <(printf '%s\n' "${missing_season_one_lines[@]}" | sort -u)
mapfile -t episode_gap_lines_sorted < <(printf '%s\n' "${episode_gap_lines[@]}" | sort -u)

write_header "$root_invalid_file" "Root-Level Invalid Directories"
write_lines_or_none "$root_invalid_file" "${root_level_invalid_dirs_sorted[@]}"

write_header "$duplicate_file" "Duplicate Show Names"
write_lines_or_none "$duplicate_file" "${duplicate_show_lines_sorted[@]}"

write_header "$season_gap_file" "Season Number Jump Anomalies"
write_lines_or_none "$season_gap_file" "${season_gap_lines_sorted[@]}"

write_header "$season_gt_max_file" "Seasons Greater Than Max (${max_season})"
write_lines_or_none "$season_gt_max_file" "${season_gt_max_lines_sorted[@]}"

write_header "$missing_season_one_file" "Shows Missing Season 1"
write_lines_or_none "$missing_season_one_file" "${missing_season_one_lines_sorted[@]}"

write_header "$episode_gap_file" "Episode Number Jump Anomalies"
write_lines_or_none "$episode_gap_file" "${episode_gap_lines_sorted[@]}"

cat >"$summary_file" <<EOF
Series Directory Anomaly Scan Summary
Generated: $(date '+%Y-%m-%d %H:%M:%S')
Series root: ${series_dir}
Max season threshold: ${max_season}

Counts:
- Root-level invalid directories: ${#root_level_invalid_dirs_sorted[@]}
- Duplicate show names: $(printf '%s\n' "${duplicate_show_lines_sorted[@]}" | grep -c '^Show name:' || true)
- Season jump anomalies: ${#season_gap_lines_sorted[@]}
- Seasons greater than ${max_season}: ${#season_gt_max_lines_sorted[@]}
- Shows missing Season 1: ${#missing_season_one_lines_sorted[@]}
- Episode jump anomalies: ${#episode_gap_lines_sorted[@]}

Report files:
- ${root_invalid_file}
- ${duplicate_file}
- ${season_gap_file}
- ${season_gt_max_file}
- ${missing_season_one_file}
- ${episode_gap_file}
EOF

echo "Scan complete. Reports written to: ${report_dir}"
