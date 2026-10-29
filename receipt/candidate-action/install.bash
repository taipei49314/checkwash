set -euo pipefail
selected="$CW_REQUESTED_PYTHON"
if [ -z "$selected" ]; then
  if [ -z "$CW_PYTHON_LOCATION" ]; then
    echo "Checkwash requires a trusted setup-python interpreter" >&2
    exit 2
  fi
  if [ "$RUNNER_OS" = "Windows" ]; then
    selected="$CW_PYTHON_LOCATION/python.exe"
  else
    selected="$CW_PYTHON_LOCATION/bin/python"
  fi
fi
case "$selected" in
  *$'\r'*|*$'\n'*) echo "Invalid Python path" >&2; exit 2 ;;
esac
workspace="$GITHUB_WORKSPACE"
# Native Windows drive paths work in Git Bash after slash normalization.
# Do not call ambient python/cygpath or any subject PATH executable.
if [ "$RUNNER_OS" = "Windows" ]; then
  selected="${selected//\\//}"
  workspace="${workspace//\\//}"
  case "$selected" in
    [A-Za-z]:/*) ;;
    *) echo "Python path must be an absolute drive path" >&2; exit 2 ;;
  esac
  compared="${selected,,}"
  workspace="${workspace,,}"
else
  case "$selected" in
    /*) ;;
    *) echo "Python path must be absolute" >&2; exit 2 ;;
  esac
  compared="$selected"
fi
case "$compared" in
  "$workspace"|"$workspace"/*)
    echo "Python cannot come from the subject checkout" >&2; exit 2 ;;
esac
if [ ! -f "$selected" ]; then
  echo "Trusted Python executable is unavailable" >&2
  exit 2
fi
"$selected" -I -B -X utf8 "$CW_ACTION_PATH/secure.py" install
