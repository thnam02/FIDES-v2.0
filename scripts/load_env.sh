# Sourced by the demo scripts. Reads KEY=VALUE lines from $1 and exports each key
# that is not already set, so a variable set in the shell wins over .env.
load_env() {
  [ -f "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '' | '#'*) continue ;;
      *=*) ;;
      *) continue ;;
    esac
    key=${line%%=*}
    case "$key" in
      '' | *[!A-Za-z0-9_]*) continue ;;
    esac
    eval "present=\${$key+x}"
    if [ -z "$present" ]; then
      export "$key=${line#*=}"
    fi
  done <"$1"
}
